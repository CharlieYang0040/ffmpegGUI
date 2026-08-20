#include "color/look_export.hpp"

#include "color/grade_processor.hpp"
#include "color/ocio_engine.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace ffgui {
namespace {

constexpr float kLog2Min = -8.0F;
constexpr float kLog2Max = 8.0F;

std::string json_escape(std::string_view value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const auto character : value) {
        if (character == '\\' || character == '"') {
            escaped.push_back('\\');
            escaped.push_back(character);
        } else if (character == '\n') {
            escaped += "\\n";
        } else {
            escaped.push_back(character);
        }
    }
    return escaped;
}

void encode_log2(float* rgb) {
    for (int channel = 0; channel < 3; ++channel) {
        const auto linear = std::max(rgb[channel], 1.0e-8F);
        rgb[channel] = (std::log2(linear) - kLog2Min) / (kLog2Max - kLog2Min);
    }
}

void decode_log2(float* rgb) {
    for (int channel = 0; channel < 3; ++channel) {
        rgb[channel] = std::exp2(std::lerp(kLog2Min, kLog2Max, rgb[channel]));
    }
}

void transform_shaper(
    OcioEngine* ocio, LutEncoding encoding, float* rgba, bool to_working) {
    if (encoding == LutEncoding::working_space) return;
    if (encoding == LutEncoding::log2) {
        if (to_working) decode_log2(rgba);
        else encode_log2(rgba);
        return;
    }
    if (ocio == nullptr) {
        throw std::invalid_argument("ACEScct shaper requires a managed OCIO configuration");
    }
    if (to_working) ocio->transform_rgba32f(rgba, 1, 1, "ACEScct", "ACEScg");
    else ocio->transform_rgba32f(rgba, 1, 1, "ACEScg", "ACEScct");
}

std::string cube_payload(
    const std::string& title, int cube_size, const std::vector<float>& rgb) {
    std::ostringstream cube;
    cube << "TITLE \"" << title << "\"\n"
         << "LUT_3D_SIZE " << cube_size << "\n"
         << "DOMAIN_MIN 0.0 0.0 0.0\n"
         << "DOMAIN_MAX 1.0 1.0 1.0\n"
         << std::fixed << std::setprecision(9);
    for (std::size_t index = 0; index < rgb.size(); index += 3) {
        cube << rgb[index] << ' ' << rgb[index + 1] << ' ' << rgb[index + 2] << '\n';
    }
    return cube.str();
}

std::string clf_payload(const std::string& name, int cube_size, const std::vector<float>& rgb) {
    std::ostringstream clf;
    clf << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        << "<ProcessList xmlns=\"urn:ASWF:ACESclip:v1.0\" id=\"ffmpegGUI.look\" name=\""
        << json_escape(name) << "\" compCLFversion=\"3.0\">\n"
        << "  <Description>Creative look only. Do not stack Unreal tone mapping.</Description>\n"
        << "  <LUT3D interpolation=\"tetrahedral\" dim=\"" << cube_size << "\">\n"
        << std::fixed << std::setprecision(9);
    for (std::size_t index = 0; index < rgb.size(); index += 3) {
        clf << "    " << rgb[index] << ' ' << rgb[index + 1] << ' ' << rgb[index + 2] << '\n';
    }
    clf << "  </LUT3D>\n</ProcessList>\n";
    return clf.str();
}

std::string ocio_config_text(const LutExportRequest& request) {
    const auto processSpace = request.encoding == LutEncoding::acescct ? "ACEScct" : "ACEScg";
    std::ostringstream config;
    config <<
        "ocio_profile_version: 2.2\n\n"
        "search_path: luts\n\n"
        "roles:\n"
        "  scene_linear: ACEScg\n"
        "  compositing_linear: ACEScg\n"
        "  color_timing: ACEScct\n"
        "  default: ACEScg\n"
        "  data: Raw\n"
        "  reference: ACES2065-1\n\n"
        "file_rules:\n"
        "  - !<Rule> {name: Default, colorspace: ACEScg}\n\n"
        "displays:\n"
        "  Unreal:\n"
        "    - !<View> {name: Linear, colorspace: ACEScg}\n"
        "    - !<View> {name: Look, colorspace: ACEScg, looks: ffmpegGUI_look}\n\n"
        "looks:\n"
        "  - !<Look>\n"
        "    name: ffmpegGUI_look\n"
        "    process_space: " << processSpace << "\n"
        "    transform: !<FileTransform> {src: ffmpegGUI_look.cube, interpolation: tetrahedral}\n\n"
        "colorspaces:\n"
        "  - !<ColorSpace>\n"
        "    name: Raw\n"
        "    family: Utility\n"
        "    isdata: true\n\n"
        "  - !<ColorSpace>\n"
        "    name: ACES2065-1\n"
        "    family: ACES\n"
        "    bitdepth: 32f\n"
        "    isdata: false\n"
        "    allocation: lg2\n\n"
        "  - !<ColorSpace>\n"
        "    name: ACEScg\n"
        "    family: ACES\n"
        "    bitdepth: 32f\n"
        "    isdata: false\n"
        "    to_scene_reference: !<BuiltinTransform> {style: ACEScg_to_ACES2065-1}\n"
        "    from_scene_reference: !<BuiltinTransform> {style: ACES2065-1_to_ACEScg}\n\n"
        "  - !<ColorSpace>\n"
        "    name: ACEScct\n"
        "    family: ACES\n"
        "    bitdepth: 32f\n"
        "    isdata: false\n"
        "    to_scene_reference: !<BuiltinTransform> {style: ACEScct_to_ACES2065-1}\n"
        "    from_scene_reference: !<BuiltinTransform> {style: ACES2065-1_to_ACEScct}\n";
    return config.str();
}

std::string unreal_guide(const LutExportRequest& request, const std::string& note) {
    std::ostringstream text;
    text <<
        "# Unreal Engine 5.5–5.8 OCIO look\n\n"
        "This package is a creative look only. It does not include a display tone map.\n"
        "In Unreal, enable OCIO on the viewport/show and select:\n\n"
        "- Config: `config.ocio` or the `.ocioz` archive\n"
        "- Working / source: ACEScg\n"
        "- Display: Unreal\n"
        "- View: Linear (no look) or Look (applies ffmpegGUI_look)\n\n"
        "Do not also enable Unreal's ACES tone mapper or a second Display/View that\n"
        "already includes SDR/HDR mapping. That is double tone mapping.\n\n"
        "Cube size: " << request.cube_size << "\n"
        "Shaper: " << encoding_name(request.encoding) << "\n"
        "Display transform included: " << (request.include_display_transform ? "yes" : "no") << "\n";
    if (!note.empty()) text << "\nWarning: " << note << "\n";
    text <<
        "\nVerification charts in `charts/expected.json` list mid-grey and high-chroma\n"
        "working-space samples before/after the look. Compare Unreal viewport samples\n"
        "against those values with the Linear view (identity) and Look view (graded).\n";
    return text.str();
}

std::string verification_charts(
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const LutExportRequest& request,
    std::int64_t source_time) {
    struct Patch final { const char* name; float rgb[3]; };
    const Patch patches[]{
        {"mid_grey", {0.18F, 0.18F, 0.18F}},
        {"black", {0.01F, 0.01F, 0.01F}},
        {"white", {1.0F, 1.0F, 1.0F}},
        {"red", {0.8F, 0.05F, 0.05F}},
        {"green", {0.05F, 0.8F, 0.05F}},
        {"blue", {0.05F, 0.05F, 0.8F}},
        {"high_chroma", {1.2F, 0.02F, 0.9F}},
    };
    ColorPipelineSettings working = settings;
    if (working.mode == ColorPipelineMode::legacy) {
        working.working_space = working.working_space.empty() ? "ACEScg" : working.working_space;
    }
    std::ostringstream json;
    json << "{\n  \"workingSpace\": \"" << json_escape(working.working_space)
         << "\",\n  \"cubeSize\": " << request.cube_size
         << ",\n  \"encoding\": \"" << encoding_name(request.encoding)
         << "\",\n  \"patches\": [\n" << std::fixed << std::setprecision(6);
    bool first = true;
    for (const auto& patch : patches) {
        float pixel[]{patch.rgb[0], patch.rgb[1], patch.rgb[2], 1.0F};
        apply_grade_graph_rgba32f(
            pixel, 1, grade, source_time, 1, 1, GradeSpatialMode::exclude);
        if (!first) json << ",\n";
        first = false;
        json << "    {\"name\": \"" << patch.name
             << "\", \"input\": [" << patch.rgb[0] << ", " << patch.rgb[1] << ", " << patch.rgb[2]
             << "], \"look\": [" << pixel[0] << ", " << pixel[1] << ", " << pixel[2] << "]}";
    }
    json << "\n  ]\n}\n";
    return json.str();
}

std::uint32_t crc32(std::string_view data) {
    std::uint32_t crc = 0xFFFFFFFF;
    for (unsigned char byte : data) {
        crc ^= byte;
        for (int bit = 0; bit < 8; ++bit) {
            const auto mix = crc & 1U;
            crc >>= 1;
            if (mix) crc ^= 0xEDB88320U;
        }
    }
    return ~crc;
}

void append_u16(std::vector<std::uint8_t>& out, std::uint16_t value) {
    out.push_back(static_cast<std::uint8_t>(value));
    out.push_back(static_cast<std::uint8_t>(value >> 8));
}

void append_u32(std::vector<std::uint8_t>& out, std::uint32_t value) {
    out.push_back(static_cast<std::uint8_t>(value));
    out.push_back(static_cast<std::uint8_t>(value >> 8));
    out.push_back(static_cast<std::uint8_t>(value >> 16));
    out.push_back(static_cast<std::uint8_t>(value >> 24));
}

std::vector<std::uint8_t> zip_store(const std::vector<LookExportFile>& files) {
    std::vector<std::uint8_t> zip;
    struct Entry final {
        std::string name;
        std::uint32_t crc{};
        std::uint32_t size{};
        std::uint32_t offset{};
    };
    std::vector<Entry> entries;
    for (const auto& file : files) {
        Entry entry;
        entry.name = file.relative_path;
        entry.crc = crc32(file.text);
        entry.size = static_cast<std::uint32_t>(file.text.size());
        entry.offset = static_cast<std::uint32_t>(zip.size());
        zip.insert(zip.end(), {'P', 'K', 0x03, 0x04});
        append_u16(zip, 20);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u32(zip, entry.crc);
        append_u32(zip, entry.size);
        append_u32(zip, entry.size);
        append_u16(zip, static_cast<std::uint16_t>(entry.name.size()));
        append_u16(zip, 0);
        zip.insert(zip.end(), entry.name.begin(), entry.name.end());
        zip.insert(zip.end(), file.text.begin(), file.text.end());
        entries.push_back(std::move(entry));
    }
    const auto central = static_cast<std::uint32_t>(zip.size());
    for (const auto& entry : entries) {
        zip.insert(zip.end(), {'P', 'K', 0x01, 0x02});
        append_u16(zip, 20);
        append_u16(zip, 20);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u32(zip, entry.crc);
        append_u32(zip, entry.size);
        append_u32(zip, entry.size);
        append_u16(zip, static_cast<std::uint16_t>(entry.name.size()));
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u16(zip, 0);
        append_u32(zip, 0);
        append_u32(zip, entry.offset);
        zip.insert(zip.end(), entry.name.begin(), entry.name.end());
    }
    const auto centralSize = static_cast<std::uint32_t>(zip.size() - central);
    zip.insert(zip.end(), {'P', 'K', 0x05, 0x06});
    append_u16(zip, 0);
    append_u16(zip, 0);
    append_u16(zip, static_cast<std::uint16_t>(entries.size()));
    append_u16(zip, static_cast<std::uint16_t>(entries.size()));
    append_u32(zip, centralSize);
    append_u32(zip, central);
    append_u16(zip, 0);
    return zip;
}

}  // namespace

std::string encoding_name(LutEncoding encoding) {
    switch (encoding) {
    case LutEncoding::acescct: return "ACEScct";
    case LutEncoding::log2: return "log2";
    case LutEncoding::working_space: return "working_space";
    }
    return "working_space";
}

std::string bake_look_cube(
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const LutExportRequest& request,
    std::int64_t source_time) {
    request.validate(grade);
    ColorPipelineSettings working = settings;
    if (working.mode == ColorPipelineMode::legacy) {
        working.working_space = working.working_space.empty() ? "ACEScg" : working.working_space;
    }
    if (request.encoding == LutEncoding::acescct &&
        (request.input_space != "ACEScct" || request.output_space != "ACEScct") &&
        request.input_space != "ACEScg") {
        // Input/output names describe the cube domain; ACEScct shaper is selected by encoding.
    }
    std::unique_ptr<OcioEngine> ocio;
    if (request.encoding == LutEncoding::acescct || request.include_display_transform) {
        ColorPipelineSettings ocioSettings = working;
        if (ocioSettings.mode == ColorPipelineMode::legacy) {
            ocioSettings.mode = ColorPipelineMode::aces_managed;
            ocioSettings.working_space = "ACEScg";
        }
        ocio = std::make_unique<OcioEngine>(ocioSettings);
        working = ocioSettings;
    }
    const auto maximum = static_cast<float>(request.cube_size - 1);
    std::vector<float> rgb;
    rgb.reserve(static_cast<std::size_t>(request.cube_size) * request.cube_size *
                request.cube_size * 3);
    for (int blue = 0; blue < request.cube_size; ++blue) {
        for (int green = 0; green < request.cube_size; ++green) {
            for (int red = 0; red < request.cube_size; ++red) {
                float pixel[]{red / maximum, green / maximum, blue / maximum, 1.0F};
                transform_shaper(ocio.get(), request.encoding, pixel, true);
                apply_grade_graph_rgba32f(
                    pixel, 1, grade, source_time, 1, 1, GradeSpatialMode::exclude);
                if (request.include_display_transform) {
                    if (uses_display_view(working)) {
                        ocio->transform_display_view_rgba32f(
                            pixel, 1, 1, working.working_space, working.display, working.view);
                    } else if (!request.output_space.empty() && ocio) {
                        ocio->transform_rgba32f(
                            pixel, 1, 1, working.working_space, request.output_space);
                    }
                } else {
                    transform_shaper(ocio.get(), request.encoding, pixel, false);
                }
                rgb.push_back(pixel[0]);
                rgb.push_back(pixel[1]);
                rgb.push_back(pixel[2]);
            }
        }
    }
    return cube_payload("ffmpegGUI look", request.cube_size, rgb);
}

LookExportPackage compile_look_export(
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const LutExportRequest& request,
    std::int64_t source_time) {
    request.validate(grade);
    LookExportPackage package;
    package.cube = bake_look_cube(settings, grade, request, source_time);
    std::vector<float> rgb;
    {
        std::istringstream stream(package.cube);
        std::string line;
        while (std::getline(stream, line)) {
            if (line.empty() || line[0] < '0' || line[0] > '9') continue;
            std::istringstream values(line);
            float red{};
            float green{};
            float blue{};
            if (values >> red >> green >> blue) {
                rgb.push_back(red);
                rgb.push_back(green);
                rgb.push_back(blue);
            }
        }
    }
    package.dual_tone_mapping_note =
        "Unreal View 'Linear' has no look. View 'Look' applies only the creative cube.";
    package.files.push_back({"luts/ffmpegGUI_look.cube", package.cube});
    package.files.push_back({"looks/ffmpegGUI_look.clf",
        clf_payload("ffmpegGUI look", request.cube_size, rgb)});
    if (request.unreal_ocio_bundle) {
        package.files.push_back({"config.ocio", ocio_config_text(request)});
        package.files.push_back({"UNREAL.md", unreal_guide(request, package.dual_tone_mapping_note)});
        package.files.push_back({"charts/expected.json",
            verification_charts(settings, grade, request, source_time)});
        package.files.push_back({"MANIFEST.json",
            std::string{"{\n  \"name\": \"ffmpegGUI look\",\n  \"ocio\": \"2.2\",\n  \"cubeSize\": "} +
            std::to_string(request.cube_size) + ",\n  \"encoding\": \"" +
            encoding_name(request.encoding) +
            "\",\n  \"includeDisplayTransform\": false,\n  \"looks\": [\"ffmpegGUI_look\"]\n}\n"});
        package.ocioz = zip_store(package.files);
    }
    return package;
}

void write_look_export(
    const LookExportPackage& package, const std::filesystem::path& directory) {
    std::filesystem::create_directories(directory);
    for (const auto& file : package.files) {
        const auto path = directory / std::filesystem::path(file.relative_path);
        std::filesystem::create_directories(path.parent_path());
        std::ofstream stream(path, std::ios::binary);
        if (!stream) throw std::runtime_error("look export file could not be written");
        stream << file.text;
    }
    if (!package.ocioz.empty()) {
        std::ofstream stream(directory / "ffmpegGUI_look.ocioz", std::ios::binary);
        if (!stream) throw std::runtime_error("ocioz archive could not be written");
        stream.write(reinterpret_cast<const char*>(package.ocioz.data()),
                     static_cast<std::streamsize>(package.ocioz.size()));
    }
}

}  // namespace ffgui
