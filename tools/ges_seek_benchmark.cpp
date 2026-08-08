#include "core/media_asset.hpp"
#include "core/timeline_model.hpp"
#include "integration/ges/ges_sequence_player.hpp"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
using ffgui::Clip;
using ffgui::PreviewVideoFrame;
using ffgui::GesSequencePlayer;
using ffgui::MediaAsset;
using ffgui::TimeNs;
using ffgui::TimelineModel;

constexpr TimeNs milliseconds(TimeNs value) { return value * 1'000'000; }

struct FrameProbe final {
    std::mutex mutex;
    std::condition_variable changed;
    std::uint64_t serial{};
    std::uint32_t width{};
    std::uint32_t height{};
    TimeNs pts{};
};

double benchmark_file(const std::filesystem::path& path) {
    TimelineModel timeline;
    timeline.add_asset(MediaAsset{"asset", path, milliseconds(4000)});
    timeline.append_clip(Clip{"clip", "asset", 0, milliseconds(4000)});

    FrameProbe probe;
    GesSequencePlayer player{"appsink", "fakesink"};
    player.set_video_frame_callback([&probe](PreviewVideoFrame frame) {
        {
            std::scoped_lock lock(probe.mutex);
            probe.serial = frame.serial;
            probe.width = frame.width;
            probe.height = frame.height;
            probe.pts = frame.pts;
        }
        probe.changed.notify_all();
    });
    player.set_timeline(timeline.snapshot());

    const std::vector<TimeNs> targets{
        milliseconds(250), milliseconds(3250), milliseconds(750), milliseconds(2750),
        milliseconds(1250), milliseconds(2250), milliseconds(1750), milliseconds(3500)};
    std::vector<double> latencies;
    latencies.reserve(targets.size());
    for (const auto target : targets) {
        player.pause();
        std::uint64_t previousSerial = 0;
        {
            std::scoped_lock lock(probe.mutex);
            previousSerial = probe.serial;
        }
        const auto started = Clock::now();
        player.seek(target);
        player.play();
        {
            std::unique_lock lock(probe.mutex);
            if (!probe.changed.wait_for(lock, std::chrono::seconds(3), [&] {
                    return probe.serial > previousSerial &&
                        probe.pts >= target - milliseconds(100) &&
                        probe.pts <= target + milliseconds(500);
                })) {
                throw std::runtime_error(
                    "timed out waiting for a decoded D3D11 frame near the seek target");
            }
            if (probe.width == 0 || probe.height == 0) {
                throw std::runtime_error("decoded D3D11 frame has an invalid size");
            }
        }
        latencies.push_back(std::chrono::duration<double, std::milli>(
            Clock::now() - started).count());
    }
    player.stop();

    std::sort(latencies.begin(), latencies.end());
    const auto median = latencies[latencies.size() / 2];
    const auto maximum = latencies.back();
    std::cout << path.filename().string() << ": median " << median << " ms, max "
              << maximum << " ms across " << latencies.size() << " seeks; preview "
              << probe.width << "x" << probe.height << "\n";
    if (median >= 750.0 || maximum >= 2000.0) {
        throw std::runtime_error("4K seek latency exceeded the development budget");
    }
    return median;
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        if (argc != 3) {
            throw std::invalid_argument("usage: ffgui_ges_seek_benchmark <4k-h264> <4k-hevc>");
        }
        for (int index = 1; index < argc; ++index) {
            if (!std::filesystem::is_regular_file(argv[index])) {
                throw std::invalid_argument("benchmark media file does not exist");
            }
            benchmark_file(std::filesystem::absolute(argv[index]));
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "4K seek benchmark failed: " << error.what() << '\n';
        return 1;
    }
}
