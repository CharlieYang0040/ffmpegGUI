#pragma once

#include "core/color_pipeline.hpp"
#include "core/media_source.hpp"
#include "media/oiio_frame_source.hpp"

#include <string>

namespace ffgui {

[[nodiscard]] FloatImageFrame process_color_frame(
    const FloatImageFrame& source,
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space);

}  // namespace ffgui
