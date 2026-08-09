#pragma once

#include "core/color_pipeline.hpp"

#include <cstddef>

namespace ffgui {

void apply_grade_graph_rgba32f(
    float* pixels, std::size_t pixel_count, const GradeGraph& graph);

}  // namespace ffgui
