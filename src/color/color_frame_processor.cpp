#include "color/color_frame_processor.hpp"

#include "color/grade_processor.hpp"
#include "color/ocio_engine.hpp"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <memory>
#include <sstream>
#include <stdexcept>

namespace ffgui {

FloatImageFrame process_color_frame(
    const FloatImageFrame& source,
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    std::int64_t source_time,
    ColorProcessStage stage) {
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
        if (inputSpace.empty()) {
            throw std::invalid_argument("managed color frame requires an explicit input space");
        }
        OcioEngine ocio(settings);
        ocio.transform_rgba32f(result.rgba.data(), source.width, source.height,
                               inputSpace, settings.working_space);
        result.color_space = settings.working_space;
        if (stage != ColorProcessStage::pre_grade) {
            apply_grade_graph_rgba32f(result.rgba.data(), pixels, grade, source_time);
        }
        if (stage == ColorProcessStage::post_display && !settings.display_transform_bypassed) {
            if (uses_display_view(settings)) {
                ocio.transform_display_view_rgba32f(
                    result.rgba.data(), source.width, source.height,
                    settings.working_space, settings.display, settings.view);
                const auto named = ocio.display_view_color_space(settings.display, settings.view);
                result.color_space = named.empty() ? output_space : named;
            } else {
                if (output_space.empty()) {
                    throw std::invalid_argument(
                        "managed color frame requires an explicit output space");
                }
                ocio.transform_rgba32f(result.rgba.data(), source.width, source.height,
                                       settings.working_space, output_space);
                result.color_space = output_space;
            }
        }
    } else if (stage != ColorProcessStage::pre_grade) {
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
    OcioGpuShader output;
    const auto skipDisplay = settings.display_transform_bypassed;
    if (!skipDisplay && uses_display_view(settings)) {
        output = engine.gpu_shader_display_view_hlsl(
            settings.working_space, settings.display, settings.view,
            "ffgui_output_transform", "ffgui_output_");
    } else if (!skipDisplay) {
        output = engine.gpu_shader_hlsl(
            settings.working_space, output_space,
            "ffgui_output_transform", "ffgui_output_");
    }
    OcioGpuShader result;
    result.cache_id = input.cache_id + ':' + (skipDisplay ? std::string{"bypass"} : output.cache_id);
    result.function_name = "ffgui_managed_transform";
    result.source = input.source + '\n';
    if (!skipDisplay) result.source += output.source + '\n';
    result.textures = std::move(input.textures);
    if (!skipDisplay) {
        result.textures.insert(result.textures.end(),
                               std::make_move_iterator(output.textures.begin()),
                               std::make_move_iterator(output.textures.end()));
    }
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
    if (!skipDisplay) {
        result.source +=
            "  pixel = ffgui_output_transform(pixel);\n";
    }
    result.source +=
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

TimeNs source_time_for_clip_buffer(
    TimeNs source_in,
    TimeNs timeline_in,
    double playback_rate,
    TimeNs buffer_pts) noexcept {
    if (!std::isfinite(playback_rate) || playback_rate <= 0.0) playback_rate = 1.0;
    const auto local = buffer_pts >= timeline_in ? buffer_pts - timeline_in : buffer_pts;
    const auto offset = static_cast<TimeNs>(std::llround(
        static_cast<long double>(std::max<TimeNs>(0, local)) *
        static_cast<long double>(playback_rate)));
    const auto result = source_in + offset;
    return result < 0 ? TimeNs{0} : result;
}

TimeNs source_time_for_recipe(const ColorLutRecipe& recipe, TimeNs buffer_pts) noexcept {
    return source_time_for_clip_buffer(
        recipe.source_in, recipe.timeline_in, recipe.playback_rate, buffer_pts);
}

void sample_color_cube(const ColorCube& cube, const float input[3], float output[3]) {
    if (cube.size < 2 || cube.rgb.size() !=
            static_cast<std::size_t>(cube.size) * cube.size * cube.size * 3 ||
        input == nullptr || output == nullptr) {
        if (output != nullptr) {
            output[0] = 0.0F;
            output[1] = 0.0F;
            output[2] = 0.0F;
        }
        return;
    }
    const auto maximum = cube.size - 1;
    int lower[3]{};
    int upper[3]{};
    float fraction[3]{};
    for (int channel = 0; channel < 3; ++channel) {
        const auto coordinate = std::clamp(
            std::isfinite(input[channel]) ? input[channel] : 0.0F, 0.0F, 1.0F) *
            static_cast<float>(maximum);
        lower[channel] = static_cast<int>(std::floor(coordinate));
        upper[channel] = std::min(maximum, lower[channel] + 1);
        fraction[channel] = coordinate - static_cast<float>(lower[channel]);
    }
    const auto value = [&](int red, int green, int blue, int channel) {
        const auto index = (static_cast<std::size_t>(blue) * cube.size * cube.size +
                            static_cast<std::size_t>(green) * cube.size +
                            static_cast<std::size_t>(red)) * 3 +
            static_cast<std::size_t>(channel);
        return cube.rgb[index];
    };
    for (int channel = 0; channel < 3; ++channel) {
        const auto c00 = std::lerp(value(lower[0], lower[1], lower[2], channel),
                                   value(upper[0], lower[1], lower[2], channel), fraction[0]);
        const auto c10 = std::lerp(value(lower[0], upper[1], lower[2], channel),
                                   value(upper[0], upper[1], lower[2], channel), fraction[0]);
        const auto c01 = std::lerp(value(lower[0], lower[1], upper[2], channel),
                                   value(upper[0], lower[1], upper[2], channel), fraction[0]);
        const auto c11 = std::lerp(value(lower[0], upper[1], upper[2], channel),
                                   value(upper[0], upper[1], upper[2], channel), fraction[0]);
        output[channel] = std::lerp(
            std::lerp(c00, c10, fraction[1]),
            std::lerp(c01, c11, fraction[1]), fraction[2]);
    }
}

ColorCube bake_recipe_cube(const ColorLutRecipe& recipe, TimeNs source_time) {
    if (recipe.working_space_grade_only) {
        return build_color_cube({}, {}, recipe.grade, {}, recipe.cube_size, source_time);
    }
    return build_color_cube(
        recipe.source_color, recipe.settings, recipe.grade, recipe.output_space,
        recipe.cube_size, source_time);
}

HaldClutImage build_hald_clut(
    const SourceColorDescriptor& source_color,
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const std::string& output_space,
    int level,
    std::int64_t source_time) {
    if (level < 2 || level > 8) {
        throw std::invalid_argument("Hald CLUT level must be between 2 and 8");
    }
    const auto cubeSize = level * level;
    const auto width = cubeSize * level;
    FloatImageFrame lattice;
    lattice.width = width;
    lattice.height = width;
    lattice.premultiplied = false;
    lattice.color_space = source_color.input_color_space;
    lattice.rgba.resize(static_cast<std::size_t>(width) * width * 4);
    const auto scale = cubeSize > 1 ? 1.0F / static_cast<float>(cubeSize - 1) : 1.0F;
    std::size_t pixel = 0;
    for (int y = 0; y < width; ++y) {
        for (int x = 0; x < width; ++x) {
            const auto index = static_cast<std::size_t>(y) * width + static_cast<std::size_t>(x);
            const auto red = static_cast<int>(index % static_cast<std::size_t>(cubeSize));
            const auto green = static_cast<int>(
                (index / static_cast<std::size_t>(cubeSize)) % static_cast<std::size_t>(cubeSize));
            const auto blue = static_cast<int>(
                index / (static_cast<std::size_t>(cubeSize) * cubeSize));
            const auto rgba = pixel++ * 4;
            lattice.rgba[rgba] = static_cast<float>(red) * scale;
            lattice.rgba[rgba + 1] = static_cast<float>(green) * scale;
            lattice.rgba[rgba + 2] = static_cast<float>(blue) * scale;
            lattice.rgba[rgba + 3] = 1.0F;
        }
    }
    const auto processed = process_color_frame(
        lattice, source_color, settings, grade, output_space, source_time);
    HaldClutImage result;
    result.level = level;
    result.width = width;
    result.rgb.resize(static_cast<std::size_t>(width) * width * 3);
    for (std::size_t index = 0, output = 0; index < processed.rgba.size(); index += 4) {
        for (int channel = 0; channel < 3; ++channel) {
            const auto value = std::clamp(
                std::isfinite(processed.rgba[index + static_cast<std::size_t>(channel)])
                    ? processed.rgba[index + static_cast<std::size_t>(channel)] : 0.0F,
                0.0F, 1.0F);
            result.rgb[output++] = static_cast<std::uint8_t>(std::lround(value * 255.0F));
        }
    }
    return result;
}

void write_hald_clut_ppm(const std::filesystem::path& path, const HaldClutImage& image) {
    if (image.width < 4 || image.rgb.size() !=
            static_cast<std::size_t>(image.width) * image.width * 3) {
        throw std::invalid_argument("Hald CLUT image is invalid");
    }
    std::ofstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("Hald CLUT PPM could not be created");
    stream << "P6\n" << image.width << ' ' << image.width << "\n255\n";
    stream.write(reinterpret_cast<const char*>(image.rgb.data()),
                 static_cast<std::streamsize>(image.rgb.size()));
    if (!stream) throw std::runtime_error("Hald CLUT PPM could not be written");
}

std::shared_ptr<const ColorCube> AnimatedCubeCache::cube_for(
    std::shared_ptr<const ColorLutRecipe> recipe, TimeNs source_time) {
    if (recipe == nullptr) return {};
    const auto quantized = source_time >= 0
        ? source_time - source_time % kQuantum : TimeNs{0};
    for (auto iterator = entries_.begin(); iterator != entries_.end(); ++iterator) {
        if (iterator->recipe == recipe && iterator->source_time == quantized) {
            auto entry = std::move(*iterator);
            entries_.erase(iterator);
            entries_.insert(entries_.begin(), entry);
            return entry.cube;
        }
    }
    auto cube = std::make_shared<const ColorCube>(bake_recipe_cube(*recipe, quantized));
    entries_.insert(entries_.begin(), Entry{recipe, quantized, cube});
    if (entries_.size() > kCapacity) entries_.pop_back();
    return cube;
}

std::shared_ptr<const ColorCube> AnimatedCubeCache::cube_for_pts(
    std::shared_ptr<const ColorLutRecipe> recipe, TimeNs buffer_pts) {
    if (recipe == nullptr) return {};
    const auto sourceTime = source_time_for_recipe(*recipe, buffer_pts);
    return cube_for(std::move(recipe), sourceTime);
}

}  // namespace ffgui
