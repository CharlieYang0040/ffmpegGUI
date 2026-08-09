#include "color/grade_processor.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <optional>
#include <stdexcept>

namespace ffgui {
namespace {

double parameter(const GradeNode& node, const char* name, double fallback) {
    const auto found = node.parameters.find(name);
    return found == node.parameters.end() ? fallback : found->second;
}

float curve_value(const std::vector<CurvePoint>& points, float value) {
    if (points.empty()) return value;
    if (value <= points.front().x) return static_cast<float>(points.front().y);
    if (value >= points.back().x) return static_cast<float>(points.back().y);
    const auto upper = std::upper_bound(points.begin(), points.end(), value,
        [](double needle, const CurvePoint& point) { return needle < point.x; });
    const auto& right = *upper;
    const auto& left = *(upper - 1);
    const auto amount = (value - static_cast<float>(left.x)) /
        static_cast<float>(right.x - left.x);
    return std::lerp(static_cast<float>(left.y), static_cast<float>(right.y), amount);
}

struct PrimaryState final {
    float exposure{};
    float contrast{};
    float pivot{};
    float saturation{};
    std::array<float, 3> lift{};
    std::array<float, 3> inverse_gamma{};
    std::array<float, 3> gain{};
    std::array<float, 3> offset{};
};

PrimaryState compile_primary(const GradeNode& node) {
    if (parameter(node, "temperature", 0.0) != 0.0 ||
        parameter(node, "tint", 0.0) != 0.0 || parameter(node, "hue", 0.0) != 0.0 ||
        parameter(node, "colorBoost", 0.0) != 0.0) {
        throw std::invalid_argument("temperature, tint, hue and color boost require the GPU grade stage");
    }
    PrimaryState state;
    state.exposure = static_cast<float>(std::exp2(parameter(node, "exposure", 0.0)));
    state.contrast = static_cast<float>(parameter(node, "contrast", 1.0));
    state.pivot = static_cast<float>(parameter(node, "pivot", 0.435));
    state.saturation = static_cast<float>(parameter(node, "saturation", 1.0));
    const std::array<const char*, 3> lift{"liftR", "liftG", "liftB"};
    const std::array<const char*, 3> gamma{"gammaR", "gammaG", "gammaB"};
    const std::array<const char*, 3> gain{"gainR", "gainG", "gainB"};
    const std::array<const char*, 3> offset{"offsetR", "offsetG", "offsetB"};
    for (std::size_t channel = 0; channel < 3; ++channel) {
        state.lift[channel] = static_cast<float>(parameter(node, lift[channel], 0.0));
        state.inverse_gamma[channel] = static_cast<float>(
            1.0 / std::max(0.001, parameter(node, gamma[channel], 1.0)));
        state.gain[channel] = static_cast<float>(parameter(node, gain[channel], 1.0));
        state.offset[channel] = static_cast<float>(parameter(node, offset[channel], 0.0));
    }
    return state;
}

void apply_primary(float* rgb, const PrimaryState& state) {
    for (std::size_t channel = 0; channel < 3; ++channel) {
        auto value = rgb[channel] * state.exposure;
        value = (value - state.pivot) * state.contrast + state.pivot;
        value += state.lift[channel];
        value = std::copysign(std::pow(std::abs(value), state.inverse_gamma[channel]), value);
        value = value * state.gain[channel] + state.offset[channel];
        rgb[channel] = value;
    }
    constexpr std::array<float, 3> acescgLuma{0.2722287F, 0.6740818F, 0.0536895F};
    const auto luma = rgb[0] * acescgLuma[0] + rgb[1] * acescgLuma[1] + rgb[2] * acescgLuma[2];
    for (std::size_t channel = 0; channel < 3; ++channel) {
        rgb[channel] = luma + (rgb[channel] - luma) * state.saturation;
    }
}

using RgbMatrix = std::array<std::array<float, 3>, 3>;

RgbMatrix compile_rgb_mixer(const GradeNode& node) {
    return RgbMatrix{{
        {static_cast<float>(parameter(node, "rr", 1.0)),
         static_cast<float>(parameter(node, "rg", 0.0)),
         static_cast<float>(parameter(node, "rb", 0.0))},
        {static_cast<float>(parameter(node, "gr", 0.0)),
         static_cast<float>(parameter(node, "gg", 1.0)),
         static_cast<float>(parameter(node, "gb", 0.0))},
        {static_cast<float>(parameter(node, "br", 0.0)),
         static_cast<float>(parameter(node, "bg", 0.0)),
         static_cast<float>(parameter(node, "bb", 1.0))}}};
}

void apply_rgb_mixer(float* rgb, const RgbMatrix& matrix) {
    const auto input = std::array<float, 3>{rgb[0], rgb[1], rgb[2]};
    for (std::size_t row = 0; row < 3; ++row) {
        rgb[row] = input[0] * matrix[row][0] + input[1] * matrix[row][1] +
                   input[2] * matrix[row][2];
    }
}

}  // namespace

void apply_grade_graph_rgba32f(float* pixels, std::size_t pixel_count, const GradeGraph& graph) {
    if (pixels == nullptr && pixel_count != 0) throw std::invalid_argument("grade pixels are null");
    const auto unsupported = graph.render_unsupported_nodes();
    if (!unsupported.empty()) throw std::invalid_argument("grade graph contains an unsupported render node");
    for (const auto& node : graph.nodes()) {
        if (!node.enabled || node.mix <= 0.0) continue;
        const auto primary = node.type == GradeNodeType::primary
            ? std::optional<PrimaryState>{compile_primary(node)} : std::nullopt;
        const auto mixer = node.type == GradeNodeType::rgb_mixer
            ? std::optional<RgbMatrix>{compile_rgb_mixer(node)} : std::nullopt;
        const auto curve = node.type == GradeNodeType::rgb_curves
            ? node.curves.find("master") : node.curves.end();
        for (std::size_t pixel = 0; pixel < pixel_count; ++pixel) {
            auto* rgba = pixels + pixel * 4;
            const std::array<float, 3> original{rgba[0], rgba[1], rgba[2]};
            if (primary.has_value()) apply_primary(rgba, *primary);
            else if (mixer.has_value()) apply_rgb_mixer(rgba, *mixer);
            else if (node.type == GradeNodeType::rgb_curves) {
                if (curve != node.curves.end()) {
                    for (std::size_t channel = 0; channel < 3; ++channel) {
                        rgba[channel] = curve_value(curve->second, rgba[channel]);
                    }
                }
            }
            for (std::size_t channel = 0; channel < 3; ++channel) {
                rgba[channel] = std::lerp(original[channel], rgba[channel], static_cast<float>(node.mix));
            }
        }
    }
}

}  // namespace ffgui
