#pragma once

#include "core/color_pipeline.hpp"

#include <cstddef>
#include <string>

namespace ffgui {

void apply_grade_graph_rgba32f(
    float* pixels, std::size_t pixel_count, const GradeGraph& graph);

// Parses and compiles a supported external look through OpenColorIO.  The same
// cached processor is used by the reference renderer, cube baker and previews.
void validate_grade_lut_file(const std::string& path);

}  // namespace ffgui
