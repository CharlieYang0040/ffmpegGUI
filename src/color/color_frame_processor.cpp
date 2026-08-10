#include "color/color_frame_processor.hpp"

#include "color/grade_processor.hpp"
#include "color/ocio_engine.hpp"

#include <algorithm>
#include <iomanip>
#include <sstream>
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

std::string bake_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size) {
    if (cube_size < 2 || cube_size > 129) {
        throw std::invalid_argument("color cube size must be between 2 and 129");
    }
    if (!grade.render_unsupported_nodes().empty()) {
        throw std::invalid_argument("color cube contains nodes unsupported by the renderer");
    }

    FloatImageFrame lattice;
    lattice.width = cube_size * cube_size;
    lattice.height = cube_size;
    lattice.premultiplied = false;
    lattice.color_space = source_color.input_color_space;
    lattice.rgba.resize(static_cast<std::size_t>(cube_size) * cube_size * cube_size * 4);
    std::size_t pixel = 0;
    for (int blue = 0; blue < cube_size; ++blue) {
        for (int green = 0; green < cube_size; ++green) {
            for (int red = 0; red < cube_size; ++red) {
                const auto index = pixel++ * 4;
                lattice.rgba[index] = static_cast<float>(red) / (cube_size - 1);
                lattice.rgba[index + 1] = static_cast<float>(green) / (cube_size - 1);
                lattice.rgba[index + 2] = static_cast<float>(blue) / (cube_size - 1);
                lattice.rgba[index + 3] = 1.0F;
            }
        }
    }
    const auto processed = process_color_frame(
        lattice, source_color, settings, grade, output_space);

    std::ostringstream cube;
    cube << "TITLE \"ffmpegGUI clip color\"\n"
         << "LUT_3D_SIZE " << cube_size << "\n"
         << "DOMAIN_MIN 0.0 0.0 0.0\n"
         << "DOMAIN_MAX 1.0 1.0 1.0\n" << std::fixed << std::setprecision(9);
    for (std::size_t index = 0; index < processed.rgba.size(); index += 4) {
        cube << processed.rgba[index] << ' ' << processed.rgba[index + 1] << ' '
             << processed.rgba[index + 2] << '\n';
    }
    return cube.str();
}

}  // namespace ffgui
