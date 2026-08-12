#include "core/media_asset.hpp"
#include "core/timeline_model.hpp"
#include "integration/ges/ges_sequence_player.hpp"
#include "integration/ges/gst_color_lut_filter.hpp"
#include "integration/ges/gst_d3d11_color_lut_filter.hpp"
#include "color/color_frame_processor.hpp"

#include <gst/app/gstappsink.h>
#include <gst/gst.h>

#include <chrono>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <atomic>

namespace {

using ffgui::Clip;
using ffgui::GesSequencePlayer;
using ffgui::MediaAsset;
using ffgui::TimeNs;
using ffgui::TimelineModel;

constexpr TimeNs milliseconds(TimeNs value) {
    return value * 1'000'000;
}

void wait_for_position(
    const GesSequencePlayer& player,
    TimeNs minimum,
    std::chrono::steady_clock::duration timeout) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (player.position() >= minimum) {
            return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    throw std::runtime_error(
        "playback timeout at " + std::to_string(player.position()) +
        " ns; expected at least " + std::to_string(minimum));
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        if (argc != 4) {
            throw std::invalid_argument("usage: ffgui_ges_smoke <mp4> <mkv> <vfr-mkv>");
        }
        const auto first = std::filesystem::absolute(argv[1]);
        const auto second = std::filesystem::absolute(argv[2]);
        const auto third = std::filesystem::absolute(argv[3]);
        if (!std::filesystem::is_regular_file(first) ||
            !std::filesystem::is_regular_file(second) ||
            !std::filesystem::is_regular_file(third)) {
            throw std::invalid_argument("all smoke-test media files must exist");
        }

        TimelineModel timeline;
        ffgui::SourceColorDescriptor rec709;
        rec709.input_color_space = "Camera Rec.709";
        timeline.add_asset(MediaAsset{
            "asset-a", first, milliseconds(2000), {}, {0.5F}, {}, ffgui::MediaKind::video,
            std::nullopt, rec709});
        timeline.add_asset(MediaAsset{
            "asset-b", second, milliseconds(2000), {}, {0.5F}, {}, ffgui::MediaKind::video,
            std::nullopt, rec709});
        timeline.add_asset(MediaAsset{
            "asset-c", third, milliseconds(2300), {}, {0.5F}, {}, ffgui::MediaKind::video,
            std::nullopt, rec709});
        auto shotA = Clip{
            "shot-a", "asset-a", milliseconds(200), milliseconds(650), {}, 2.0};
        shotA.audio = {0.8, false, milliseconds(40), milliseconds(60)};
        shotA.color = {0.08, 1.1, 0.9};
        timeline.append_clip(std::move(shotA));
        auto shotB = Clip{"shot-b", "asset-b", milliseconds(350), milliseconds(700)};
        shotB.transition_in = milliseconds(100);
        shotB.audio.gain = 0.7;
        auto shotBGrade = ffgui::make_default_grade_node(
            ffgui::GradeNodeType::primary, "shot-b-primary");
        shotBGrade.parameters["exposure"] = 0.25;
        shotB.grade.add(std::move(shotBGrade));
        timeline.append_clip(std::move(shotB));
        timeline.append_clip(Clip{"shot-vfr", "asset-c", milliseconds(300), milliseconds(900)});
        timeline.append_clip(Clip{"shot-c", "asset-a", milliseconds(1000), milliseconds(500)});

        const bool expectGpuColor = g_getenv("FFGUI_FORCE_CPU_COLOR") == nullptr;
        std::atomic<std::uint64_t> videoFrames{0};
        std::atomic<std::uint64_t> scopeFrames{0};
        std::atomic<bool> invalidCpuFrame{false};
        std::atomic<bool> invalidScopeFrame{false};
        GesSequencePlayer player{"cpu-appsink", "fakesink"};
        player.set_scope_frame_callback([&](ffgui::PreviewVideoFrame frame) {
            if (frame.cpu_format != ffgui::PreviewCpuFormat::bgra8 ||
                frame.cpu_pixels == nullptr || frame.width != 1280 || frame.height != 720 ||
                frame.cpu_stride != frame.width * 4) {
                invalidScopeFrame.store(true);
                return;
            }
            scopeFrames.fetch_add(1);
        });
        auto solidRed = std::make_shared<ffgui::ColorCube>();
        solidRed->size = 2;
        solidRed->rgb.resize(2 * 2 * 2 * 3);
        for (std::size_t index = 0; index < solidRed->rgb.size(); index += 3) {
            solidRed->rgb[index] = 1.0F;
        }
        ffgui::publish_gst_color_lut("smoke-red", solidRed);
        GError* lutPipelineError = nullptr;
        auto* lutPipeline = gst_parse_launch(
            "videotestsrc num-buffers=1 pattern=solid-color foreground-color=0x80000000 ! "
            "videoconvert ! "
            "video/x-raw,format=RGBA64_LE,width=8,height=8 ! "
            "ffguilut3d lut-id=smoke-red ! appsink name=luttestsink sync=false",
            &lutPipelineError);
        if (lutPipeline == nullptr) {
            const std::string message =
                lutPipelineError != nullptr && lutPipelineError->message != nullptr
                ? lutPipelineError->message : "unknown parse error";
            if (lutPipelineError != nullptr) g_error_free(lutPipelineError);
            throw std::runtime_error("color LUT filter pipeline failed: " + message);
        }
        auto* lutSink = gst_bin_get_by_name(GST_BIN(lutPipeline), "luttestsink");
        gst_element_set_state(lutPipeline, GST_STATE_PLAYING);
        auto* lutSample = gst_app_sink_try_pull_sample(
            GST_APP_SINK(lutSink), 5 * GST_SECOND);
        GstMapInfo lutMap{};
        const auto mapped = lutSample != nullptr && gst_buffer_map(
            gst_sample_get_buffer(lutSample), &lutMap, GST_MAP_READ);
        const auto* lutPixel = mapped
            ? reinterpret_cast<const std::uint16_t*>(lutMap.data) : nullptr;
        const auto validLutPixel = lutPixel != nullptr &&
            lutPixel[0] > 65'000 && lutPixel[1] < 100 && lutPixel[2] < 100 &&
            lutPixel[3] > 32'000 && lutPixel[3] < 33'000;
        if (mapped) gst_buffer_unmap(gst_sample_get_buffer(lutSample), &lutMap);
        if (lutSample != nullptr) gst_sample_unref(lutSample);
        gst_element_set_state(lutPipeline, GST_STATE_NULL);
        gst_object_unref(lutSink);
        gst_object_unref(lutPipeline);
        if (!validLutPixel) {
            throw std::runtime_error(
                "color LUT filter did not transform straight-alpha RGBA64 pixels");
        }
        GError* gpuLutPipelineError = nullptr;
        auto* gpuLutPipeline = gst_parse_launch(
            "videotestsrc num-buffers=1 pattern=solid-color foreground-color=0x80000000 ! "
            "d3d11upload ! "
            "video/x-raw(memory:D3D11Memory),format=RGBA64_LE,width=8,height=8 ! "
            "ffguilut3d11 lut-id=smoke-red ! d3d11download ! "
            "video/x-raw,format=RGBA64_LE ! appsink name=gputestsink sync=false",
            &gpuLutPipelineError);
        if (gpuLutPipeline == nullptr) {
            const std::string message = gpuLutPipelineError != nullptr &&
                    gpuLutPipelineError->message != nullptr
                ? gpuLutPipelineError->message : "unknown parse error";
            if (gpuLutPipelineError != nullptr) g_error_free(gpuLutPipelineError);
            throw std::runtime_error("D3D11 color LUT filter pipeline failed: " + message);
        }
        auto* gpuLutSink = gst_bin_get_by_name(GST_BIN(gpuLutPipeline), "gputestsink");
        gst_element_set_state(gpuLutPipeline, GST_STATE_PLAYING);
        auto* gpuLutSample = gst_app_sink_try_pull_sample(
            GST_APP_SINK(gpuLutSink), 5 * GST_SECOND);
        GstMapInfo gpuLutMap{};
        const auto gpuMapped = gpuLutSample != nullptr && gst_buffer_map(
            gst_sample_get_buffer(gpuLutSample), &gpuLutMap, GST_MAP_READ);
        const auto* gpuLutPixel = gpuMapped
            ? reinterpret_cast<const std::uint16_t*>(gpuLutMap.data) : nullptr;
        const std::array<std::uint16_t, 4> gpuLutValues{
            static_cast<std::uint16_t>(gpuLutPixel == nullptr ? 0 : gpuLutPixel[0]),
            static_cast<std::uint16_t>(gpuLutPixel == nullptr ? 0 : gpuLutPixel[1]),
            static_cast<std::uint16_t>(gpuLutPixel == nullptr ? 0 : gpuLutPixel[2]),
            static_cast<std::uint16_t>(gpuLutPixel == nullptr ? 0 : gpuLutPixel[3])};
        const auto validGpuLutPixel = gpuLutPixel != nullptr &&
            gpuLutPixel[0] > 65'000 && gpuLutPixel[1] < 100 && gpuLutPixel[2] < 100 &&
            gpuLutPixel[3] > 32'000 && gpuLutPixel[3] < 33'000;
        if (gpuMapped) {
            gst_buffer_unmap(gst_sample_get_buffer(gpuLutSample), &gpuLutMap);
        }
        if (gpuLutSample != nullptr) gst_sample_unref(gpuLutSample);
        gst_element_set_state(gpuLutPipeline, GST_STATE_NULL);
        gst_object_unref(gpuLutSink);
        gst_object_unref(gpuLutPipeline);
        ffgui::remove_gst_color_lut("smoke-red");
        if (!validGpuLutPixel) {
            throw std::runtime_error("D3D11 color LUT filter pixel mismatch: " +
                (gpuLutPixel == nullptr ? std::string{"no pixel"} :
                    std::to_string(gpuLutValues[0]) + "," +
                    std::to_string(gpuLutValues[1]) + "," +
                    std::to_string(gpuLutValues[2]) + "," +
                    std::to_string(gpuLutValues[3])));
        }

        ffgui::ColorPipelineSettings ocioSettings;
        ocioSettings.mode = ffgui::ColorPipelineMode::aces_managed;
        ocioSettings.working_space = "ACEScg";
        ffgui::SourceColorDescriptor appleLog;
        appleLog.input_color_space = "Apple Log";
        ffgui::GradeGraph gpuGrade;
        auto gpuPrimary = ffgui::make_default_grade_node(
            ffgui::GradeNodeType::primary, "gpu-smoke-primary");
        gpuPrimary.parameters["exposure"] = 0.25;
        gpuGrade.add(std::move(gpuPrimary));
        auto exactShader = std::make_shared<const ffgui::OcioGpuShader>(
            ffgui::build_managed_gpu_shader(
                appleLog, ocioSettings, gpuGrade, "sRGB - Display"));
        if (exactShader->textures.size() < 2) {
            throw std::runtime_error(
                "managed GPU smoke requires OCIO and creative grade textures");
        }
        ffgui::publish_gst_d3d11_ocio_shader("smoke-ocio", exactShader);
        GError* ocioPipelineError = nullptr;
        auto* ocioPipeline = gst_parse_launch(
            "videotestsrc num-buffers=1 pattern=solid-color foreground-color=0x80808080 ! "
            "d3d11upload ! "
            "video/x-raw(memory:D3D11Memory),format=RGBA64_LE,width=8,height=8 ! "
            "ffguilut3d11 shader-id=smoke-ocio ! d3d11download ! "
            "video/x-raw,format=RGBA64_LE ! appsink name=ociotestsink sync=false",
            &ocioPipelineError);
        if (ocioPipeline == nullptr) {
            const std::string message = ocioPipelineError != nullptr &&
                    ocioPipelineError->message != nullptr
                ? ocioPipelineError->message : "unknown parse error";
            if (ocioPipelineError != nullptr) g_error_free(ocioPipelineError);
            ffgui::remove_gst_d3d11_ocio_shader("smoke-ocio");
            throw std::runtime_error("D3D11 exact OCIO pipeline failed: " + message);
        }
        auto* ocioSink = gst_bin_get_by_name(GST_BIN(ocioPipeline), "ociotestsink");
        gst_element_set_state(ocioPipeline, GST_STATE_PLAYING);
        auto* ocioSample = gst_app_sink_try_pull_sample(
            GST_APP_SINK(ocioSink), 5 * GST_SECOND);
        GstMapInfo ocioMap{};
        const auto ocioMapped = ocioSample != nullptr && gst_buffer_map(
            gst_sample_get_buffer(ocioSample), &ocioMap, GST_MAP_READ);
        const auto* ocioPixel = ocioMapped
            ? reinterpret_cast<const std::uint16_t*>(ocioMap.data) : nullptr;
        ffgui::FloatImageFrame referenceFrame;
        referenceFrame.width = 1;
        referenceFrame.height = 1;
        referenceFrame.color_space = "Apple Log";
        referenceFrame.rgba = {128.0F / 255.0F, 128.0F / 255.0F,
                               128.0F / 255.0F, 128.0F / 255.0F};
        const auto reference = ffgui::process_color_frame(
            referenceFrame, appleLog, ocioSettings, gpuGrade, "sRGB - Display");
        bool validOcioPixel = ocioPixel != nullptr;
        for (std::size_t channel = 0; channel < 3 && validOcioPixel; ++channel) {
            const auto expected = static_cast<int>(std::lround(
                std::clamp(reference.rgba[channel], 0.0F, 1.0F) * 65535.0F));
            // The creative stage is intentionally a 33^3 trilinear cube; exact OCIO input
            // and output transforms surround it. Keep the acceptance bound below 1.6%.
            validOcioPixel = std::abs(static_cast<int>(ocioPixel[channel]) - expected) <= 1'024;
        }
        validOcioPixel = validOcioPixel &&
            std::abs(static_cast<int>(ocioPixel[3]) - 32'896) <= 300;
        std::array<std::uint16_t, 4> ocioValues{};
        if (ocioPixel != nullptr) std::copy_n(ocioPixel, 4, ocioValues.begin());
        if (ocioMapped) gst_buffer_unmap(gst_sample_get_buffer(ocioSample), &ocioMap);
        if (ocioSample != nullptr) gst_sample_unref(ocioSample);
        gst_element_set_state(ocioPipeline, GST_STATE_NULL);
        gst_object_unref(ocioSink);
        gst_object_unref(ocioPipeline);
        ffgui::remove_gst_d3d11_ocio_shader("smoke-ocio");
        if (!validOcioPixel) {
            throw std::runtime_error(
                "D3D11 exact OCIO shader did not match the CPU processor: " +
                std::to_string(ocioValues[0]) + "," + std::to_string(ocioValues[1]) + "," +
                std::to_string(ocioValues[2]) + "," + std::to_string(ocioValues[3]) +
                " expected " + std::to_string(reference.rgba[0]) + "," +
                std::to_string(reference.rgba[1]) + "," +
                std::to_string(reference.rgba[2]));
        }
        player.set_video_frame_callback([&](ffgui::PreviewVideoFrame frame) {
            if (frame.cpu_pixels == nullptr || frame.width != 1280 || frame.height != 720 ||
                frame.cpu_stride != frame.width * 4 ||
                frame.cpu_pixels->size() !=
                    static_cast<std::size_t>(frame.cpu_stride) * frame.height) {
                invalidCpuFrame.store(true);
            }
            videoFrames.fetch_add(1);
        });
        player.set_timeline(timeline.snapshot());
        if (player.duration() != milliseconds(2325)) {
            throw std::runtime_error("GES sequence duration does not match TimelineModel");
        }
        if (player.source_automation_bindings() != 3) {
            throw std::runtime_error(
                "GES source alpha/volume automation was not attached to every edited clip");
        }
        if (player.source_color_lut_bindings() != 1) {
            throw std::runtime_error("legacy GradeGraph LUT was not attached before composition");
        }
        if (player.source_gpu_color_lut_bindings() != (expectGpuColor ? 1 : 0)) {
            throw std::runtime_error("legacy GradeGraph LUT did not use the D3D11 source shader");
        }

        player.seek(milliseconds(1200));
        player.play();
        wait_for_position(player, milliseconds(1450), std::chrono::seconds(8));

        player.pause();
        player.seek(milliseconds(300));
        player.play();
        wait_for_position(player, milliseconds(550), std::chrono::seconds(8));

        player.stop();
        player.reset_audio_continuity_metrics();
        player.play();
        wait_for_position(player, milliseconds(2225), std::chrono::seconds(12));
        player.stop();

        const auto audio = player.audio_continuity_metrics();
        if (audio.buffer_count < 20) {
            throw std::runtime_error("GES audio continuity probe received too few buffers");
        }
        if (audio.maximum_positive_gap > milliseconds(2)) {
            throw std::runtime_error(
                "GES audio gap exceeded 2 ms: " +
                std::to_string(audio.maximum_positive_gap) + " ns");
        }
        if (invalidCpuFrame.load() || videoFrames.load() < 20) {
            throw std::runtime_error(
                "CPU appsink did not deliver enough valid 1280x720 BGRA frames: " +
                std::to_string(videoFrames.load()));
        }
        if (invalidScopeFrame.load() || scopeFrames.load() < 5) {
            throw std::runtime_error(
                "scope callback did not deliver enough valid post-display frames: " +
                std::to_string(scopeFrames.load()));
        }

        std::atomic<std::uint64_t> floatFrames{0};
        std::atomic<bool> invalidFloatFrame{false};
        player.set_video_frame_callback([&](ffgui::PreviewVideoFrame frame) {
            if (frame.cpu_format != ffgui::PreviewCpuFormat::rgba16le ||
                frame.cpu_pixels == nullptr || frame.width != 640 || frame.height != 360 ||
                frame.cpu_stride != frame.width * 8 ||
                frame.cpu_pixels->size() !=
                    static_cast<std::size_t>(frame.cpu_stride) * frame.height) {
                invalidFloatFrame.store(true);
            }
            floatFrames.fetch_add(1);
        });
        player.set_float_output_enabled(true);
        ffgui::ColorPipelineSettings managedColor;
        managedColor.mode = ffgui::ColorPipelineMode::aces_managed;
        managedColor.working_space = "ACEScg";
        managedColor.output_space = "sRGB - Display";
        player.set_color_pipeline(managedColor, managedColor.output_space);
        player.set_timeline(timeline.snapshot());
        if (player.source_color_lut_bindings() != 4) {
            throw std::runtime_error("managed color LUT was not attached to every source clip");
        }
        if (player.source_gpu_color_lut_bindings() != (expectGpuColor ? 4 : 0)) {
            throw std::runtime_error("managed color LUT did not use every D3D11 source shader");
        }
        if (player.source_gpu_ocio_shader_bindings() != (expectGpuColor ? 4 : 0)) {
            throw std::runtime_error(
                "managed sources did not use exact OCIO D3D11 transforms");
        }
        player.seek(milliseconds(300));
        player.play();
        const auto floatDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
        while (floatFrames.load() < 2 && std::chrono::steady_clock::now() < floatDeadline) {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        player.stop();
        if (invalidFloatFrame.load() || floatFrames.load() < 2) {
            throw std::runtime_error(
                "float appsink did not deliver valid 640x360 RGBA16 frames: " +
                std::to_string(floatFrames.load()));
        }

        std::cout << "GES continuous playback passed: 4 shots with source-alpha dissolve, "
                     "audio gain/fades, VFR and 2x speed, "
                  << player.duration() / 1'000'000 << " ms; "
                  << audio.buffer_count << " audio buffers, max gap "
                  << audio.maximum_positive_gap << " ns; "
                  << videoFrames.load() << " CPU BGRA frames and "
                  << floatFrames.load() << " RGBA16 frames\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "GES smoke failed: " << error.what() << '\n';
        return 1;
    }
}
