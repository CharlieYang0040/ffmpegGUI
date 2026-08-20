#include "color/shot_matching.hpp"

#include "color/review_tools.hpp"

#include <OpenImageIO/imageio.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <string>

namespace ffgui {
namespace {

constexpr std::array<float, 3> kLuma{0.2722287F, 0.6740818F, 0.0536895F};

float luma_of(const float* rgb) {
    return rgb[0] * kLuma[0] + rgb[1] * kLuma[1] + rgb[2] * kLuma[2];
}

float chroma_of(const float* rgb) {
    const auto luma = luma_of(rgb);
    const auto dr = rgb[0] - luma;
    const auto dg = rgb[1] - luma;
    const auto db = rgb[2] - luma;
    return std::sqrt(dr * dr + dg * dg + db * db);
}

void mean_stats(const float* rgba, std::size_t pixel_count, float& luma, float& chroma) {
    luma = 0.0F;
    chroma = 0.0F;
    if (pixel_count == 0) return;
    for (std::size_t pixel = 0; pixel < pixel_count; ++pixel) {
        const auto* rgb = rgba + pixel * 4;
        luma += luma_of(rgb);
        chroma += chroma_of(rgb);
    }
    luma /= static_cast<float>(pixel_count);
    chroma /= static_cast<float>(pixel_count);
}

}  // namespace

ShotMatchOffset match_mean_rgb(
    const float* reference_rgba, const float* source_rgba, std::size_t pixel_count) {
    if (reference_rgba == nullptr || source_rgba == nullptr || pixel_count == 0) {
        throw std::invalid_argument("shot match requires two float frames");
    }
    float referenceLuma{};
    float referenceChroma{};
    float sourceLuma{};
    float sourceChroma{};
    mean_stats(reference_rgba, pixel_count, referenceLuma, referenceChroma);
    mean_stats(source_rgba, pixel_count, sourceLuma, sourceChroma);
    ShotMatchOffset offset;
    const auto safeSource = std::max(sourceLuma, 1.0e-6F);
    offset.exposure = std::log2(std::max(referenceLuma, 1.0e-6F) / safeSource);
    offset.saturation = referenceChroma <= 1.0e-6F || sourceChroma <= 1.0e-6F
        ? 1.0
        : static_cast<double>(referenceChroma / sourceChroma);
    return offset;
}

void apply_shot_match(GradeGraph& graph, const ShotMatchOffset& offset) {
    GradeNode* primary = nullptr;
    for (auto& node : graph.nodes()) {
        if (node.type == GradeNodeType::primary && node.enabled) {
            primary = graph.node(node.id);
            break;
        }
    }
    if (primary == nullptr) {
        std::string id = "shot-match-primary";
        int suffix = 1;
        while (graph.node(id) != nullptr) {
            id = "shot-match-primary-" + std::to_string(++suffix);
        }
        auto node = make_default_grade_node(GradeNodeType::primary, id);
        node.name = "Shot Match";
        graph.add(std::move(node));
        primary = graph.node(id);
    }
    if (primary == nullptr) throw std::runtime_error("shot match primary could not be created");
    primary->parameters["exposure"] = primary->parameters["exposure"] + offset.exposure;
    const auto saturation = primary->parameters.contains("saturation")
        ? primary->parameters["saturation"] : 1.0;
    primary->parameters["saturation"] = saturation * offset.saturation;
}

void write_rgba32f_png(
    const std::filesystem::path& path, int width, int height, const float* rgba) {
    if (width <= 0 || height <= 0 || rgba == nullptr) {
        throw std::invalid_argument("shot still frame is invalid");
    }
    const auto parent = path.parent_path();
    if (!parent.empty()) std::filesystem::create_directories(parent);
    auto output = OIIO::ImageOutput::create(path.string());
    if (!output) throw std::runtime_error("PNG writer is unavailable");
    OIIO::ImageSpec spec(width, height, 4, OIIO::TypeDesc::FLOAT);
    if (!output->open(path.string(), spec) ||
        !output->write_image(OIIO::TypeDesc::FLOAT, rgba) || !output->close()) {
        throw std::runtime_error("shot still PNG could not be written");
    }
}

FloatImageFrame read_rgba32f_image(const std::filesystem::path& path) {
    return read_float_image_frame(ImageFrameRequest{path});
}

void split_rgba32f(
    float* display, const float* other, std::size_t width, std::size_t height, float split) {
    if (display == nullptr || other == nullptr || width == 0 || height == 0) return;
    const auto cut = static_cast<std::size_t>(std::lround(
        std::clamp(split, 0.0F, 1.0F) * static_cast<float>(height)));
    for (std::size_t y = 0; y < cut; ++y) {
        for (std::size_t x = 0; x < width; ++x) {
            const auto index = (y * width + x) * 4;
            display[index] = other[index];
            display[index + 1] = other[index + 1];
            display[index + 2] = other[index + 2];
            display[index + 3] = other[index + 3];
        }
    }
}

void compose_shot_compare_rgba32f(
    float* current, const float* still, std::size_t width, std::size_t height,
    ShotCompareMode mode) {
    if (mode == ShotCompareMode::still_wipe) {
        wipe_rgba32f(current, still, width, height);
    } else if (mode == ShotCompareMode::still_split) {
        split_rgba32f(current, still, width, height);
    }
}

}  // namespace ffgui
