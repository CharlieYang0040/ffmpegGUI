#pragma once

#include "core/color_pipeline.hpp"
#include "core/media_source.hpp"
#include "media/oiio_frame_source.hpp"
#include "color/ocio_engine.hpp"

#include <string>
#include <vector>

namespace ffgui {

struct ColorCube final {
    int size{};
    std::vector<float> rgb;
};

[[nodiscard]] FloatImageFrame process_color_frame(
    const FloatImageFrame& source,
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space);

// Bake the exact CPU color path used by preview and float export into a .cube payload.
// The resulting LUT can be attached to ordinary video/image inputs before timeline
// transitions, keeping FFmpeg composition and the managed color path in agreement.
[[nodiscard]] std::string bake_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size = 33);

[[nodiscard]] ColorCube build_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size = 33);

// Builds the exact OCIO input/output Direct3D shader around the current creative
// grade. The creative stage remains a working-space cube until individual grade
// nodes gain native HLSL implementations.
[[nodiscard]] OcioGpuShader build_managed_gpu_shader(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int grade_cube_size = 33);

}  // namespace ffgui
