#pragma once

#include "core/color_pipeline.hpp"
#include "core/media_source.hpp"
#include "core/time.hpp"
#include "media/oiio_frame_source.hpp"
#include "color/ocio_engine.hpp"

#include <filesystem>
#include <memory>
#include <string>
#include <cstdint>
#include <vector>

namespace ffgui {

struct ColorCube final {
    int size{};
    std::vector<float> rgb;
};

struct ColorLutRecipe final {
    SourceColorDescriptor source_color;
    ColorPipelineSettings settings;
    GradeGraph grade;
    std::string output_space;
    int cube_size{33};
    TimeNs source_in{};
    TimeNs timeline_in{};
    double playback_rate{1.0};
    bool animated{};
    bool working_space_grade_only{};
};

struct HaldClutImage final {
    int level{};
    int width{};
    std::vector<std::uint8_t> rgb;
};

[[nodiscard]] FloatImageFrame process_color_frame(
    const FloatImageFrame& source,
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    std::int64_t source_time = 0,
    ColorProcessStage stage = ColorProcessStage::post_display);

// Bake the exact CPU color path used by preview and float export into a .cube payload.
// The resulting LUT can be attached to ordinary video/image inputs before timeline
// transitions, keeping FFmpeg composition and the managed color path in agreement.
[[nodiscard]] std::string bake_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size = 33,
    std::int64_t source_time = 0);

[[nodiscard]] ColorCube build_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size = 33,
    std::int64_t source_time = 0);

// Builds the exact OCIO input/output Direct3D shader around the current creative
// grade. The creative stage remains a working-space cube until individual grade
// nodes gain native HLSL implementations.
[[nodiscard]] OcioGpuShader build_managed_gpu_shader(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int grade_cube_size = 33,
    std::int64_t source_time = 0);

[[nodiscard]] TimeNs source_time_for_clip_buffer(
    TimeNs source_in,
    TimeNs timeline_in,
    double playback_rate,
    TimeNs buffer_pts) noexcept;

[[nodiscard]] TimeNs source_time_for_recipe(
    const ColorLutRecipe& recipe, TimeNs buffer_pts) noexcept;

void sample_color_cube(const ColorCube& cube, const float input[3], float output[3]);

[[nodiscard]] ColorCube bake_recipe_cube(
    const ColorLutRecipe& recipe, TimeNs source_time);

[[nodiscard]] HaldClutImage build_hald_clut(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int level = 6,
    std::int64_t source_time = 0);

void write_hald_clut_ppm(const std::filesystem::path& path, const HaldClutImage& image);

class AnimatedCubeCache final {
public:
    [[nodiscard]] std::shared_ptr<const ColorCube> cube_for(
        std::shared_ptr<const ColorLutRecipe> recipe, TimeNs source_time);
    [[nodiscard]] std::shared_ptr<const ColorCube> cube_for_pts(
        std::shared_ptr<const ColorLutRecipe> recipe, TimeNs buffer_pts);

private:
    static constexpr std::size_t kCapacity = 8;
    static constexpr TimeNs kQuantum = 1'000'000;

    struct Entry final {
        std::shared_ptr<const ColorLutRecipe> recipe;
        TimeNs source_time{};
        std::shared_ptr<const ColorCube> cube;
    };

    std::vector<Entry> entries_;
};

}  // namespace ffgui
