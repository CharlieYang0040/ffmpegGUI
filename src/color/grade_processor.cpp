#include "color/grade_processor.hpp"

#include <OpenColorIO/OpenColorIO.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <unordered_map>

namespace OCIO = OCIO_NAMESPACE;

namespace ffgui {
namespace {

struct CachedLut final {
    std::filesystem::file_time_type modified;
    std::uintmax_t size{};
    OCIO::ConstCPUProcessorRcPtr processor;
};

OCIO::ConstCPUProcessorRcPtr grade_lut_processor(const std::string& path) {
    if (path.empty()) throw std::invalid_argument("LUT file path is empty");
    const std::filesystem::path inputPath{std::u8string(path.begin(), path.end())};
    std::error_code error;
    auto resolved = std::filesystem::weakly_canonical(inputPath, error);
    if (error) resolved = std::filesystem::absolute(inputPath, error);
    if (error || !std::filesystem::is_regular_file(resolved, error) || error) {
        throw std::runtime_error("LUT file is missing or unreadable: " + path);
    }
    const auto modified = std::filesystem::last_write_time(resolved, error);
    if (error) throw std::runtime_error("LUT modification time could not be read: " + path);
    const auto size = std::filesystem::file_size(resolved, error);
    if (error || size == 0) throw std::runtime_error("LUT file is empty or unreadable: " + path);
    const auto key = resolved.generic_u8string();
    const std::string cacheKey(key.begin(), key.end());

    static std::mutex cacheMutex;
    static std::unordered_map<std::string, CachedLut> cache;
    std::scoped_lock lock(cacheMutex);
    if (const auto found = cache.find(cacheKey); found != cache.end() &&
        found->second.modified == modified && found->second.size == size) {
        return found->second.processor;
    }
    try {
        const auto transform = OCIO::FileTransform::Create();
        transform->setSrc(cacheKey.c_str());
        transform->setInterpolation(OCIO::INTERP_BEST);
        transform->validate();
        const auto config = OCIO::Config::CreateRaw();
        const auto processor = config->getProcessor(transform)->getDefaultCPUProcessor();
        if (!processor) throw std::runtime_error("OpenColorIO returned no LUT processor");
        cache[cacheKey] = CachedLut{modified, size, processor};
        return processor;
    } catch (const OCIO::Exception& exception) {
        throw std::runtime_error(
            std::string{"OpenColorIO LUT load failed: "} + exception.what());
    }
}

double parameter(
    const GradeNode& node, const char* name, double fallback, std::int64_t sourceTime) {
    if (const auto keyed = node.parameter_keyframes.find(name);
        keyed != node.parameter_keyframes.end() && !keyed->second.empty()) {
        const auto& values = keyed->second;
        if (sourceTime <= values.front().source_time) return values.front().value;
        if (sourceTime >= values.back().source_time) return values.back().value;
        const auto upper = std::upper_bound(values.begin(), values.end(), sourceTime,
            [](std::int64_t time, const GradeParameterKeyframe& keyframe) {
                return time < keyframe.source_time;
            });
        const auto& right = *upper;
        const auto& left = *(upper - 1);
        const auto amount = static_cast<double>(sourceTime - left.source_time) /
            static_cast<double>(right.source_time - left.source_time);
        return std::lerp(left.value, right.value, amount);
    }
    const auto found = node.parameters.find(name);
    return found == node.parameters.end() ? fallback : found->second;
}

double parameter(const GradeNode& node, const char* name, double fallback) {
    return parameter(node, name, fallback, 0);
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

float smoothstep(float edge0, float edge1, float value) {
    if (edge1 <= edge0) return value >= edge1 ? 1.0F : 0.0F;
    const auto amount = std::clamp((value - edge0) / (edge1 - edge0), 0.0F, 1.0F);
    return amount * amount * (3.0F - 2.0F * amount);
}

constexpr std::array<float, 3> acescg_luma{0.2722287F, 0.6740818F, 0.0536895F};

float luminance(const float* rgb) {
    return rgb[0] * acescg_luma[0] + rgb[1] * acescg_luma[1] +
           rgb[2] * acescg_luma[2];
}

struct Hsv final { float hue{}; float saturation{}; float value{}; };

Hsv rgb_to_hsv(const float* rgb) {
    const auto minimum = std::min({rgb[0], rgb[1], rgb[2]});
    const auto maximum = std::max({rgb[0], rgb[1], rgb[2]});
    const auto delta = maximum - minimum;
    Hsv result;
    result.value = maximum;
    result.saturation = std::abs(maximum) > 1.0e-8F ? delta / std::abs(maximum) : 0.0F;
    if (delta <= 1.0e-8F) return result;
    if (maximum == rgb[0]) result.hue = (rgb[1] - rgb[2]) / delta;
    else if (maximum == rgb[1]) result.hue = 2.0F + (rgb[2] - rgb[0]) / delta;
    else result.hue = 4.0F + (rgb[0] - rgb[1]) / delta;
    result.hue = std::fmod(result.hue / 6.0F + 1.0F, 1.0F);
    return result;
}

void hsv_to_rgb(const Hsv& hsv, float* rgb) {
    const auto hue = std::fmod(hsv.hue + 10.0F, 1.0F) * 6.0F;
    const auto saturation = std::max(0.0F, hsv.saturation);
    const auto chroma = std::abs(hsv.value) * saturation;
    const auto x = chroma * (1.0F - std::abs(std::fmod(hue, 2.0F) - 1.0F));
    std::array<float, 3> base{};
    if (hue < 1.0F) base = {chroma, x, 0.0F};
    else if (hue < 2.0F) base = {x, chroma, 0.0F};
    else if (hue < 3.0F) base = {0.0F, chroma, x};
    else if (hue < 4.0F) base = {0.0F, x, chroma};
    else if (hue < 5.0F) base = {x, 0.0F, chroma};
    else base = {chroma, 0.0F, x};
    const auto match = hsv.value >= 0.0F ? hsv.value - chroma : hsv.value + chroma;
    for (std::size_t channel = 0; channel < 3; ++channel) rgb[channel] = base[channel] + match;
}

void apply_hue_and_vibrance(float* rgb, float hue_degrees, float color_boost) {
    auto hsv = rgb_to_hsv(rgb);
    hsv.hue = std::fmod(hsv.hue + hue_degrees / 360.0F + 1.0F, 1.0F);
    const auto boost = color_boost / 100.0F;
    const auto protection = 1.0F - std::clamp(hsv.saturation, 0.0F, 1.0F);
    hsv.saturation = std::max(0.0F, hsv.saturation * (1.0F + boost * protection * 2.0F));
    hsv_to_rgb(hsv, rgb);
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
    std::array<float, 3> shadow{};
    std::array<float, 3> midtone{};
    std::array<float, 3> highlight{};
    float low_range{};
    float high_range{};
};

PrimaryState compile_primary(const GradeNode& node) {
    PrimaryState state;
    state.exposure = static_cast<float>(std::exp2(parameter(node, "exposure", 0.0)));
    state.contrast = static_cast<float>(parameter(node, "contrast", 1.0));
    state.pivot = static_cast<float>(parameter(node, "pivot", 0.435));
    state.saturation = static_cast<float>(parameter(node, "saturation", 1.0));
    const std::array<const char*, 3> lift{"liftR", "liftG", "liftB"};
    const std::array<const char*, 3> gamma{"gammaR", "gammaG", "gammaB"};
    const std::array<const char*, 3> gain{"gainR", "gainG", "gainB"};
    const std::array<const char*, 3> offset{"offsetR", "offsetG", "offsetB"};
    const std::array<const char*, 3> shadow{"shadowR", "shadowG", "shadowB"};
    const std::array<const char*, 3> midtone{"midtoneR", "midtoneG", "midtoneB"};
    const std::array<const char*, 3> highlight{"highlightR", "highlightG", "highlightB"};
    for (std::size_t channel = 0; channel < 3; ++channel) {
        state.lift[channel] = static_cast<float>(parameter(node, lift[channel], 0.0));
        state.inverse_gamma[channel] = static_cast<float>(
            1.0 / std::max(0.001, parameter(node, gamma[channel], 1.0)));
        state.gain[channel] = static_cast<float>(parameter(node, gain[channel], 1.0));
        state.offset[channel] = static_cast<float>(parameter(node, offset[channel], 0.0));
        state.shadow[channel] = static_cast<float>(parameter(node, shadow[channel], 0.0));
        state.midtone[channel] = static_cast<float>(parameter(node, midtone[channel], 0.0));
        state.highlight[channel] = static_cast<float>(parameter(node, highlight[channel], 0.0));
    }
    state.low_range = static_cast<float>(parameter(node, "lowRange", 0.25));
    state.high_range = static_cast<float>(parameter(node, "highRange", 0.75));
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
    const auto tonalLuma = std::max(0.0F, luminance(rgb));
    const auto normalized = tonalLuma / (1.0F + tonalLuma);
    const auto shadowWeight = 1.0F - smoothstep(0.0F, state.low_range, normalized);
    const auto highlightWeight = smoothstep(state.high_range, 1.0F, normalized);
    const auto midtoneWeight = std::max(0.0F, 1.0F - shadowWeight - highlightWeight);
    for (std::size_t channel = 0; channel < 3; ++channel) {
        rgb[channel] += state.shadow[channel] * shadowWeight +
            state.midtone[channel] * midtoneWeight +
            state.highlight[channel] * highlightWeight;
    }
    const auto luma = luminance(rgb);
    for (std::size_t channel = 0; channel < 3; ++channel) {
        rgb[channel] = luma + (rgb[channel] - luma) * state.saturation;
    }
}

void apply_primary_creative(float* rgb, const GradeNode& node) {
    const auto temperature = static_cast<float>(parameter(node, "temperature", 0.0));
    const auto tint = static_cast<float>(parameter(node, "tint", 0.0));
    rgb[0] *= std::exp2(temperature * 0.003F + tint * 0.001F);
    rgb[1] *= std::exp2(-tint * 0.002F);
    rgb[2] *= std::exp2(-temperature * 0.003F + tint * 0.001F);
    apply_hue_and_vibrance(
        rgb, static_cast<float>(parameter(node, "hue", 0.0)),
        static_cast<float>(parameter(node, "colorBoost", 0.0)));
}

struct LogState final {
    std::array<float, 3> shadow{};
    std::array<float, 3> midtone{};
    std::array<float, 3> highlight{};
    std::array<float, 3> offset{};
    float low_range{};
    float high_range{};
};

LogState compile_log(const GradeNode& node) {
    LogState state;
    const std::array<const char*, 3> shadow{"shadowR", "shadowG", "shadowB"};
    const std::array<const char*, 3> midtone{"midtoneR", "midtoneG", "midtoneB"};
    const std::array<const char*, 3> highlight{"highlightR", "highlightG", "highlightB"};
    const std::array<const char*, 3> offset{"offsetR", "offsetG", "offsetB"};
    for (std::size_t channel = 0; channel < 3; ++channel) {
        state.shadow[channel] = static_cast<float>(parameter(node, shadow[channel], 0.0));
        state.midtone[channel] = static_cast<float>(parameter(node, midtone[channel], 0.0));
        state.highlight[channel] = static_cast<float>(parameter(node, highlight[channel], 0.0));
        state.offset[channel] = static_cast<float>(parameter(node, offset[channel], 0.0));
    }
    state.low_range = static_cast<float>(parameter(node, "lowRange", 0.25));
    state.high_range = static_cast<float>(parameter(node, "highRange", 0.75));
    return state;
}

void apply_log(float* rgb, const LogState& state) {
    const auto luma = std::max(0.0F, luminance(rgb));
    const auto normalized = luma / (1.0F + luma);
    const auto shadowWeight = 1.0F - smoothstep(0.0F, state.low_range, normalized);
    const auto highlightWeight = smoothstep(state.high_range, 1.0F, normalized);
    const auto midtoneWeight = std::max(0.0F, 1.0F - shadowWeight - highlightWeight);
    for (std::size_t channel = 0; channel < 3; ++channel) {
        rgb[channel] += state.offset[channel] + state.shadow[channel] * shadowWeight +
            state.midtone[channel] * midtoneWeight +
            state.highlight[channel] * highlightWeight;
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

const std::vector<CurvePoint>* find_curve(const GradeNode& node, const char* name) {
    const auto found = node.curves.find(name);
    return found == node.curves.end() ? nullptr : &found->second;
}

void apply_rgb_curves(float* rgb, const GradeNode& node) {
    if (const auto* master = find_curve(node, "master")) {
        for (std::size_t channel = 0; channel < 3; ++channel) {
            rgb[channel] = curve_value(*master, rgb[channel]);
        }
    }
    constexpr std::array<const char*, 3> names{"red", "green", "blue"};
    for (std::size_t channel = 0; channel < 3; ++channel) {
        if (const auto* curve = find_curve(node, names[channel])) {
            rgb[channel] = curve_value(*curve, rgb[channel]);
        }
    }
}

void apply_hue_curves(float* rgb, const GradeNode& node) {
    auto hsv = rgb_to_hsv(rgb);
    auto luma = std::max(0.0F, luminance(rgb));
    const auto normalizedLuma = luma / (1.0F + luma);
    const auto originalHue = hsv.hue;
    const auto originalSaturation = std::clamp(hsv.saturation, 0.0F, 1.0F);
    if (const auto* curve = find_curve(node, "hueVsHue")) hsv.hue = curve_value(*curve, originalHue);
    if (const auto* curve = find_curve(node, "hueVsSat")) {
        hsv.saturation *= std::max(0.0F, 1.0F + 2.0F *
            (curve_value(*curve, originalHue) - originalHue));
    }
    if (const auto* curve = find_curve(node, "lumVsSat")) {
        hsv.saturation *= std::max(0.0F, 1.0F + 2.0F *
            (curve_value(*curve, normalizedLuma) - normalizedLuma));
    }
    if (const auto* curve = find_curve(node, "satVsSat")) {
        hsv.saturation = std::max(
            0.0F, hsv.saturation + curve_value(*curve, originalSaturation) - originalSaturation);
    }
    auto valueScale = 1.0F;
    if (const auto* curve = find_curve(node, "hueVsLum")) {
        valueScale *= std::max(0.0F, 1.0F + 2.0F *
            (curve_value(*curve, originalHue) - originalHue));
    }
    if (const auto* curve = find_curve(node, "satVsLum")) {
        valueScale *= std::max(0.0F, 1.0F + 2.0F *
            (curve_value(*curve, originalSaturation) - originalSaturation));
    }
    if (const auto* curve = find_curve(node, "lumVsLum")) {
        const auto mapped = std::clamp(curve_value(*curve, normalizedLuma), 0.0F, 0.999999F);
        const auto mappedLuma = mapped / std::max(1.0e-6F, 1.0F - mapped);
        valueScale *= luma > 1.0e-8F ? mappedLuma / luma : 1.0F;
    }
    hsv.value *= valueScale;
    hsv_to_rgb(hsv, rgb);
}

void apply_hdr_zones(float* rgb, const GradeNode& node) {
    const auto luma = std::max(1.0e-6F, luminance(rgb));
    const auto logLuma = std::log2(luma / 0.18F);
    constexpr std::array<const char*, 5> exposureNames{
        "blackExposure", "shadowExposure", "midtoneExposure",
        "highlightExposure", "specularExposure"};
    constexpr std::array<const char*, 5> centerNames{
        "blackCenter", "shadowCenter", "midtoneCenter",
        "highlightCenter", "specularCenter"};
    const auto width = std::max(0.1F, static_cast<float>(parameter(node, "zoneWidth", 2.0)));
    std::array<float, 5> weights{};
    auto totalWeight = 0.0F;
    for (std::size_t index = 0; index < weights.size(); ++index) {
        const auto center = static_cast<float>(parameter(node, centerNames[index],
            static_cast<double>(static_cast<int>(index) * 2 - 4)));
        const auto distance = (logLuma - center) / width;
        weights[index] = std::exp(-0.5F * distance * distance);
        totalWeight += weights[index];
    }
    auto exposure = 0.0F;
    for (std::size_t index = 0; index < weights.size(); ++index) {
        exposure += weights[index] / std::max(1.0e-6F, totalWeight) *
            static_cast<float>(parameter(node, exposureNames[index], 0.0));
    }
    const auto scale = std::exp2(exposure);
    for (std::size_t channel = 0; channel < 3; ++channel) rgb[channel] *= scale;
}

float circular_parameter(const GradeNode& node, const char* prefix, int count, float position,
                         float fallback) {
    const auto scaled = std::fmod(position + 10.0F, 1.0F) * count;
    const auto left = static_cast<int>(std::floor(scaled)) % count;
    const auto right = (left + 1) % count;
    const auto amount = scaled - std::floor(scaled);
    return std::lerp(
        static_cast<float>(parameter(node, (std::string{prefix} + std::to_string(left)).c_str(), fallback)),
        static_cast<float>(parameter(node, (std::string{prefix} + std::to_string(right)).c_str(), fallback)),
        amount);
}

void apply_inside_grade(float* rgb, float exposure, float saturation) {
    const auto scale = std::exp2(exposure);
    for (std::size_t channel = 0; channel < 3; ++channel) rgb[channel] *= scale;
    const auto luma = luminance(rgb);
    for (std::size_t channel = 0; channel < 3; ++channel) {
        rgb[channel] = luma + (rgb[channel] - luma) * saturation;
    }
}

float circular_hue_distance(float left, float right) {
    const auto delta = std::abs(left - right);
    return std::min(delta, 1.0F - delta);
}

float qualifier_key(const float* rgb, const GradeNode& node) {
    const auto hsv = rgb_to_hsv(rgb);
    const auto hueCenter = static_cast<float>(parameter(node, "hueCenter", 0.0) / 360.0);
    const auto hueWidth = std::max(
        0.0F, static_cast<float>(parameter(node, "hueWidth", 40.0) / 360.0));
    const auto hueSoft = std::max(
        0.0F, static_cast<float>(parameter(node, "hueSoft", 10.0) / 360.0));
    const auto satLow = static_cast<float>(parameter(node, "satLow", 0.15));
    const auto satHigh = static_cast<float>(parameter(node, "satHigh", 1.0));
    const auto satSoft = std::max(0.0F, static_cast<float>(parameter(node, "satSoft", 0.05)));
    const auto lumaLow = static_cast<float>(parameter(node, "lumaLow", 0.0));
    const auto lumaHigh = static_cast<float>(parameter(node, "lumaHigh", 1.0));
    const auto lumaSoft = std::max(0.0F, static_cast<float>(parameter(node, "lumaSoft", 0.05)));
    const auto hueKey = 1.0F - smoothstep(hueWidth, hueWidth + hueSoft,
        circular_hue_distance(hsv.hue, hueCenter));
    const auto satKey = smoothstep(satLow - satSoft, satLow, hsv.saturation) *
        (1.0F - smoothstep(satHigh, satHigh + satSoft, hsv.saturation));
    const auto luma = luminance(rgb);
    const auto lumaKey = smoothstep(lumaLow - lumaSoft, lumaLow, luma) *
        (1.0F - smoothstep(lumaHigh, lumaHigh + lumaSoft, luma));
    auto key = hueKey * satKey * lumaKey;
    if (parameter(node, "invert", 0.0) >= 0.5) key = 1.0F - key;
    return std::clamp(key, 0.0F, 1.0F);
}

float power_window_key(
    std::size_t x, std::size_t y, std::size_t width, std::size_t height, const GradeNode& node) {
    if (width == 0 || height == 0) return 1.0F;
    const auto centerX = static_cast<float>(parameter(node, "centerX", 0.5));
    const auto centerY = static_cast<float>(parameter(node, "centerY", 0.5));
    const auto sizeX = std::max(1.0e-4F, static_cast<float>(parameter(node, "sizeX", 0.45)));
    const auto sizeY = std::max(1.0e-4F, static_cast<float>(parameter(node, "sizeY", 0.45)));
    const auto rotation = static_cast<float>(parameter(node, "rotation", 0.0) * 3.14159265358979323846 / 180.0);
    const auto softness = std::max(0.0F, static_cast<float>(parameter(node, "softness", 0.12)));
    const auto nx = (static_cast<float>(x) + 0.5F) / static_cast<float>(width);
    const auto ny = (static_cast<float>(y) + 0.5F) / static_cast<float>(height);
    const auto dx = nx - centerX;
    const auto dy = ny - centerY;
    const auto cosine = std::cos(-rotation);
    const auto sine = std::sin(-rotation);
    const auto rx = dx * cosine - dy * sine;
    const auto ry = dx * sine + dy * cosine;
    float distance = 0.0F;
    if (parameter(node, "shape", 0.0) >= 0.5) {
        distance = std::max(std::abs(rx) / (sizeX * 0.5F), std::abs(ry) / (sizeY * 0.5F));
    } else {
        const auto ex = rx / (sizeX * 0.5F);
        const auto ey = ry / (sizeY * 0.5F);
        distance = std::sqrt(ex * ex + ey * ey);
    }
    auto key = 1.0F - smoothstep(1.0F, 1.0F + softness, distance);
    if (parameter(node, "invert", 0.0) >= 0.5) key = 1.0F - key;
    return std::clamp(key, 0.0F, 1.0F);
}

void apply_masked_inside(float* rgb, float key, const GradeNode& node) {
    if (key <= 0.0F) return;
    const std::array<float, 3> original{rgb[0], rgb[1], rgb[2]};
    apply_inside_grade(
        rgb,
        static_cast<float>(parameter(node, "insideExposure", 0.0)),
        static_cast<float>(parameter(node, "insideSaturation", 1.0)));
    for (std::size_t channel = 0; channel < 3; ++channel) {
        rgb[channel] = std::lerp(original[channel], rgb[channel], key);
    }
}

void apply_color_warper(float* rgb, const GradeNode& node) {
    auto hsv = rgb_to_hsv(rgb);
    const auto hueShift = circular_parameter(node, "hueShift", 12, hsv.hue, 0.0F);
    const auto saturationScale = circular_parameter(node, "satScale", 12, hsv.hue, 1.0F);
    hsv.hue = std::fmod(hsv.hue + hueShift / 360.0F + 1.0F, 1.0F);
    hsv.saturation = std::max(0.0F, hsv.saturation * saturationScale);
    const auto luma = std::max(0.0F, luminance(rgb));
    const auto normalized = std::clamp(luma / (1.0F + luma), 0.0F, 0.999999F) * 7.0F;
    const auto low = static_cast<int>(std::floor(normalized));
    const auto high = std::min(7, low + 1);
    const auto scale = std::lerp(
        static_cast<float>(parameter(node, ("lumScale" + std::to_string(low)).c_str(), 1.0)),
        static_cast<float>(parameter(node, ("lumScale" + std::to_string(high)).c_str(), 1.0)),
        normalized - low);
    hsv.value *= scale;
    hsv_to_rgb(hsv, rgb);
}

}  // namespace

void apply_grade_node_matte_bgra8(
    std::uint8_t* pixels,
    std::size_t width,
    std::size_t height,
    std::size_t stride,
    const GradeNode& sourceNode,
    bool monochrome,
    std::int64_t source_time) {
    if (pixels == nullptr || width == 0 || height == 0 ||
        (sourceNode.type != GradeNodeType::qualifier &&
         sourceNode.type != GradeNodeType::power_window)) return;
    auto node = sourceNode;
    for (auto& [name, value] : node.parameters) {
        value = evaluate_grade_parameter(sourceNode, name, value, source_time);
    }
    for (std::size_t y = 0; y < height; ++y) {
        auto* row = pixels + y * stride;
        for (std::size_t x = 0; x < width; ++x) {
            auto* bgra = row + x * 4;
            const float rgb[3]{bgra[2] / 255.0F, bgra[1] / 255.0F, bgra[0] / 255.0F};
            const auto key = node.type == GradeNodeType::qualifier
                ? qualifier_key(rgb, node)
                : power_window_key(x, y, width, height, node);
            if (monochrome) {
                const auto value = static_cast<std::uint8_t>(std::lround(key * 255.0F));
                bgra[0] = value; bgra[1] = value; bgra[2] = value;
            } else if (key < 0.5F) {
                bgra[0] = static_cast<std::uint8_t>(bgra[0] * 0.18F);
                bgra[1] = static_cast<std::uint8_t>(bgra[1] * 0.18F);
                bgra[2] = static_cast<std::uint8_t>(bgra[2] * 0.18F);
            }
        }
    }
}

void apply_grade_graph_rgba32f(
    float* pixels, std::size_t pixel_count, const GradeGraph& graph,
    std::int64_t source_time, std::size_t width, std::size_t height,
    GradeSpatialMode spatial_mode) {
    if (pixels == nullptr && pixel_count != 0) throw std::invalid_argument("grade pixels are null");
    const auto unsupported = graph.render_unsupported_nodes();
    if (!unsupported.empty()) throw std::invalid_argument("grade graph contains an unsupported render node");
    if (width == 0 || height == 0) {
        width = pixel_count;
        height = pixel_count == 0 ? 0 : 1;
    }
    if (width * height != pixel_count && pixel_count != 0) {
        throw std::invalid_argument("grade pixel count does not match frame dimensions");
    }
    for (const auto& storedNode : graph.nodes()) {
        const auto spatial = !storedNode.lut_representable();
        if (spatial && spatial_mode == GradeSpatialMode::exclude) continue;
        if (!spatial && spatial_mode == GradeSpatialMode::only) continue;
        auto evaluatedNode = storedNode;
        for (const auto& [name, keyframes] : storedNode.parameter_keyframes) {
            if (!keyframes.empty()) {
                evaluatedNode.parameters[name] = parameter(
                    storedNode, name.c_str(), evaluatedNode.parameters.at(name), source_time);
            }
        }
        evaluatedNode.parameter_keyframes.clear();
        const auto& node = evaluatedNode;
        if (!node.enabled || node.mix <= 0.0) continue;
        const auto primary = node.type == GradeNodeType::primary
            ? std::optional<PrimaryState>{compile_primary(node)} : std::nullopt;
        const auto log = node.type == GradeNodeType::log_wheels
            ? std::optional<LogState>{compile_log(node)} : std::nullopt;
        const auto mixer = node.type == GradeNodeType::rgb_mixer
            ? std::optional<RgbMatrix>{compile_rgb_mixer(node)} : std::nullopt;
        const auto lut = node.type == GradeNodeType::lut
            ? grade_lut_processor(node.external_path) : OCIO::ConstCPUProcessorRcPtr{};
        for (std::size_t pixel = 0; pixel < pixel_count; ++pixel) {
            auto* rgba = pixels + pixel * 4;
            const std::array<float, 3> original{rgba[0], rgba[1], rgba[2]};
            const auto alpha = rgba[3];
            if (primary.has_value()) {
                apply_primary(rgba, *primary);
                apply_primary_creative(rgba, node);
            }
            else if (log.has_value()) apply_log(rgba, *log);
            else if (mixer.has_value()) apply_rgb_mixer(rgba, *mixer);
            else if (node.type == GradeNodeType::rgb_curves) apply_rgb_curves(rgba, node);
            else if (node.type == GradeNodeType::hue_curves) apply_hue_curves(rgba, node);
            else if (node.type == GradeNodeType::hdr_zones) apply_hdr_zones(rgba, node);
            else if (node.type == GradeNodeType::color_warper) apply_color_warper(rgba, node);
            else if (lut) lut->applyRGBA(rgba);
            else if (node.type == GradeNodeType::qualifier) {
                apply_masked_inside(rgba, qualifier_key(rgba, node), node);
            }
            else if (node.type == GradeNodeType::power_window) {
                const auto x = height == 0 ? 0 : pixel % width;
                const auto y = height == 0 ? 0 : pixel / width;
                apply_masked_inside(rgba, power_window_key(x, y, width, height, node), node);
            }
            for (std::size_t channel = 0; channel < 3; ++channel) {
                rgba[channel] = std::lerp(original[channel], rgba[channel], static_cast<float>(node.mix));
            }
            rgba[3] = alpha;
        }
    }
}

double evaluate_grade_parameter(
    const GradeNode& node, const std::string& name, double fallback,
    std::int64_t source_time) {
    return parameter(node, name.c_str(), fallback, source_time);
}

void validate_grade_lut_file(const std::string& path) {
    static_cast<void>(grade_lut_processor(path));
}

}  // namespace ffgui
