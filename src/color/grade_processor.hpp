#pragma once

#include "core/color_pipeline.hpp"

#include <cstddef>
#include <cstdint>
#include <string>

namespace ffgui {

enum class GradeSpatialMode { include, exclude, only };

void apply_grade_graph_rgba32f(
    float* pixels, std::size_t pixel_count, const GradeGraph& graph,
    std::int64_t source_time = 0,
    std::size_t width = 0,
    std::size_t height = 0,
    GradeSpatialMode spatial_mode = GradeSpatialMode::include);

[[nodiscard]] double evaluate_grade_parameter(
    const GradeNode& node, const std::string& name, double fallback,
    std::int64_t source_time);

// Parses and compiles a supported external look through OpenColorIO.  The same
// cached processor is used by the reference renderer, cube baker and previews.
void validate_grade_lut_file(const std::string& path);

}  // namespace ffgui
