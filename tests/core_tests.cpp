#include "core/media_asset.hpp"
#include "core/color_pipeline.hpp"
#include "core/render_preflight.hpp"
#include "color/ocio_engine.hpp"
#include "color/grade_processor.hpp"
#include "color/color_frame_processor.hpp"
#include "color/scope_analyzer.hpp"
#include "media/oiio_probe.hpp"
#include "media/oiio_frame_source.hpp"
#include "render/timeline_frame_server.hpp"
#include "core/ffprobe_parser.hpp"
#include "core/timeline_model.hpp"
#include "core/subtitle_srt.hpp"
#include "export/ffmpeg_export_plan.hpp"

#include <exception>
#include <array>
#include <filesystem>
#include <functional>
#include <fstream>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>
#include <OpenImageIO/imageio.h>

namespace {

using ffgui::Clip;
using ffgui::MediaAsset;
using ffgui::TimeNs;
using ffgui::TimelineModel;
using namespace std::string_literals;

constexpr TimeNs seconds(TimeNs value) {
    return value * ffgui::kNanosecondsPerSecond;
}

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

template <typename Exception, typename Callable>
void require_throws(Callable&& callable, const std::string& message) {
    try {
        callable();
    } catch (const Exception&) {
        return;
    }
    throw std::runtime_error(message);
}

TimelineModel make_timeline() {
    TimelineModel timeline;
    timeline.add_asset(MediaAsset{
        "asset-a",
        std::filesystem::path{"A.mp4"},
        seconds(10),
        {0, seconds(1), seconds(2), seconds(4), seconds(7)}});
    timeline.add_asset(MediaAsset{
        "asset-b",
        std::filesystem::path{"B.mkv"},
        seconds(20)});
    return timeline;
}

void test_vfr_frame_lookup() {
    const MediaAsset asset{
        "vfr",
        std::filesystem::path{"vfr.mkv"},
        seconds(9),
        {0, seconds(1), seconds(2), seconds(4), seconds(7)}};
    require(asset.frame_at_or_before(0) == 0, "first VFR frame must start at zero");
    require(asset.frame_at_or_before(seconds(3)) == 2, "VFR lookup must choose previous PTS");
    require(asset.frame_at_or_before(seconds(8)) == 4, "VFR lookup must reach last frame");
    require(!asset.frame_at_or_before(seconds(9)).has_value(), "asset end is half-open");
}

void test_image_sequence_detection_preserves_gaps_and_negative_frames() {
    const auto root = std::filesystem::temp_directory_path() / "ffgui-sequence-detection-test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    for (const auto* name : {"shot.-0002.exr", "shot.-0001.exr", "shot.0001.exr", "shot.0003.exr"}) {
        std::ofstream(root / name).put('\0');
    }
    const auto sequence = ffgui::detect_image_sequence(root / "shot.0001.exr", {24, 1});
    require(sequence.has_value(), "numbered EXR siblings must be detected as one sequence");
    require(sequence->first_frame == -2 && sequence->last_frame == 3,
            "sequence range must preserve signed source frame numbers");
    require(sequence->missing_frames == std::vector<int>({0, 2}),
            "sequence gaps must remain explicit timeline frames");
    require(sequence->nearest_present_frame(0) == -1,
            "equidistant missing frames must prefer the previous frame");
    require(sequence->frame_path(-2).filename() == std::filesystem::path{"shot.-0002.exr"},
            "signed padded frame paths must round trip");
    std::filesystem::remove_all(root);
}

void test_media_asset_separates_original_and_playback_paths() {
    ffgui::ImageSequenceDescriptor sequence;
    sequence.directory = ".";
    sequence.prefix = "render.";
    sequence.suffix = ".exr";
    sequence.padding = 4;
    sequence.first_frame = 1001;
    sequence.last_frame = 1002;
    sequence.present_frames = {1001, 1002};
    const MediaAsset asset{
        "sequence", "render.1001.exr", seconds(2), {0, seconds(1)}, {}, {},
        ffgui::MediaKind::image_sequence, sequence, {}, "cache/sequence-proxy.mkv"};
    require(asset.path() == std::filesystem::path{"render.1001.exr"},
            "sequence asset must preserve its original representative frame");
    require(asset.playback_path() == std::filesystem::path{"cache/sequence-proxy.mkv"},
            "sequence asset must expose a separate playback proxy");
}

void test_color_pipeline_defaults_to_legacy_and_lut_preflight_rejects_spatial_nodes() {
    ffgui::ColorPipelineSettings settings;
    require(settings.mode == ffgui::ColorPipelineMode::legacy,
            "new projects must preserve the legacy color path by default");
    settings.validate();
    ffgui::GradeGraph graph;
    graph.add(ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "primary-1"));
    require(graph.lut_representable(), "primary correction must be LUT representable");
    graph.add(ffgui::make_default_grade_node(ffgui::GradeNodeType::power_window, "window-1"));
    require(!graph.lut_representable() && graph.lut_incompatible_nodes() ==
                std::vector<std::string>{"Power Window"},
            "spatial grade nodes must be named in LUT preflight failures");
    require_throws<std::invalid_argument>([&] {
        ffgui::LutExportRequest{"ACEScct", "ACEScg", ffgui::LutEncoding::acescct, 33}.validate(graph);
    }, "LUT export must reject graphs that cannot be represented by a global RGB transform");
}

void test_ocio_aces_config_transforms_float_pixels_and_bakes_resolve_cube() {
    ffgui::ColorPipelineSettings settings;
    settings.mode = ffgui::ColorPipelineMode::aces_managed;
    ffgui::OcioEngine engine(settings);
    require(engine.managed() && !engine.color_spaces().empty(),
            "ACES managed mode must load the bundled OCIO configuration");
    const auto spaces = engine.color_spaces();
    require(std::ranges::find(spaces, "ACEScg") != spaces.end(),
            "ACES Studio config must expose ACEScg");
    require(std::ranges::find(spaces, "sRGB - Display") != spaces.end(),
            "ACES Studio config must expose the default SDR preview output space");
    require(std::ranges::find(spaces, "Camera Rec.709") != spaces.end(),
            "ACES Studio config must expose the tagged Rec.709 video input space");
    require(std::ranges::find(spaces, "Rec.2100-PQ - Display") != spaces.end(),
            "ACES Studio config must expose the tagged PQ video input space");
    float pixel[]{0.18F, 0.18F, 0.18F, 0.5F};
    engine.transform_rgba32f(pixel, 1, 1, "ACEScg", "ACES2065-1");
    require(pixel[0] > 0.0F && pixel[1] > 0.0F && pixel[2] > 0.0F &&
                std::abs(pixel[3] - 0.5F) < 0.00001F,
            "OCIO float transform must preserve a separate alpha channel");
    const auto cube = engine.bake_cube("ACEScct", "ACEScg", 33);
    require(cube.contains("LUT_3D_SIZE 33"),
            "Resolve Cube baker must honor the requested real-time LUT size");
    ffgui::SourceColorDescriptor rec709;
    rec709.input_color_space = "Camera Rec.709";
    const auto clipCube = ffgui::bake_color_cube(
        rec709, settings, {}, "sRGB - Display", 2);
    require(clipCube.contains("LUT_3D_SIZE 2") &&
                std::ranges::count(clipCube, '\n') == 12,
            "managed video export LUT must evaluate input, ACEScg and display transforms");
    const auto shader = engine.gpu_shader_hlsl("Apple Log", "ACEScg");
    require(!shader.cache_id.empty() && !shader.source.empty() &&
                shader.function_name == "ffgui_ocio_transform" &&
                shader.textures.size() == 1 && shader.textures.front().binding > 0 &&
                shader.textures.front().dimensions == 2 &&
                shader.textures.front().values.size() ==
                    static_cast<std::size_t>(shader.textures.front().width) *
                        shader.textures.front().height * shader.textures.front().channels,
            "ACES processor must produce a cacheable Direct3D 11 HLSL shader description");
    ffgui::GradeGraph gpuGrade;
    auto gpuPrimary = ffgui::make_default_grade_node(
        ffgui::GradeNodeType::primary, "gpu-primary");
    gpuPrimary.parameters["exposure"] = 0.25;
    gpuGrade.add(std::move(gpuPrimary));
    ffgui::SourceColorDescriptor appleLog;
    appleLog.input_color_space = "Apple Log";
    const auto managedShader = ffgui::build_managed_gpu_shader(
        appleLog, settings, gpuGrade, "sRGB - Display");
    require(managedShader.source.contains("ffgui_input_transform") &&
                managedShader.source.contains("ffgui_grade_lut.Sample") &&
                managedShader.source.contains("ffgui_output_transform") &&
                managedShader.textures.size() >= 2 &&
                managedShader.textures.back().dimensions == 3,
            "managed GPU shader must keep exact OCIO stages around the creative grade cube");
}

void test_float_grade_pipeline_preserves_alpha_and_node_mix() {
    ffgui::GradeGraph grade;
    auto primary = ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "primary-1");
    primary.parameters["exposure"] = 1.0;
    primary.mix = 0.5;
    grade.add(primary);
    float pixel[]{0.25F, 0.25F, 0.25F, 0.4F};
    ffgui::apply_grade_graph_rgba32f(pixel, 1, grade);
    require(std::abs(pixel[0] - 0.375F) < 0.00001F &&
                std::abs(pixel[1] - 0.375F) < 0.00001F &&
                std::abs(pixel[2] - 0.375F) < 0.00001F &&
                std::abs(pixel[3] - 0.4F) < 0.00001F,
            "primary exposure and node mix must operate in float RGB without changing alpha");

    ffgui::FloatImageFrame premultiplied;
    premultiplied.width = 1;
    premultiplied.height = 1;
    premultiplied.premultiplied = true;
    premultiplied.rgba = {0.125F, 0.125F, 0.125F, 0.5F};
    primary.mix = 1.0;
    ffgui::GradeGraph fullGrade;
    fullGrade.add(primary);
    const auto processed = ffgui::process_color_frame(
        premultiplied, {}, {}, fullGrade, {});
    require(std::abs(processed.rgba[0] - 0.25F) < 0.00001F &&
                std::abs(processed.rgba[3] - 0.5F) < 0.00001F,
            "premultiplied alpha must be separated for grading and restored afterward");

    ffgui::GradeGraph unsupported;
    unsupported.add(ffgui::make_default_grade_node(ffgui::GradeNodeType::qualifier, "qualifier"));
    require_throws<std::invalid_argument>([&] {
        ffgui::apply_grade_graph_rgba32f(pixel, 1, unsupported);
    }, "spatial grade nodes must never be silently ignored by the reference renderer");

    const auto cube = ffgui::bake_color_cube({}, {}, fullGrade, {}, 2);
    require(cube.contains("LUT_3D_SIZE 2") && std::ranges::count(cube, '\n') == 12,
            "clip color cube must contain every RGB lattice point from the reference path");
}

void test_advanced_grade_nodes_share_the_float_reference_contract() {
    constexpr std::array advancedTypes{
        ffgui::GradeNodeType::log_wheels,
        ffgui::GradeNodeType::rgb_curves,
        ffgui::GradeNodeType::hue_curves,
        ffgui::GradeNodeType::hdr_zones,
        ffgui::GradeNodeType::color_warper};
    for (const auto type : advancedTypes) {
        ffgui::GradeGraph identity;
        identity.add(ffgui::make_default_grade_node(type, "identity"));
        float pixel[]{0.18F, 0.32F, 0.71F, 0.37F};
        ffgui::apply_grade_graph_rgba32f(pixel, 1, identity);
        require(std::abs(pixel[0] - 0.18F) < 0.00002F &&
                    std::abs(pixel[1] - 0.32F) < 0.00002F &&
                    std::abs(pixel[2] - 0.71F) < 0.00002F &&
                    std::abs(pixel[3] - 0.37F) < 0.000001F,
                "every advanced grade node must be identity by default and preserve alpha");
    }

    auto primary = ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "primary");
    primary.parameters["temperature"] = 60.0;
    primary.parameters["tint"] = 20.0;
    primary.parameters["colorBoost"] = 30.0;
    ffgui::GradeGraph primaryGraph;
    primaryGraph.add(primary);
    float neutral[]{0.4F, 0.4F, 0.4F, 0.25F};
    ffgui::apply_grade_graph_rgba32f(neutral, 1, primaryGraph);
    require(neutral[0] > neutral[1] && neutral[1] > neutral[2] &&
                std::abs(neutral[3] - 0.25F) < 0.000001F,
            "temperature and tint must execute in the common primary renderer");

    auto log = ffgui::make_default_grade_node(ffgui::GradeNodeType::log_wheels, "log");
    log.parameters["shadowR"] = 0.2;
    ffgui::GradeGraph logGraph;
    logGraph.add(log);
    float logPixels[]{0.02F, 0.02F, 0.02F, 1.0F, 2.0F, 2.0F, 2.0F, 1.0F};
    ffgui::apply_grade_graph_rgba32f(logPixels, 2, logGraph);
    require(logPixels[0] - 0.02F > logPixels[4] - 2.0F + 0.05F,
            "log shadow wheel must protect highlights while changing dark values");

    auto curves = ffgui::make_default_grade_node(ffgui::GradeNodeType::rgb_curves, "curves");
    curves.curves["red"] = {{0.0, 0.0}, {0.5, 0.8}, {1.0, 1.0}};
    ffgui::GradeGraph curveGraph;
    curveGraph.add(curves);
    float curvePixel[]{0.5F, 0.5F, 0.5F, 0.6F};
    ffgui::apply_grade_graph_rgba32f(curvePixel, 1, curveGraph);
    require(std::abs(curvePixel[0] - 0.8F) < 0.00001F &&
                std::abs(curvePixel[1] - 0.5F) < 0.00001F,
            "RGB curves must apply master and per-channel curves in sequence");

    auto hue = ffgui::make_default_grade_node(ffgui::GradeNodeType::hue_curves, "hue");
    hue.curves["hueVsHue"] = {{0.0, 0.333333}, {1.0, 1.333333}};
    ffgui::GradeGraph hueGraph;
    hueGraph.add(hue);
    float red[]{1.0F, 0.0F, 0.0F, 0.8F};
    ffgui::apply_grade_graph_rgba32f(red, 1, hueGraph);
    require(red[1] > 0.9F && red[0] < 0.1F && red[2] < 0.1F,
            "Hue vs Hue must rotate selected colors without changing alpha");

    auto hdr = ffgui::make_default_grade_node(ffgui::GradeNodeType::hdr_zones, "hdr");
    hdr.parameters["midtoneExposure"] = 1.0;
    ffgui::GradeGraph hdrGraph;
    hdrGraph.add(hdr);
    float middleGray[]{0.18F, 0.18F, 0.18F, 1.0F};
    ffgui::apply_grade_graph_rgba32f(middleGray, 1, hdrGraph);
    require(middleGray[0] > 0.22F && middleGray[0] < 0.37F,
            "HDR zone exposure must affect its selected scene-linear luminance range");

    auto warper = ffgui::make_default_grade_node(ffgui::GradeNodeType::color_warper, "warper");
    warper.parameters["satScale0"] = 0.0;
    ffgui::GradeGraph warperGraph;
    warperGraph.add(warper);
    float warpedRed[]{1.0F, 0.0F, 0.0F, 0.5F};
    ffgui::apply_grade_graph_rgba32f(warpedRed, 1, warperGraph);
    require(std::abs(warpedRed[0] - warpedRed[1]) < 0.00001F &&
                std::abs(warpedRed[1] - warpedRed[2]) < 0.00001F,
            "Color Warper hue grid must apply local saturation scaling");
}

void test_external_lut_node_uses_ocio_and_preserves_mix_and_alpha() {
    const auto root = std::filesystem::temp_directory_path() / "ffgui-grade-lut-test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto path = root / "invert.cube";
    {
        std::ofstream stream(path, std::ios::binary);
        stream << "TITLE \"ffgui invert\"\n"
                  "LUT_3D_SIZE 2\n"
                  "DOMAIN_MIN 0 0 0\n"
                  "DOMAIN_MAX 1 1 1\n";
        for (int blue = 0; blue < 2; ++blue) {
            for (int green = 0; green < 2; ++green) {
                for (int red = 0; red < 2; ++red) {
                    stream << 1 - red << ' ' << 1 - green << ' ' << 1 - blue << '\n';
                }
            }
        }
    }
    ffgui::validate_grade_lut_file(path.string());
    auto node = ffgui::make_default_grade_node(ffgui::GradeNodeType::lut, "lut");
    node.external_path = path.string();
    node.mix = 0.5;
    ffgui::GradeGraph graph;
    graph.add(node);
    require(graph.render_unsupported_nodes().empty(),
            "a valid external LUT node must be supported by the common renderer");
    float pixel[]{0.2F, 0.4F, 0.6F, 0.37F};
    ffgui::apply_grade_graph_rgba32f(pixel, 1, graph);
    require(std::abs(pixel[0] - 0.5F) < 0.0001F &&
                std::abs(pixel[1] - 0.5F) < 0.0001F &&
                std::abs(pixel[2] - 0.5F) < 0.0001F &&
                std::abs(pixel[3] - 0.37F) < 0.000001F,
            "OCIO LUT evaluation must honor node mix without changing alpha");
    const auto published = ffgui::build_color_cube({}, {}, graph, {}, 2);
    require(published.size == 2 && published.rgb.size() == 24 &&
                std::ranges::all_of(published.rgb, [](float value) {
                    return std::abs(value - 0.5F) < 0.0001F;
                }),
            "external looks must be baked into the same 3D texture published to GPU previews");
    require_throws<std::runtime_error>([&] {
        ffgui::validate_grade_lut_file((root / "missing.cube").string());
    }, "an offline LUT must fail validation instead of being silently ignored");
    auto unsupported = ffgui::make_default_grade_node(ffgui::GradeNodeType::lut, "bad");
    unsupported.external_path = (root / "look.png").string();
    require_throws<std::invalid_argument>([&] { unsupported.validate(); },
        "grade LUT nodes must reject files outside the declared CG interchange formats");
    std::filesystem::remove_all(root);
}

void test_scope_analyzer_builds_histogram_waveform_parade_and_vectorscope() {
    const std::array<std::uint8_t, 16> pixels{
        0, 0, 255, 255, 0, 255, 0, 255,
        255, 0, 0, 255, 255, 255, 255, 255};
    const auto scopes = ffgui::analyze_scope_bgra8(
        pixels.data(), 2, 2, 8, 42, ffgui::ScopeReferenceStage::post_display);
    require(scopes.serial == 42 && scopes.sampled_pixels == 4 &&
                scopes.histogram[0][255] == 2 && scopes.histogram[0][0] == 2 &&
                scopes.histogram[1][255] == 2 && scopes.histogram[2][255] == 2,
            "scope histograms must count final display RGB channels exactly");
    const auto waveformCount = std::accumulate(
        scopes.waveform.begin(), scopes.waveform.end(), std::uint64_t{});
    const auto vectorscopeCount = std::accumulate(
        scopes.vectorscope.begin(), scopes.vectorscope.end(), std::uint64_t{});
    require(waveformCount == 4 && vectorscopeCount == 4 &&
                std::ranges::all_of(scopes.rgb_parade, [](const auto& channel) {
                    return std::accumulate(
                        channel.begin(), channel.end(), std::uint64_t{}) == 4;
                }),
            "waveform, RGB parade and vectorscope must receive every sampled pixel");

    const std::array<std::uint8_t, 16> rgbaPixels{
        255, 0, 0, 255, 0, 255, 0, 255,
        0, 0, 255, 255, 255, 255, 255, 255};
    const auto rgbaScopes = ffgui::analyze_scope_rgba8(
        rgbaPixels.data(), 2, 2, 8, 44, ffgui::ScopeReferenceStage::post_display);
    require(rgbaScopes.histogram == scopes.histogram &&
                rgbaScopes.waveform == scopes.waveform &&
                rgbaScopes.rgb_parade == scopes.rgb_parade &&
                rgbaScopes.vectorscope == scopes.vectorscope,
            "RGBA GPU downloads and BGRA CPU frames must produce identical scopes");

    ffgui::FloatImageFrame frame;
    frame.width = 2;
    frame.height = 2;
    frame.rgba = {
        1.0F, 0.0F, 0.0F, 1.0F, 0.0F, 1.0F, 0.0F, 1.0F,
        0.0F, 0.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F, 1.0F};
    const auto floatScopes = ffgui::analyze_scope_float(frame, 43);
    require(floatScopes.serial == 43 && floatScopes.histogram == scopes.histogram,
            "float and BGRA scope inputs must agree for the same display-referred pixels");
}

void test_oiio_probe_reports_exr_layers_alpha_and_color_space() {
    const auto root = std::filesystem::temp_directory_path() / "ffgui-oiio-probe-test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto path = root / "layered.exr";
    OIIO::ImageSpec spec(2, 2, 4, OIIO::TypeDesc::FLOAT);
    spec.channelnames = {"beauty.R", "beauty.G", "beauty.B", "beauty.A"};
    spec.alpha_channel = 3;
    spec.attribute("oiio:ColorSpace", "ACEScg");
    auto output = OIIO::ImageOutput::create(path.string());
    require(static_cast<bool>(output) && output->open(path.string(), spec),
            "OpenImageIO EXR test output must open");
    const std::vector<float> pixels{
        0.1F, 0.2F, 0.3F, 0.25F, 0.4F, 0.5F, 0.6F, 0.5F,
        0.7F, 0.8F, 0.9F, 0.75F, 1.0F, 0.9F, 0.8F, 1.0F};
    require(output->write_image(OIIO::TypeDesc::FLOAT, pixels.data()) && output->close(),
            "OpenImageIO EXR test pixels must be written");
    const auto metadata = ffgui::probe_image_metadata(path);
    require(metadata.color_space == "ACEScg" && metadata.parts.size() == 1 &&
                metadata.parts[0].has_alpha &&
                metadata.parts[0].layers == std::vector<std::string>{"beauty"},
            "OpenImageIO probe must expose EXR layer, alpha and source color space");
    const auto frame = ffgui::read_float_image_frame(
        {path, metadata.parts[0].name,
         {"beauty.R", "beauty.G", "beauty.B", "beauty.A"}});
    require(frame.width == 2 && frame.height == 2 && frame.rgba == pixels &&
                frame.color_space == "ACEScg" && frame.premultiplied,
            "float frame source must preserve selected AOV values, alpha and color metadata");
    const auto remapped = ffgui::read_float_image_frame(
        {path, metadata.parts[0].name,
         {"beauty.B", "beauty.R", "missing", "missingAlpha"}});
    require(std::abs(remapped.rgba[0] - 0.3F) < 0.00001F &&
                std::abs(remapped.rgba[1] - 0.1F) < 0.00001F &&
                remapped.rgba[2] == 0.0F && remapped.rgba[3] == 1.0F,
            "AOV channel mapping must reorder channels and use safe RGB/alpha defaults");
    const auto selectedPath = root / "selected.exr";
    ffgui::write_selected_exr_frame(
        {path, metadata.parts[0].name,
         {"beauty.B", "beauty.R", "missing", "missingAlpha"}},
        selectedPath);
    const auto selected = ffgui::read_float_image_frame(
        {selectedPath, "part0", {"R", "G", "B", "A"}});
    require(std::abs(selected.rgba[0] - 0.3F) < 0.001F &&
                std::abs(selected.rgba[1] - 0.1F) < 0.001F &&
                std::abs(selected.rgba[2]) < 0.001F &&
                std::abs(selected.rgba[3] - 1.0F) < 0.001F,
            "selected AOV cache EXR must preserve remapped half-float RGBA pixels");
    ffgui::ImageFrameCache cache(64);
    const auto first = cache.get({path, metadata.parts[0].name,
                                  {"beauty.R", "beauty.G", "beauty.B", "beauty.A"}});
    const auto second = cache.get({path, metadata.parts[0].name,
                                   {"beauty.R", "beauty.G", "beauty.B", "beauty.A"}});
    require(first == second && cache.entry_count() == 1 && cache.byte_size() == 64,
            "frame cache must reuse an immutable float frame inside its byte budget");
    cache.invalidate(path);
    require(cache.entry_count() == 0 && cache.byte_size() == 0,
            "frame cache invalidation must remove changed source frames");

    const auto frame1001 = root / "plate.1001.exr";
    const auto frame1003 = root / "plate.1003.exr";
    std::filesystem::copy_file(path, frame1001);
    std::filesystem::copy_file(path, frame1003);
    ffgui::ImageSequenceDescriptor sequence;
    sequence.directory = root;
    sequence.prefix = "plate.";
    sequence.suffix = ".exr";
    sequence.padding = 4;
    sequence.first_frame = 1001;
    sequence.last_frame = 1003;
    sequence.frame_rate = {1, 1};
    sequence.present_frames = {1001, 1003};
    sequence.missing_frames = {1002};
    sequence.exr_part = "part0";
    sequence.exr_layer = "beauty";
    sequence.channel_mapping = {"beauty.R", "beauty.G", "beauty.B", "beauty.A"};
    ffgui::SourceColorDescriptor sourceColor;
    sourceColor.input_color_space = "ACEScg";
    TimelineModel sequenceTimeline;
    sequenceTimeline.add_asset(MediaAsset{
        "sequence", frame1001, seconds(3), {0, seconds(1), seconds(2)}, {}, {},
        ffgui::MediaKind::image_sequence, sequence, sourceColor, frame1001, frame1001});
    Clip sequenceClip{"sequence-clip", "sequence", 0, seconds(3)};
    sequenceClip.color.brightness = 0.05;
    auto exposure = ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "exposure");
    exposure.parameters["exposure"] = 1.0;
    sequenceClip.grade.add(std::move(exposure));
    sequenceTimeline.append_clip(std::move(sequenceClip));
    ffgui::TimelineFrameServer frameServer(1024);
    const auto timelineFrame = frameServer.render(sequenceTimeline, seconds(1), {}, {});
    require(timelineFrame.requested_sequence_frame == 1002 &&
                timelineFrame.resolved_sequence_frame == 1001 &&
                timelineFrame.substituted_missing_frame &&
                std::abs(timelineFrame.processed.rgba[0] - 0.225F) < 0.00001F,
            "timeline frame server must map time, substitute missing frames and apply clip controls before grading");
    TimelineModel dissolveTimeline;
    dissolveTimeline.add_asset(MediaAsset{
        "sequence", frame1001, seconds(3), {0, seconds(1), seconds(2)}, {}, {},
        ffgui::MediaKind::image_sequence, sequence, sourceColor, frame1001, frame1001});
    Clip outgoing{"outgoing", "sequence", 0, seconds(2)};
    auto outgoingExposure =
        ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "outgoing exposure");
    outgoingExposure.parameters["exposure"] = 1.0;
    outgoing.grade.add(std::move(outgoingExposure));
    dissolveTimeline.append_clip(std::move(outgoing));
    dissolveTimeline.append_clip(Clip{
        "incoming", "sequence", 0, seconds(2), {}, 1.0, {}, seconds(1)});
    const auto dissolveFrame = frameServer.render(
        dissolveTimeline, seconds(1) + seconds(1) / 2, {}, {});
    require(dissolveFrame.clip_id == "incoming" &&
                std::abs(dissolveFrame.processed.rgba[0] - 0.15F) < 0.00001F,
            "timeline frame server must grade both clips before blending a dissolve");

    const auto multipartPath = root / "stereo.exr";
    std::array<OIIO::ImageSpec, 2> multipartSpecs{
        OIIO::ImageSpec(1, 1, 4, OIIO::TypeDesc::FLOAT),
        OIIO::ImageSpec(1, 1, 4, OIIO::TypeDesc::FLOAT)};
    multipartSpecs[0].channelnames = {"R", "G", "B", "A"};
    multipartSpecs[0].attribute("oiio:subimagename", "leftPart");
    multipartSpecs[0].attribute("view", "left");
    multipartSpecs[1].channelnames = {"R", "G", "B", "A"};
    multipartSpecs[1].attribute("oiio:subimagename", "rightPart");
    multipartSpecs[1].attribute("view", "right");
    auto multipartOutput = OIIO::ImageOutput::create(multipartPath.string());
    require(static_cast<bool>(multipartOutput) &&
                multipartOutput->open(multipartPath.string(), 2, multipartSpecs.data()),
            "multipart EXR test output must open");
    const std::array<float, 4> leftPixel{0.1F, 0.2F, 0.3F, 1.0F};
    const std::array<float, 4> rightPixel{0.7F, 0.8F, 0.9F, 1.0F};
    require(multipartOutput->write_image(OIIO::TypeDesc::FLOAT, leftPixel.data()) &&
                multipartOutput->open(
                    multipartPath.string(), multipartSpecs[1],
                    OIIO::ImageOutput::AppendSubimage) &&
                multipartOutput->write_image(OIIO::TypeDesc::FLOAT, rightPixel.data()) &&
                multipartOutput->close(),
            "multipart EXR views must be written");
    const auto multipartMetadata = ffgui::probe_image_metadata(multipartPath);
    require(multipartMetadata.parts.size() == 2 &&
                multipartMetadata.parts[0].view == "left" &&
                multipartMetadata.parts[1].view == "right",
            "EXR probe must retain per-part view metadata");
    const auto rightFrame = ffgui::read_float_image_frame(
        {multipartPath, "rightPart", {"R", "G", "B", "A"}, "right"});
    require(std::abs(rightFrame.rgba[0] - 0.7F) < 0.00001F,
            "EXR frame source must select the requested part/view pixels");
    require_throws<std::invalid_argument>([&] {
        static_cast<void>(ffgui::read_float_image_frame(
            {multipartPath, "rightPart", {"R", "G", "B", "A"}, "left"}));
    }, "mismatched EXR part/view selection must be rejected");
    std::filesystem::remove_all(root);
}

void test_magnetic_trim_closes_space() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"clip-a", "asset-a", seconds(1), seconds(6)});
    timeline.append_clip(Clip{"clip-b", "asset-b", seconds(5), seconds(4)});

    timeline.trim_clip("clip-a", seconds(2), seconds(2));
    const auto spans = timeline.snapshot();
    require(spans.size() == 2, "timeline must keep both clips");
    require(spans[0].timeline_in == 0 && spans[0].timeline_out == seconds(2), "trimmed clip span");
    require(spans[1].timeline_in == seconds(2), "next clip must magnetically follow trim");
    require(timeline.duration() == seconds(6), "timeline duration must be the active clip sum");
}

void test_global_frame_trim_is_atomic_magnetic_and_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"first", "asset-a", 0, seconds(7)});
    timeline.append_clip(Clip{"second", "asset-a", 0, seconds(7)});
    timeline.trim_all_clip_edges(1, 1);
    require(timeline.clips()[0].source_in == seconds(1) &&
            timeline.clips()[0].duration == seconds(3),
            "global trim must use analyzed frame boundaries");
    require(timeline.snapshot()[1].timeline_in == seconds(3) &&
            timeline.duration() == seconds(6),
            "global trim must magnetically close every shortened edge");
    require(timeline.undo() && timeline.duration() == seconds(14),
            "global trim must be one undoable edit");
    const auto before = timeline.clips();
    require_throws<std::invalid_argument>(
        [&] { timeline.trim_all_clip_edges(4, 1); },
        "global trim must reject settings that erase a clip");
    require(timeline.clips() == before, "rejected global trim must be atomic");
}

void test_clip_color_is_atomic_and_validated() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"first", "asset-a", 0, seconds(2)});
    timeline.append_clip(Clip{"second", "asset-a", seconds(2), seconds(2)});
    timeline.set_clips_color({"first", "second"}, ffgui::ClipColor{0.2, 1.1, 0.8});
    require(timeline.clips()[0].color == timeline.clips()[1].color,
            "multi-selection color grading must apply atomically");
    require_throws<std::invalid_argument>(
        [&] { timeline.set_clips_color({"first"}, ffgui::ClipColor{2.0, 1.0, 1.0}); },
        "out-of-range color grading must fail");
}

void test_dissolve_overlaps_adjacent_clips_and_is_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"first", "asset-a", 0, seconds(4)});
    timeline.append_clip(Clip{"second", "asset-a", seconds(2), seconds(4)});
    timeline.set_clip_dissolve("second", seconds(1));
    const auto spans = timeline.snapshot();
    require(timeline.duration() == seconds(7),
            "one-second dissolve must shorten the sequence by its overlap");
    require(spans[0].timeline_out == seconds(4) &&
            spans[1].timeline_in == seconds(3),
            "incoming clip must overlap the outgoing clip on the same boundary");
    const auto mapped = timeline.locate(3'500'000'000);
    require(mapped.has_value() && mapped->clip_id == "second" &&
            mapped->clip_time == 500'000'000,
            "overlap seeking must prefer the incoming clip coordinate");
    require(timeline.undo() && timeline.duration() == seconds(8),
            "dissolve must be one undoable edit");
    require_throws<std::invalid_argument>(
        [&] { timeline.set_clip_dissolve("first", seconds(1)); },
        "first clip cannot have an incoming dissolve");
}

void test_insert_uses_overlapped_timeline_coordinates() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"first", "asset-a", 0, seconds(4)});
    timeline.append_clip(Clip{"second", "asset-a", seconds(2), seconds(4)});
    timeline.set_clip_dissolve("second", seconds(1));
    timeline.insert_clip_at(
        seconds(5), Clip{"inserted", "asset-a", seconds(7), seconds(1)},
        "second-left", "second-right");
    const auto& clips = timeline.clips();
    require(clips.size() == 4 && clips[1].id == "second-left" &&
            clips[1].duration == seconds(2) && clips[2].id == "inserted" &&
            clips[3].id == "second-right" && clips[3].source_in == seconds(4),
            "insertion after a dissolve must split the incoming clip at its overlapped coordinate");
    require(clips[1].transition_in == seconds(1) && clips[3].transition_in == 0 &&
            timeline.duration() == seconds(8),
            "split remainders must not duplicate an incoming transition");
}

void test_snapshot_preserves_asset_audio_presence() {
    TimelineModel timeline;
    timeline.add_asset(MediaAsset{"silent", "silent.mp4", seconds(2)});
    timeline.add_asset(MediaAsset{
        "audio", "audio.mp4", seconds(2), {}, {0.25F, 0.5F}});
    timeline.append_clip(Clip{"silent-clip", "silent", 0, seconds(1)});
    timeline.append_clip(Clip{"audio-clip", "audio", 0, seconds(1)});
    const auto spans = timeline.snapshot();
    require(!spans[0].has_audio, "silent asset span must not advertise an audio stream");
    require(spans[1].has_audio, "audio asset span must preserve audio presence");
}

void test_sequence_to_source_mapping() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"clip-a", "asset-a", seconds(1), seconds(6)});
    timeline.append_clip(Clip{"clip-b", "asset-b", seconds(5), seconds(4)});

    const auto mapped = timeline.locate(seconds(7));
    require(mapped.has_value(), "sequence position must resolve");
    require(mapped->clip_id == "clip-b", "sequence position must select second clip");
    require(mapped->clip_time == seconds(1), "clip-local position must be relative");
    require(mapped->source_time == seconds(6), "source position must include trim in-point");
    require(
        timeline.timeline_time_for_source("clip-b", seconds(7)) == seconds(8),
        "source position must map back to sequence time");
    require(!timeline.locate(seconds(10)).has_value(), "timeline end is half-open");
}

void test_vfr_frame_stepping_respects_trims_and_clip_boundaries() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"first", "asset-a", seconds(1), seconds(3)});
    timeline.append_clip(Clip{"second", "asset-a", seconds(4), seconds(4)});

    require(timeline.next_frame_time(0) == seconds(1), "next step must follow VFR PTS");
    require(timeline.next_frame_time(seconds(1)) == seconds(3),
            "next step must land on the magnetic clip boundary");
    require(timeline.next_frame_time(seconds(3)) == seconds(6),
            "next step in the second clip must use its source in-point");
    require(timeline.next_frame_time(seconds(6)) == seconds(7),
            "last frame step must reach the sequence end");
    require(!timeline.next_frame_time(seconds(7)).has_value(), "cannot step past the end");

    require(timeline.previous_frame_time(seconds(7)) == seconds(6),
            "previous step from the end must reach the last visible frame");
    require(timeline.previous_frame_time(seconds(6)) == seconds(3),
            "previous VFR step must reach the second clip in-point");
    require(timeline.previous_frame_time(seconds(3)) == seconds(1),
            "previous step at a cut must enter the preceding clip");
    require(!timeline.previous_frame_time(0).has_value(), "cannot step before the start");
}

void test_trim_and_split_snap_to_vfr_frame_boundaries() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"clip", "asset-a", seconds(1), seconds(6)});
    timeline.clear_history();

    timeline.trim_clip_to_frame_boundaries("clip", 1'600'000'000, 4'600'000'000);
    require(timeline.clips()[0].source_in == seconds(2), "trim in must snap to nearest PTS");
    require(timeline.clips()[0].source_out() == seconds(7), "trim out must snap to boundary");
    const auto revision = timeline.revision();
    timeline.trim_clip_to_frame_boundaries("clip", 2'100'000'000, 4'800'000'000);
    require(timeline.revision() == revision, "same snapped range must not create undo history");

    const auto snapped = timeline.nearest_frame_time(1'700'000'000);
    require(snapped == seconds(2), "sequence split position must snap through source PTS");
    timeline.split_at(snapped.value(), "left", "right");
    require(timeline.clips()[0].duration == seconds(2), "left split must end at snapped frame");
    require(timeline.clips()[1].source_in == seconds(4), "right split must start on frame PTS");
}

void test_split_preserves_duration_and_source_boundary() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"original", "asset-a", seconds(1), seconds(6)});
    timeline.split_at(seconds(2), "left", "right");

    const auto spans = timeline.snapshot();
    require(spans.size() == 2, "split must create two clips");
    require(spans[0].clip.id == "left" && spans[0].clip.duration == seconds(2), "left split");
    require(spans[1].clip.id == "right", "right split id");
    require(spans[1].clip.source_in == seconds(3), "right split source boundary");
    require(spans[1].clip.duration == seconds(4), "right split duration");
    require(timeline.duration() == seconds(6), "split must preserve sequence duration");
}

void test_reorder_uses_insertion_index_after_removal() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(1)});
    timeline.append_clip(Clip{"b", "asset-a", seconds(1), seconds(1)});
    timeline.append_clip(Clip{"c", "asset-a", seconds(2), seconds(1)});

    timeline.move_clip("c", 0);
    require(timeline.clips()[0].id == "c", "clip must move to the front");
    timeline.move_clip("c", 2);
    require(timeline.clips()[2].id == "c", "clip must move to the end");
    require(timeline.duration() == seconds(3), "reorder must preserve duration");
}

void test_duplicate_style_insert_is_magnetic_and_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"original", "asset-a", seconds(1), seconds(2)});
    timeline.clear_history();
    timeline.insert_clip(1, Clip{"copy", "asset-a", seconds(1), seconds(2)});
    const auto spans = timeline.snapshot();
    require(spans.size() == 2, "duplicate insert must keep both clips");
    require(spans[1].timeline_in == seconds(2), "duplicate must magnetically follow original");
    require(timeline.undo(), "duplicate insert must be undoable in one step");
    require(timeline.clips().size() == 1, "undo must remove only the duplicate");
}

void test_time_insert_splits_once_and_is_single_step_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"original", "asset-a", seconds(1), seconds(6)});
    timeline.clear_history();

    timeline.insert_clip_at(
        seconds(2),
        Clip{"inserted", "asset-b", 0, seconds(3)},
        "left",
        "right");
    const auto spans = timeline.snapshot();
    require(spans.size() == 3, "time insert must split the occupied clip around the insert");
    require(spans[0].clip.id == "left" && spans[0].clip.duration == seconds(2),
            "left side must preserve the source before the insertion point");
    require(spans[1].clip.id == "inserted" && spans[1].timeline_in == seconds(2),
            "inserted media must begin at the requested timeline time");
    require(spans[2].clip.id == "right" && spans[2].clip.source_in == seconds(3),
            "right side must resume the original source after the split");
    require(timeline.duration() == seconds(9), "insert edit must extend the magnetic timeline");
    require(timeline.undo(), "split insert must be one undoable edit");
    require(timeline.clips().size() == 1 && timeline.clips()[0].id == "original",
            "one undo must restore the unsplit original clip");

    timeline.insert_clip_at(
        timeline.duration(),
        Clip{"tail", "asset-b", 0, seconds(1)},
        "unused-left",
        "unused-right");
    require(timeline.clips().back().id == "tail", "inserting at the end must append");
}

void test_multi_clip_delete_is_atomic_magnetic_and_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(1)});
    timeline.append_clip(Clip{"b", "asset-a", seconds(1), seconds(1)});
    timeline.append_clip(Clip{"c", "asset-b", 0, seconds(2)});
    timeline.append_clip(Clip{"d", "asset-b", seconds(2), seconds(1)});
    timeline.clear_history();

    timeline.erase_clips({"b", "d"});
    const auto spans = timeline.snapshot();
    require(spans.size() == 2, "multi-delete must remove every selected clip");
    require(spans[0].clip.id == "a" && spans[1].clip.id == "c",
            "multi-delete must preserve the order of remaining clips");
    require(spans[1].timeline_in == seconds(1),
            "remaining clips must close all deleted gaps magnetically");
    require(timeline.undo(), "multi-delete must be a single undo step");
    require(timeline.clips().size() == 4, "one undo must restore all deleted clips");

    const auto revision = timeline.revision();
    require_throws<std::invalid_argument>(
        [&] { timeline.erase_clips({"a", "missing"}); },
        "unknown selection member must reject the whole delete");
    require(timeline.clips().size() == 4 && timeline.revision() == revision,
            "rejected multi-delete must not mutate timeline or history");
}

void test_multi_clip_insert_is_atomic_ordered_and_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"base", "asset-a", 0, seconds(1)});
    timeline.clear_history();

    timeline.insert_clips(1, {
        Clip{"copy-a", "asset-a", seconds(1), seconds(1)},
        Clip{"copy-b", "asset-b", 0, seconds(2)}});
    require(timeline.clips().size() == 3, "batch insert must add every clip");
    require(timeline.clips()[1].id == "copy-a" && timeline.clips()[2].id == "copy-b",
            "batch insert must preserve selection timeline order");
    require(timeline.undo(), "batch insert must be one undo step");
    require(timeline.clips().size() == 1, "one undo must remove the whole inserted batch");

    const auto revision = timeline.revision();
    require_throws<std::invalid_argument>(
        [&] {
            timeline.insert_clips(1, {
                Clip{"same", "asset-a", 0, seconds(1)},
                Clip{"same", "asset-b", 0, seconds(1)}});
        },
        "duplicate id inside insert batch must reject the whole batch");
    require(timeline.clips().size() == 1 && timeline.revision() == revision,
            "rejected batch insert must not mutate timeline or history");
}

void test_multi_clip_move_preserves_order_and_skips_noop_history() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(1)});
    timeline.append_clip(Clip{"b", "asset-a", seconds(1), seconds(1)});
    timeline.append_clip(Clip{"c", "asset-b", 0, seconds(1)});
    timeline.append_clip(Clip{"d", "asset-b", seconds(1), seconds(1)});
    timeline.clear_history();

    timeline.move_clips({"b", "d"}, 0);
    require(
        timeline.clips()[0].id == "b" && timeline.clips()[1].id == "d" &&
        timeline.clips()[2].id == "a" && timeline.clips()[3].id == "c",
        "group move must keep selected and remaining timeline order");
    require(timeline.undo(), "group move must be one undo step");

    const auto revision = timeline.revision();
    timeline.move_clips({"b", "c"}, 1);
    require(timeline.revision() == revision,
            "dropping a selected group at its current insertion point must be a no-op");
    require_throws<std::out_of_range>(
        [&] { timeline.move_clips({"b", "c"}, 3); },
        "group move past the remaining list must be rejected");
    require(timeline.revision() == revision, "rejected group move must not create history");
}

void test_range_delete_trims_boundaries_and_is_single_step_undoable() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(3)});
    timeline.append_clip(Clip{"b", "asset-b", seconds(2), seconds(4)});
    timeline.append_clip(Clip{"c", "asset-b", seconds(8), seconds(3)});
    timeline.clear_history();

    timeline.erase_range(seconds(2), seconds(8), "unused");
    require(timeline.clips().size() == 2, "range delete must remove covered middle clips");
    require(timeline.clips()[0].id == "a" && timeline.clips()[0].duration == seconds(2),
            "range delete must preserve the left boundary remainder");
    require(timeline.clips()[1].id == "c" &&
            timeline.clips()[1].source_in == seconds(9) &&
            timeline.clips()[1].duration == seconds(2),
            "range delete must preserve the right source remainder");
    require(timeline.duration() == seconds(4), "range delete must close the gap magnetically");
    require(timeline.undo(), "range delete must be one undo step");
    require(timeline.clips().size() == 3, "one undo must restore every affected clip");

    timeline.clear_history();
    timeline.erase_range(seconds(1), seconds(2), "a-right");
    require(timeline.clips().size() == 4, "range inside one clip must split it in two");
    require(timeline.clips()[0].id == "a" && timeline.clips()[0].duration == seconds(1),
            "single-clip range delete must keep its left side");
    require(timeline.clips()[1].id == "a-right" &&
            timeline.clips()[1].source_in == seconds(2) &&
            timeline.clips()[1].duration == seconds(1),
            "single-clip range delete must assign a unique right remainder");

    require(timeline.undo(), "single-clip range delete must be undoable");
    const auto revision = timeline.revision();
    require_throws<std::invalid_argument>(
        [&] { timeline.erase_range(seconds(1), seconds(2), "b"); },
        "colliding remainder id must reject range delete atomically");
    require(timeline.clips().size() == 3 && timeline.revision() == revision,
            "rejected range delete must preserve timeline and history");
}

void test_invalid_edits_are_rejected_without_mutation() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(2)});
    require_throws<std::invalid_argument>(
        [&] { timeline.append_clip(Clip{"a", "asset-b", 0, seconds(1)}); },
        "duplicate clip id must fail");
    require_throws<std::invalid_argument>(
        [&] { timeline.trim_clip("a", seconds(9), seconds(2)); },
        "out-of-range trim must fail");
    require(timeline.clips().size() == 1, "failed edits must not mutate timeline");
    require(timeline.clips()[0].duration == seconds(2), "failed trim must preserve clip");
}

void test_undo_redo_covers_structural_edits() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(4)});
    timeline.clear_history();

    timeline.trim_clip("a", seconds(1), seconds(2));
    timeline.split_at(seconds(1), "left", "right");
    timeline.erase_clip("left");
    require(timeline.clips().size() == 1 && timeline.clips()[0].id == "right", "edited state");

    require(timeline.undo(), "delete must be undoable");
    require(timeline.clips().size() == 2, "undo delete restores both split clips");
    require(timeline.undo(), "split must be undoable");
    require(timeline.clips().size() == 1 && timeline.clips()[0].id == "a", "undo split");
    require(timeline.undo(), "trim must be undoable");
    require(timeline.clips()[0].source_in == 0, "undo trim restores source in");
    require(timeline.redo() && timeline.redo() && timeline.redo(), "all edits must redo");
    require(timeline.clips().size() == 1 && timeline.clips()[0].id == "right", "redo state");

    require(timeline.undo(), "redo state must remain undoable");
    timeline.move_clip("right", 0);
    require(!timeline.can_redo(), "new edit must invalidate redo history");
}

void test_timeline_revision_changes_only_after_successful_edits() {
    auto timeline = make_timeline();
    const auto initial = timeline.revision();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(2)});
    require(timeline.revision() == initial + 1, "successful append must advance revision");
    const auto edited = timeline.revision();
    require_throws<std::invalid_argument>(
        [&] { timeline.trim_clip("a", seconds(9), seconds(2)); },
        "invalid edit should fail");
    require(timeline.revision() == edited, "rejected edit must not advance revision");
    timeline.trim_clip("a", seconds(1), seconds(1));
    require(timeline.revision() == edited + 1, "trim must advance revision");
    require(timeline.undo(), "trim undo must succeed");
    require(timeline.revision() == edited + 2, "undo must publish a distinct revision");
    require(timeline.redo(), "trim redo must succeed");
    require(timeline.revision() == edited + 3, "redo must publish a distinct revision");
}

void test_asset_replacement_preserves_clips_and_validates_source_ranges() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", seconds(2), seconds(5)});
    const auto revision = timeline.revision();
    timeline.replace_asset(MediaAsset{
        "asset-a", std::filesystem::path{"A-selected-aov.exr"}, seconds(10)});
    require(timeline.revision() == revision + 1,
            "asset replacement must publish a new preview revision");
    require(timeline.clips().size() == 1 && timeline.clips()[0].asset_id == "asset-a" &&
                timeline.clips()[0].source_in == seconds(2),
            "asset replacement must preserve clip identity and edit ranges");
    require(timeline.asset("asset-a")->path() ==
                std::filesystem::path{"A-selected-aov.exr"},
            "asset replacement must publish the new media source");
    const auto acceptedRevision = timeline.revision();
    require_throws<std::invalid_argument>(
        [&] { timeline.replace_asset(MediaAsset{
            "asset-a", std::filesystem::path{"too-short.exr"}, seconds(6)}); },
        "shorter replacement must reject clips outside its source duration");
    require(timeline.revision() == acceptedRevision &&
                timeline.asset("asset-a")->path() ==
                    std::filesystem::path{"A-selected-aov.exr"},
            "rejected asset replacement must leave the model unchanged");
}

void test_clip_audio_edits_are_atomic_and_follow_split_edges() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(4)});
    timeline.append_clip(Clip{"b", "asset-b", 0, seconds(3)});
    timeline.clear_history();

    const ffgui::ClipAudio audio{1.25, true, seconds(1), seconds(2)};
    timeline.set_clips_audio({"a", "b"}, audio);
    require(timeline.clips()[0].audio == audio && timeline.clips()[1].audio == audio,
            "one audio edit must update the full selection");
    require(timeline.undo(), "selected audio edit must be one undo step");
    require(timeline.clips()[0].audio == ffgui::ClipAudio{},
            "audio undo must restore defaults");
    timeline.redo();

    timeline.split_at(seconds(2), "left", "right");
    require(timeline.clips()[0].audio.fade_in == seconds(1) &&
            timeline.clips()[0].audio.fade_out == 0,
            "left split must preserve only the original outer fade");
    require(timeline.clips()[1].audio.fade_in == 0 &&
            timeline.clips()[1].audio.fade_out == seconds(2),
            "right split must preserve only the original outer fade");
    require_throws<std::invalid_argument>(
        [&] { timeline.set_clips_audio({"left"}, ffgui::ClipAudio{5.0, false, 0, 0}); },
        "unsafe audio gain must be rejected");
}

void test_playback_rate_maps_source_sequence_frames_and_captions() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{
        "fast", "asset-a", seconds(1), seconds(6), ffgui::ClipAudio{}, 2.0});
    timeline.append_clip(Clip{"tail", "asset-b", 0, seconds(4)});
    require(timeline.duration() == seconds(7),
            "2x source range must occupy half its source duration on the sequence");
    const auto mapped = timeline.locate(seconds(1));
    require(mapped.has_value() && mapped->clip_time == seconds(1) &&
            mapped->source_offset == seconds(2) && mapped->source_time == seconds(3),
            "sequence time must scale into the source range");
    require(timeline.timeline_time_for_source("fast", seconds(5)) == seconds(2),
            "source time must scale back into sequence coordinates");
    require(timeline.next_frame_time(0) == 500'000'000 &&
            timeline.next_frame_time(500'000'000) == 1'500'000'000,
            "VFR frame steps must be compressed by playback rate");

    timeline.add_caption(ffgui::CaptionCue{"after", "after", seconds(5), seconds(1)});
    timeline.clear_history();
    timeline.set_clips_playback_rate({"fast"}, 1.0);
    require(timeline.duration() == seconds(10) &&
            timeline.captions().front().timeline_in == seconds(8),
            "slowing a clip must push later captions by the inserted sequence time");
    require(timeline.undo() && timeline.duration() == seconds(7) &&
            timeline.captions().front().timeline_in == seconds(5),
            "speed and caption ripple must undo as one edit");

    timeline.split_at(1'500'000'000, "left", "right");
    require(timeline.clips()[0].duration == seconds(3) &&
            timeline.clips()[1].source_in == seconds(4) &&
            timeline.clips()[0].playback_rate == 2.0 &&
            timeline.clips()[1].playback_rate == 2.0,
            "speed-aware split must preserve source boundary and rate");
}

void test_caption_edits_and_ripple_mapping_share_undo_state() {
    auto timeline = make_timeline();
    timeline.append_clip(Clip{"a", "asset-a", 0, seconds(3)});
    timeline.append_clip(Clip{"b", "asset-b", 0, seconds(3)});
    timeline.clear_history();
    timeline.add_caption(ffgui::CaptionCue{"cap-a", "left", 500'000'000, seconds(1)});
    timeline.add_caption(ffgui::CaptionCue{"cap-b", "cross", 2'500'000'000, seconds(2)});
    timeline.add_caption(ffgui::CaptionCue{"cap-c", "after", seconds(5), 500'000'000});
    timeline.clear_history();

    timeline.erase_range(seconds(1), seconds(3), "unused");
    require(timeline.captions().size() == 3, "partial ripple overlaps must preserve cue remnants");
    require(timeline.captions()[0] == ffgui::CaptionCue{"cap-a", "left", 500'000'000, 500'000'000},
            "left-overlap cue must trim at ripple start");
    require(timeline.captions()[1] == ffgui::CaptionCue{"cap-b", "cross", seconds(1), 1'500'000'000},
            "right-overlap cue must move to ripple start");
    require(timeline.captions()[2].timeline_in == seconds(3),
            "later cues must shift by removed duration");
    require(timeline.undo(), "clip and caption ripple must undo together");
    require(timeline.duration() == seconds(6) && timeline.captions()[2].timeline_in == seconds(5),
            "undo must restore both sequence and caption coordinates");

    timeline.insert_clip(0, Clip{"insert", "asset-a", seconds(3), seconds(1)});
    require(timeline.captions()[0].timeline_in == 1'500'000'000 &&
            timeline.captions()[2].timeline_in == seconds(6),
            "inserted time must shift cues at and after the edit");
    require(timeline.undo() && timeline.captions()[0].timeline_in == 500'000'000,
            "insert ripple must be one undo step");

    timeline.clear_history();
    timeline.add_captions({
        {"batch-a", "one", seconds(1), 250'000'000},
        {"batch-b", "two", seconds(2), 250'000'000}});
    require(timeline.captions().size() == 5, "caption imports must append the complete batch");
    require(timeline.undo() && timeline.captions().size() == 3,
            "caption import batch must be one undo step");
}

void test_srt_utf8_multiline_parse_and_serialize_roundtrip() {
    const auto cues = ffgui::parse_srt(
        "\xEF\xBB\xBF" "1\r\n00:00:00,125 --> 00:00:01,750\r\n첫 줄\r\n둘째 줄\r\n\r\n"
        "2\n00:00:02.000 --> 00:00:03.250\nsecond\n");
    require(cues.size() == 2, "SRT parser must preserve two cue blocks");
    require(cues[0] == ffgui::SrtCue{"첫 줄\n둘째 줄", 125'000'000, 1'625'000'000},
            "SRT parser must preserve UTF-8, multiline text and millisecond timing");
    require(cues[1].timeline_in == seconds(2) && cues[1].duration == 1'250'000'000,
            "SRT parser must accept dot millisecond separators");

    const auto serialized = ffgui::serialize_srt(cues);
    require(serialized.contains("00:00:00,125 --> 00:00:01,750\r\n"),
            "SRT writer must emit canonical CRLF timestamps");
    require(serialized.contains("첫 줄\r\n둘째 줄\r\n\r\n"),
            "SRT writer must normalize multiline text to CRLF");
    require(ffgui::parse_srt(serialized) == cues,
            "serialized SRT must parse back without timing or text drift");
    require_throws<std::invalid_argument>(
        [] { static_cast<void>(ffgui::parse_srt("1\n00:00:02,000 --> 00:00:01,000\nbad\n")); },
        "negative SRT durations must be rejected");
}

void test_ffprobe_timestamp_parser_preserves_vfr() {
    require(ffgui::parse_ffprobe_seconds("12.345678901") == 12'345'678'901, "exact decimal ns");
    const auto pts = ffgui::parse_ffprobe_frame_pts(
        "-0.100000,\r\n-0.066000\n0.000000\n0.000000\n0.200000\n");
    require(pts.size() == 4, "duplicate frame timestamps must collapse");
    require(pts[0] == 0 && pts[1] == 34'000'000, "negative start must normalize to zero");
    require(pts[2] == 100'000'000 && pts[3] == 300'000'000, "VFR gaps must remain exact");
    require(ffgui::estimated_media_end(pts) == 500'000'000, "last frame duration estimate");
}

void test_ffprobe_frame_timeline_preserves_keyframes() {
    const auto timeline = ffgui::parse_ffprobe_frame_timeline(
        "1,-0.100000,\r\n0,-0.066000\n0,0.000000\n1,0.200000\n");
    require(timeline.frame_pts == std::vector<TimeNs>{0, 34'000'000, 100'000'000, 300'000'000},
            "combined frame parser must share the normalized PTS origin");
    require(timeline.keyframe_pts == std::vector<TimeNs>{0, 300'000'000},
            "keyframe flags must remain attached after normalization");
}

void test_ffmpeg_export_plan_preserves_clip_ranges_and_audio() {
    const auto plan = ffgui::compile_ffmpeg_export(ffgui::ExportRequest{
        {
            {std::filesystem::path{"A.mp4"}, 1'234'567'890, seconds(2), true},
            {std::filesystem::path{"B.mkv"}, seconds(4), 500'000'000, false},
        },
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::h264_nvenc});
    require(plan.duration == 2'500'000'000, "export duration must sum magnetic clips");
    const auto joined = [&] {
        std::string value;
        for (const auto& argument : plan.arguments) value += argument + '\n';
        return value;
    }();
    require(joined.contains("1.234567890"), "source in must retain nanosecond precision");
    require(joined.contains("0.500000000"), "sub-second clip duration must remain exact");
    require(joined.contains("[0:a:0]aresample=48000"), "audio source must be normalized");
    require(joined.contains("apad=whole_dur=2.000000000,atrim=duration=2.000000000"),
            "short source audio must be padded and clipped to the shot duration");
    require(joined.contains("anullsrc=r=48000:cl=stereo:d=0.500000000"),
            "silent clips must receive matching audio");
    require(joined.contains("concat=n=2:v=1:a=1"), "all clips must share one concat graph");
    require(joined.contains("h264_nvenc"), "requested GPU encoder must be selected");
}

void test_ffmpeg_export_plan_applies_clip_audio_controls() {
    auto request = ffgui::ExportRequest{
        {{std::filesystem::path{"A.mp4"}, 0, seconds(4), true,
          seconds(4), {0, seconds(4)}, 1.5, false, seconds(1), seconds(2)}},
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::libx264};
    request.prefer_stream_copy = true;
    request.concat_script_path = std::filesystem::path{"job.ffconcat"};
    const auto plan = ffgui::compile_ffmpeg_export(request);
    require(plan.mode == ffgui::ExportMode::transcode,
            "audio controls must prevent unsafe stream copy");
    std::string joined;
    for (const auto& argument : plan.arguments) joined += argument + '\n';
    require(joined.contains("volume=1.500000"), "clip gain must reach the audio graph");
    require(joined.contains("afade=t=in:st=0:d=1.000000000"),
            "fade in must start at the clip edge");
    require(joined.contains("afade=t=out:st=2.000000000:d=2.000000000"),
            "fade out must end at the clip edge");

    request.clips[0].audio_muted = true;
    const auto muted = ffgui::compile_ffmpeg_export(request);
    std::string mutedArguments;
    for (const auto& argument : muted.arguments) mutedArguments += argument + '\n';
    require(mutedArguments.contains("volume=0.000000"),
            "muted clips must render silent audio");
}

void test_ffmpeg_export_plan_burns_timeline_captions() {
    auto request = ffgui::ExportRequest{
        {{std::filesystem::path{"A.mp4"}, 0, seconds(4), true,
          seconds(4), {0, seconds(4)}}},
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::libx264};
    request.concat_script_path = std::filesystem::path{"job.ffconcat"};
    request.captions = {{"첫 줄\nsecond", 500'000'000, 1'250'000'000,
                         0.25, 0.35, 52, 65}};
    request.stamp = {true, "편집자", "검수본 v2", 10, 75, true};
    request.subtitle_script_path = std::filesystem::path{"D:/cache/job.ass"};
    const auto plan = ffgui::compile_ffmpeg_export(request);
    require(plan.mode == ffgui::ExportMode::transcode,
            "burned captions must disable stream copy");
    std::string arguments;
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("ass=filename='D\\:/cache/job.ass'"),
            "caption ASS file must be attached to the video graph");
    require(plan.subtitle_script.contains("Dialogue: 2,0:00:00.50,0:00:01.75"),
            "caption timestamps must retain centisecond ASS precision");
    require(arguments.contains("vstack=inputs=3[vstampexpanded]") &&
            plan.subtitle_script.contains("PlayResY: 864"),
            "expanded stamp must add top and bottom pixels without scaling the center clip");
    require(plan.subtitle_script.contains("Style: TextBackground0") &&
            plan.subtitle_script.contains("&H5A000000"),
            "caption black background opacity must compile into an ASS opaque-box style");
    require(plan.subtitle_script.contains("\\pos(320,324)\\fs52"),
            "caption drag coordinates and font size must reach the ASS script");
    require(plan.subtitle_script.contains("첫 줄\\Nsecond"),
            "caption text and line breaks must reach the ASS script");
    require(plan.subtitle_script.contains("작업자  편집자") &&
            plan.subtitle_script.contains("검수본 v2") &&
            plan.subtitle_script.contains("00:00:00"),
            "letterbox stamp metadata and timecode must reach the ASS script");

    request.stamp.expand_canvas = false;
    request.stamp.background_opacity = 50;
    const auto overlayPlan = ffgui::compile_ffmpeg_export(request);
    std::string overlayArguments;
    for (const auto& argument : overlayPlan.arguments) overlayArguments += argument + '\n';
    require(!overlayArguments.contains("vstampexpanded") &&
            overlayPlan.subtitle_script.contains("PlayResY: 720") &&
            overlayPlan.subtitle_script.contains("\\1a&H80&"),
            "overlay stamp opacity must darken the existing video without changing its canvas");
}

void test_ffmpeg_export_plan_applies_video_and_audio_speed() {
    auto request = ffgui::ExportRequest{
        {{std::filesystem::path{"A.mp4"}, 0, seconds(4), true,
          seconds(4), {0, seconds(4)}, 1.0, false, 0, 0, 2.0}},
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::libx264};
    request.concat_script_path = std::filesystem::path{"job.ffconcat"};
    const auto fast = ffgui::compile_ffmpeg_export(request);
    require(fast.duration == seconds(2) && fast.mode == ffgui::ExportMode::transcode,
            "2x speed must halve output duration and disable stream copy");
    std::string arguments;
    for (const auto& argument : fast.arguments) arguments += argument + '\n';
    require(arguments.contains("setpts=(PTS-STARTPTS)/2.000000"),
            "video speed must be compiled into setpts");
    require(arguments.contains("atempo=2.000000"),
            "audio speed must be compiled into atempo");

    request.clips[0].playback_rate = 0.25;
    const auto slow = ffgui::compile_ffmpeg_export(request);
    std::string slowArguments;
    for (const auto& argument : slow.arguments) slowArguments += argument + '\n';
    require(slow.duration == seconds(16) &&
            slowArguments.contains("atempo=0.500000,atempo=0.500000"),
            "0.25x speed must expand duration and chain valid atempo stages");
}

void test_ffmpeg_export_plan_rejects_invalid_requests() {
    require_throws<std::invalid_argument>(
        [] { static_cast<void>(ffgui::compile_ffmpeg_export(ffgui::ExportRequest{})); },
        "empty export must fail");
    require_throws<std::invalid_argument>(
        [] {
            static_cast<void>(ffgui::compile_ffmpeg_export(ffgui::ExportRequest{
                {{std::filesystem::path{"A.mp4"}, 0, 0, true}},
                std::filesystem::path{"out.mp4"},
                ffgui::ExportVideoEncoder::libx264}));
        },
        "zero-duration export clip must fail");
}

void test_ffmpeg_export_plan_uses_stream_copy_only_for_safe_keyframe_cuts() {
    auto request = ffgui::ExportRequest{
        {
            {std::filesystem::path{"same.mp4"}, 0, seconds(1), true,
             seconds(3), {0, seconds(1), seconds(2)}},
            {std::filesystem::path{"same.mp4"}, seconds(2), seconds(1), true,
             seconds(3), {0, seconds(1), seconds(2)}},
        },
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::h264_nvenc};
    request.concat_script_path = std::filesystem::path{"job.ffconcat"};
    const auto copied = ffgui::compile_ffmpeg_export(request);
    require(copied.mode == ffgui::ExportMode::stream_copy, "safe same-source GOP cuts should copy");
    require(copied.concat_script.contains("inpoint 0.000000000") &&
            copied.concat_script.contains("outpoint 3.000000000"),
            "concat script must preserve every source range");
    std::string arguments;
    for (const auto& argument : copied.arguments) arguments += argument + '\n';
    require(arguments.contains("copy") && !arguments.contains("h264_nvenc"),
            "stream-copy plan must avoid video encoding");

    request.clips[0].duration = 500'000'000;
    const auto transcoded = ffgui::compile_ffmpeg_export(request);
    require(transcoded.mode == ffgui::ExportMode::transcode,
            "non-keyframe boundary must fall back to transcoding");
}

void test_ffmpeg_export_plan_applies_codec_and_quality_presets() {
    auto request = ffgui::ExportRequest{
        {{std::filesystem::path{"A.mp4"}, 0, seconds(2), true}},
        std::filesystem::path{"result.mov"},
        ffgui::ExportVideoEncoder::hevc_nvenc};
    request.prefer_stream_copy = false;
    request.quality = ffgui::ExportQuality::high;
    auto plan = ffgui::compile_ffmpeg_export(request);
    std::string arguments;
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("hevc_nvenc") && arguments.contains("-cq\n18\n") &&
            arguments.contains("-tag:v\nhvc1"),
            "high-quality HEVC preset must select NVENC CQ 18 and QuickTime-compatible tag");
    require(arguments.contains("-b:a\n256k"), "high quality must use 256k audio");

    request.output_path = std::filesystem::path{"result.mkv"};
    plan = ffgui::compile_ffmpeg_export(request);
    arguments.clear();
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(!arguments.contains("-movflags") && !arguments.contains("hvc1"),
            "Matroska preset must not receive QuickTime-only muxer options");

    request.video_encoder = ffgui::ExportVideoEncoder::libx264;
    request.quality = ffgui::ExportQuality::compact;
    plan = ffgui::compile_ffmpeg_export(request);
    arguments.clear();
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("libx264") && arguments.contains("-preset\nfast") &&
            arguments.contains("-crf\n24") && arguments.contains("-b:a\n128k"),
            "compact H.264 preset must trade quality for speed and size");
}

void test_ffmpeg_export_plan_applies_resolution_fps_and_color() {
    auto request = ffgui::ExportRequest{
        {{std::filesystem::path{"A.mp4"}, 0, seconds(2), true}},
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::libx264};
    request.prefer_stream_copy = true;
    request.concat_script_path = std::filesystem::path{"job.ffconcat"};
    request.output_width = 1920;
    request.output_height = 1080;
    request.output_fps = 30;
    request.clips[0].brightness = 0.1;
    request.clips[0].contrast = 1.2;
    request.clips[0].saturation = 0.8;
    const auto plan = ffgui::compile_ffmpeg_export(request);
    require(plan.mode == ffgui::ExportMode::transcode,
            "output transforms must disable stream copy");
    std::string arguments;
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("scale=1920:1080") && arguments.contains("fps=30"),
            "resolution and frame-rate settings must reach the video graph");
    require(arguments.contains("eq=brightness=0.100000:contrast=1.200000:saturation=0.800000"),
            "color grading must reach the video graph");
}

void test_ffmpeg_export_plan_compiles_video_and_audio_dissolve() {
    auto request = ffgui::ExportRequest{
        {
            {std::filesystem::path{"A.mp4"}, 0, seconds(4), true},
            {std::filesystem::path{"B.mp4"}, 0, seconds(4), true},
        },
        std::filesystem::path{"result.mp4"},
        ffgui::ExportVideoEncoder::libx264};
    request.clips[1].transition_in = seconds(1);
    request.clips[0].color_lut_path = std::filesystem::path{"clip A.cube"};
    const auto plan = ffgui::compile_ffmpeg_export(request);
    require(plan.duration == seconds(7),
            "dissolve export duration must subtract the overlap");
    std::string arguments;
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("xfade=transition=fade:duration=1.000000000:offset=3.000000000"),
            "video dissolve must use the cumulative overlap offset");
    require(arguments.contains("lut3d=file='clip A.cube':interp=tetrahedral") &&
                arguments.find("lut3d=") < arguments.find("xfade="),
            "clip color LUT must run before the timeline dissolve");
    require(arguments.contains("acrossfade=d=1.000000000:c1=tri:c2=tri"),
            "audio dissolve must match the video overlap duration");
    require(arguments.contains("fps=30:round=near:eof_action=pass") &&
            arguments.contains("tpad=stop_mode=clone") &&
            arguments.contains("format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS"),
            "VFR dissolve inputs must share a constant frame rate, time base and pixel format");
    require(arguments.contains("trim=duration=4.000000000"),
            "dissolve input normalization must preserve the exact clip duration");
}

void test_ffmpeg_export_plan_builds_palette_optimized_gif_without_audio() {
    auto request = ffgui::ExportRequest{
        {{std::filesystem::path{"source.mkv"}, 0, seconds(3), true}},
        std::filesystem::path{"result.gif"},
        ffgui::ExportVideoEncoder::h264_nvenc};
    request.gif = {true, 480, 270, 8, 64, ffgui::GifDither::bayer, false};
    const auto plan = ffgui::compile_ffmpeg_export(request);
    require(plan.mode == ffgui::ExportMode::transcode,
            "GIF output must never enter stream-copy mode");
    std::string arguments;
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("fps=8,scale=480:270") &&
            arguments.contains("palettegen=max_colors=64:reserve_transparent=0:stats_mode=diff") &&
            arguments.contains("paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle"),
            "GIF output must use bounded resolution, frame rate and a generated palette");
    require(arguments.contains("\n-an\n") && arguments.contains("\n-loop\n-1\n") &&
            !arguments.contains("[aout]") && !arguments.contains("-c:a"),
            "GIF output must omit audio and honor one-shot playback");
}

void test_render_preflight_blocks_offline_and_unresolved_managed_media() {
    TimelineModel offline;
    offline.add_asset(MediaAsset{"offline", std::filesystem::path{"does-not-exist.mov"}, seconds(1)});
    offline.append_clip(Clip{"clip-offline", "offline", 0, seconds(1)});
    auto report = ffgui::build_render_preflight(offline, {});
    require(!report.can_render() && report.blocker_count() == 1,
            "offline media must block render preflight");

    const auto path = std::filesystem::temp_directory_path() / "ffgui-preflight-media.bin";
    { std::ofstream stream(path, std::ios::binary); stream << 'x'; }
    ffgui::SourceColorDescriptor unresolved;
    unresolved.unresolved = true;
    TimelineModel managed;
    managed.add_asset(MediaAsset{"managed", path, seconds(1), {}, {}, {},
        ffgui::MediaKind::video, std::nullopt, unresolved});
    managed.append_clip(Clip{"clip-managed", "managed", 0, seconds(1)});
    ffgui::ColorPipelineSettings settings;
    settings.mode = ffgui::ColorPipelineMode::aces_managed;
    report = ffgui::build_render_preflight(managed, settings);
    require(!report.can_render() && report.blocker_count() == 1,
            "managed output must block unresolved input color spaces");
    settings.mode = ffgui::ColorPipelineMode::legacy;
    require(ffgui::build_render_preflight(managed, settings).can_render(),
            "legacy output must preserve unresolved media without an automatic transform");
    auto graded = managed.clips().front();
    graded.id = "graded";
    graded.grade.add(ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "primary"));
    TimelineModel gradedTimeline;
    gradedTimeline.add_asset(MediaAsset{"managed", path, seconds(1)});
    gradedTimeline.append_clip(std::move(graded));
    report = ffgui::build_render_preflight(gradedTimeline, {});
    require(report.can_render(),
            "video grades must pass after per-clip LUT export wiring");
    ffgui::ImageSequenceDescriptor renderableSequence;
    renderableSequence.directory = path.parent_path();
    renderableSequence.prefix = path.filename().string();
    renderableSequence.first_frame = 1;
    renderableSequence.last_frame = 1;
    renderableSequence.present_frames = {1};
    TimelineModel gradedSequence;
    gradedSequence.add_asset(MediaAsset{
        "sequence", path, seconds(1), {0}, {}, {}, ffgui::MediaKind::image_sequence,
        renderableSequence, {}, path, path});
    auto sequenceClip = Clip{"graded-sequence", "sequence", 0, seconds(1)};
    sequenceClip.grade.add(
        ffgui::make_default_grade_node(ffgui::GradeNodeType::primary, "primary"));
    gradedSequence.append_clip(std::move(sequenceClip));
    require(ffgui::build_render_preflight(gradedSequence, {}).can_render(),
            "image sequence grades must pass after float export wiring");
    auto missingLut = ffgui::make_default_grade_node(ffgui::GradeNodeType::lut, "offline-lut");
    missingLut.external_path = (path.parent_path() / "offline.cube").string();
    auto missingLutGraph = gradedTimeline.clips().front().grade;
    missingLutGraph.add(std::move(missingLut));
    gradedTimeline.set_clip_grade_graph("graded", std::move(missingLutGraph));
    report = ffgui::build_render_preflight(gradedTimeline, {});
    require(!report.can_render() &&
                std::ranges::any_of(report.issues, [](const auto& issue) {
                    return issue.code == "offline-grade-lut";
                }),
            "an offline external LUT must block export during preflight");
    std::filesystem::remove(path);
}

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"vfr_frame_lookup", test_vfr_frame_lookup},
        {"image_sequence_detection_preserves_gaps_and_negative_frames", test_image_sequence_detection_preserves_gaps_and_negative_frames},
        {"media_asset_separates_original_and_playback_paths", test_media_asset_separates_original_and_playback_paths},
        {"color_pipeline_defaults_to_legacy_and_lut_preflight_rejects_spatial_nodes", test_color_pipeline_defaults_to_legacy_and_lut_preflight_rejects_spatial_nodes},
        {"ocio_aces_config_transforms_float_pixels_and_bakes_resolve_cube", test_ocio_aces_config_transforms_float_pixels_and_bakes_resolve_cube},
        {"float_grade_pipeline_preserves_alpha_and_node_mix", test_float_grade_pipeline_preserves_alpha_and_node_mix},
        {"advanced_grade_nodes_share_the_float_reference_contract", test_advanced_grade_nodes_share_the_float_reference_contract},
        {"external_lut_node_uses_ocio_and_preserves_mix_and_alpha", test_external_lut_node_uses_ocio_and_preserves_mix_and_alpha},
        {"scope_analyzer_builds_histogram_waveform_parade_and_vectorscope", test_scope_analyzer_builds_histogram_waveform_parade_and_vectorscope},
        {"oiio_probe_reports_exr_layers_alpha_and_color_space", test_oiio_probe_reports_exr_layers_alpha_and_color_space},
        {"magnetic_trim_closes_space", test_magnetic_trim_closes_space},
        {"global_frame_trim_is_atomic_magnetic_and_undoable", test_global_frame_trim_is_atomic_magnetic_and_undoable},
        {"clip_color_is_atomic_and_validated", test_clip_color_is_atomic_and_validated},
        {"dissolve_overlaps_adjacent_clips_and_is_undoable", test_dissolve_overlaps_adjacent_clips_and_is_undoable},
        {"insert_uses_overlapped_timeline_coordinates", test_insert_uses_overlapped_timeline_coordinates},
        {"snapshot_preserves_asset_audio_presence", test_snapshot_preserves_asset_audio_presence},
        {"sequence_to_source_mapping", test_sequence_to_source_mapping},
        {"vfr_frame_stepping_respects_trims_and_clip_boundaries", test_vfr_frame_stepping_respects_trims_and_clip_boundaries},
        {"trim_and_split_snap_to_vfr_frame_boundaries", test_trim_and_split_snap_to_vfr_frame_boundaries},
        {"split_preserves_duration_and_source_boundary", test_split_preserves_duration_and_source_boundary},
        {"reorder_uses_insertion_index_after_removal", test_reorder_uses_insertion_index_after_removal},
        {"duplicate_style_insert_is_magnetic_and_undoable", test_duplicate_style_insert_is_magnetic_and_undoable},
        {"time_insert_splits_once_and_is_single_step_undoable", test_time_insert_splits_once_and_is_single_step_undoable},
        {"multi_clip_delete_is_atomic_magnetic_and_undoable", test_multi_clip_delete_is_atomic_magnetic_and_undoable},
        {"multi_clip_insert_is_atomic_ordered_and_undoable", test_multi_clip_insert_is_atomic_ordered_and_undoable},
        {"multi_clip_move_preserves_order_and_skips_noop_history", test_multi_clip_move_preserves_order_and_skips_noop_history},
        {"range_delete_trims_boundaries_and_is_single_step_undoable", test_range_delete_trims_boundaries_and_is_single_step_undoable},
        {"invalid_edits_are_rejected_without_mutation", test_invalid_edits_are_rejected_without_mutation},
        {"undo_redo_covers_structural_edits", test_undo_redo_covers_structural_edits},
        {"timeline_revision_changes_only_after_successful_edits", test_timeline_revision_changes_only_after_successful_edits},
        {"asset_replacement_preserves_clips_and_validates_source_ranges", test_asset_replacement_preserves_clips_and_validates_source_ranges},
        {"clip_audio_edits_are_atomic_and_follow_split_edges", test_clip_audio_edits_are_atomic_and_follow_split_edges},
        {"playback_rate_maps_source_sequence_frames_and_captions", test_playback_rate_maps_source_sequence_frames_and_captions},
        {"caption_edits_and_ripple_mapping_share_undo_state", test_caption_edits_and_ripple_mapping_share_undo_state},
        {"srt_utf8_multiline_parse_and_serialize_roundtrip", test_srt_utf8_multiline_parse_and_serialize_roundtrip},
        {"ffprobe_timestamp_parser_preserves_vfr", test_ffprobe_timestamp_parser_preserves_vfr},
        {"ffprobe_frame_timeline_preserves_keyframes", test_ffprobe_frame_timeline_preserves_keyframes},
        {"ffmpeg_export_plan_preserves_clip_ranges_and_audio", test_ffmpeg_export_plan_preserves_clip_ranges_and_audio},
        {"ffmpeg_export_plan_applies_clip_audio_controls", test_ffmpeg_export_plan_applies_clip_audio_controls},
        {"ffmpeg_export_plan_burns_timeline_captions", test_ffmpeg_export_plan_burns_timeline_captions},
        {"ffmpeg_export_plan_applies_video_and_audio_speed", test_ffmpeg_export_plan_applies_video_and_audio_speed},
        {"ffmpeg_export_plan_rejects_invalid_requests", test_ffmpeg_export_plan_rejects_invalid_requests},
        {"ffmpeg_export_plan_uses_stream_copy_only_for_safe_keyframe_cuts", test_ffmpeg_export_plan_uses_stream_copy_only_for_safe_keyframe_cuts},
        {"ffmpeg_export_plan_applies_codec_and_quality_presets", test_ffmpeg_export_plan_applies_codec_and_quality_presets},
        {"ffmpeg_export_plan_applies_resolution_fps_and_color", test_ffmpeg_export_plan_applies_resolution_fps_and_color},
        {"ffmpeg_export_plan_compiles_video_and_audio_dissolve", test_ffmpeg_export_plan_compiles_video_and_audio_dissolve},
        {"ffmpeg_export_plan_builds_palette_optimized_gif_without_audio", test_ffmpeg_export_plan_builds_palette_optimized_gif_without_audio},
        {"render_preflight_blocks_offline_and_unresolved_managed_media", test_render_preflight_blocks_offline_and_unresolved_managed_media},
    };

    int failed = 0;
    for (const auto& [name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception& error) {
            ++failed;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - static_cast<std::size_t>(failed) << '/' << tests.size()
              << " tests passed\n";
    return failed == 0 ? 0 : 1;
}
