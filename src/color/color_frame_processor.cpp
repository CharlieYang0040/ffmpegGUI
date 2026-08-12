#include "color/color_frame_processor.hpp"

#include "color/grade_processor.hpp"
#include "color/ocio_engine.hpp"

#include <algorithm>
#include <iomanip>
#include <iterator>
#include <sstream>
#include <stdexcept>

namespace ffgui {

FloatImageFrame process_color_frame(
    const FloatImageFrame& source,
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    std::int64_t source_time) {
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
        apply_grade_graph_rgba32f(result.rgba.data(), pixels, grade, source_time);
        ocio.transform_rgba32f(result.rgba.data(), source.width, source.height,
                               settings.working_space, output_space);
        result.color_space = output_space;
    } else {
        apply_grade_graph_rgba32f(result.rgba.data(), pixels, grade, source_time);
    }
    if (source.premultiplied) {
        for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
            auto* rgba = result.rgba.data() + pixel * 4;
            rgba[0] *= rgba[3]; rgba[1] *= rgba[3]; rgba[2] *= rgba[3];
        }
    }
    return result;
}

ColorCube build_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size,
    std::int64_t source_time) {
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
        lattice, source_color, settings, grade, output_space, source_time);

    ColorCube result;
    result.size = cube_size;
    result.rgb.reserve(processed.rgba.size() / 4 * 3);
    for (std::size_t index = 0; index < processed.rgba.size(); index += 4) {
        result.rgb.push_back(processed.rgba[index]);
        result.rgb.push_back(processed.rgba[index + 1]);
        result.rgb.push_back(processed.rgba[index + 2]);
    }
    return result;
}

OcioGpuShader build_managed_gpu_shader(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int grade_cube_size,
    std::int64_t source_time) {
    if (settings.mode == ColorPipelineMode::legacy ||
        source_color.input_color_space.empty() || settings.working_space.empty() ||
        output_space.empty()) {
        throw std::invalid_argument(
            "managed GPU color requires explicit input, working and output spaces");
    }
    OcioEngine engine(settings);
    auto input = engine.gpu_shader_hlsl(
        source_color.input_color_space, settings.working_space,
        "ffgui_input_transform", "ffgui_input_");
    auto output = engine.gpu_shader_hlsl(
        settings.working_space, output_space,
        "ffgui_output_transform", "ffgui_output_");
    OcioGpuShader result;
    result.cache_id = input.cache_id + ':' + output.cache_id;
    result.function_name = "ffgui_managed_transform";
    result.source = input.source + '\n' + output.source + '\n';
    result.textures = std::move(input.textures);
    result.textures.insert(result.textures.end(),
                           std::make_move_iterator(output.textures.begin()),
                           std::make_move_iterator(output.textures.end()));
    const auto graded = !grade.nodes().empty();
    if (graded) {
        const auto cube = build_color_cube({}, {}, grade, {}, grade_cube_size, source_time);
        OcioGpuTexture texture;
        texture.name = "ffgui_grade_lut";
        texture.sampler = "ffgui_grade_sampler";
        texture.width = static_cast<unsigned>(cube.size);
        texture.height = static_cast<unsigned>(cube.size);
        texture.depth = static_cast<unsigned>(cube.size);
        texture.channels = 3;
        texture.dimensions = 3;
        texture.values = cube.rgb;
        result.textures.push_back(std::move(texture));
        result.source +=
            "Texture3D ffgui_grade_lut;\n"
            "SamplerState ffgui_grade_sampler;\n";
        result.cache_id += ":grade";
    }
    result.source +=
        "float4 ffgui_managed_transform(float4 pixel) {\n"
        "  pixel = ffgui_input_transform(pixel);\n";
    if (graded) {
        result.source +=
            "  pixel.rgb = ffgui_grade_lut.Sample(ffgui_grade_sampler, "
            "saturate(pixel.rgb)).rgb;\n";
    }
    result.source +=
        "  pixel = ffgui_output_transform(pixel);\n"
        "  return pixel;\n"
        "}\n";
    return result;
}

std::string bake_color_cube(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int cube_size,
    std::int64_t source_time) {
    const auto values = build_color_cube(
        source_color, settings, grade, output_space, cube_size, source_time);
    std::ostringstream cube;
    cube << "TITLE \"ffmpegGUI clip color\"\n"
         << "LUT_3D_SIZE " << cube_size << "\n"
         << "DOMAIN_MIN 0.0 0.0 0.0\n"
         << "DOMAIN_MAX 1.0 1.0 1.0\n" << std::fixed << std::setprecision(9);
    for (std::size_t index = 0; index < values.rgb.size(); index += 3) {
        cube << values.rgb[index] << ' ' << values.rgb[index + 1] << ' '
             << values.rgb[index + 2] << '\n';
    }
    return cube.str();
}

}  // namespace ffgui
