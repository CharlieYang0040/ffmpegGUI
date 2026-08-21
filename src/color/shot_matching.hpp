#pragma once

#include "core/color_pipeline.hpp"
#include "media/oiio_frame_source.hpp"

#include <cstddef>
#include <filesystem>
#include <string>

namespace ffgui {

enum class ShotCompareMode { off, still_wipe, still_split };

struct ShotStill final {
    std::string clip_id;
    std::string path;
    std::int64_t source_time{};
};

struct ShotMatchOffset final {
    double exposure{};
    double saturation{1.0};
};

[[nodiscard]] ShotMatchOffset match_mean_rgb(
    const float* reference_rgba, const float* source_rgba, std::size_t pixel_count);
void apply_shot_match(GradeGraph& graph, const ShotMatchOffset& offset);
void write_rgba32f_png(
    const std::filesystem::path& path, int width, int height, const float* rgba);
[[nodiscard]] FloatImageFrame read_rgba32f_image(const std::filesystem::path& path);
void compose_shot_compare_rgba32f(
    float* current, const float* still, std::size_t width, std::size_t height,
    ShotCompareMode mode);
void split_rgba32f(
    float* display, const float* other, std::size_t width, std::size_t height, float split = 0.5F);

}  // namespace ffgui
