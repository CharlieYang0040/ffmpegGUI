#include "core/media_asset.hpp"
#include "core/timeline_model.hpp"
#include "integration/ges/ges_sequence_player.hpp"

#include <chrono>
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
        timeline.add_asset(MediaAsset{"asset-a", first, milliseconds(2000), {}, {0.5F}});
        timeline.add_asset(MediaAsset{"asset-b", second, milliseconds(2000), {}, {0.5F}});
        timeline.add_asset(MediaAsset{"asset-c", third, milliseconds(2300), {}, {0.5F}});
        auto shotA = Clip{
            "shot-a", "asset-a", milliseconds(200), milliseconds(650), {}, 2.0};
        shotA.audio = {0.8, false, milliseconds(40), milliseconds(60)};
        timeline.append_clip(std::move(shotA));
        auto shotB = Clip{"shot-b", "asset-b", milliseconds(350), milliseconds(700)};
        shotB.transition_in = milliseconds(100);
        shotB.audio.gain = 0.7;
        timeline.append_clip(std::move(shotB));
        timeline.append_clip(Clip{"shot-vfr", "asset-c", milliseconds(300), milliseconds(900)});
        timeline.append_clip(Clip{"shot-c", "asset-a", milliseconds(1000), milliseconds(500)});

        std::atomic<std::uint64_t> videoFrames{0};
        std::atomic<bool> invalidCpuFrame{false};
        GesSequencePlayer player{"cpu-appsink", "fakesink"};
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
        player.set_timeline(timeline.snapshot());
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
