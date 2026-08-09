#include "color/color_frame_processor.hpp"

#include "color/grade_processor.hpp"
#include "color/ocio_engine.hpp"

#include <algorithm>
#include <stdexcept>

namespace ffgui {

FloatImageFrame process_color_frame(
    const FloatImageFrame& source,
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space) {
    if (source.rgba.size() != static_cast<std::size_t>(source.width) * source.height * 4) {
        throw std::invalid_argument("source float frame storage is invalid");
    }
    FloatImageFrame result = source;
    const auto pixels = static_cast<std::size_t>(source.width) * source.height;
    if (source.premultiplied) {
        for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
            auto* rgba = result.rgba.data() + pixel * 4;
            if (rgba[3] > 0.0F) {
                rgba[0] /= rgba[3]; rgba[1] /= rgba[3]; rgba[2] /= rgba[3];
            }
        }
    }
    if (settings.mode != ColorPipelineMode::legacy) {
        const auto inputSpace = source_color.input_color_space.empty()
            ? source.color_space : source_color.input_color_space;
        if (inputSpace.empty() || output_space.empty()) {
            throw std::invalid_argument("managed color frame requires explicit input and output spaces");
        }
        OcioEngine ocio(settings);
        ocio.transform_rgba32f(result.rgba.data(), source.width, source.height,
                               inputSpace, settings.working_space);
        apply_grade_graph_rgba32f(result.rgba.data(), pixels, grade);
        ocio.transform_rgba32f(result.rgba.data(), source.width, source.height,
                               settings.working_space, output_space);
        result.color_space = output_space;
    } else {
        apply_grade_graph_rgba32f(result.rgba.data(), pixels, grade);
    }
    if (source.premultiplied) {
        for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
            auto* rgba = result.rgba.data() + pixel * 4;
            rgba[0] *= rgba[3]; rgba[1] *= rgba[3]; rgba[2] *= rgba[3];
        }
    }
    return result;
}

}  // namespace ffgui
