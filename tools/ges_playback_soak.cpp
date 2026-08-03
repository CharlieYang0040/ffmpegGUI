#include "core/media_asset.hpp"
#include "core/timeline_model.hpp"
#include "integration/ges/ges_sequence_player.hpp"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#include <Psapi.h>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
using ffgui::Clip;
using ffgui::D3D11VideoFrame;
using ffgui::GesSequencePlayer;
using ffgui::MediaAsset;
using ffgui::TimeNs;
using ffgui::TimelineModel;

constexpr TimeNs milliseconds(TimeNs value) { return value * 1'000'000; }

struct Probe final {
    std::mutex mutex;
    std::condition_variable changed;
    std::uint64_t serial{};
    TimeNs pts{};
    std::string error;
};

std::uint64_t private_bytes() {
    PROCESS_MEMORY_COUNTERS_EX counters{};
    counters.cb = sizeof(counters);
    if (!GetProcessMemoryInfo(
            GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),
            sizeof(counters))) {
        throw std::runtime_error("GetProcessMemoryInfo failed");
    }
    return counters.PrivateUsage;
}

std::vector<ffgui::TimelineSpan> make_timeline(
    const std::filesystem::path& h264,
    const std::filesystem::path& hevc) {
    TimelineModel timeline;
    timeline.add_asset(MediaAsset{"h264", h264, milliseconds(4000)});
    timeline.add_asset(MediaAsset{"hevc", hevc, milliseconds(4000)});
    timeline.append_clip(Clip{"shot-h264", "h264", 0, milliseconds(4000)});
    timeline.append_clip(Clip{"shot-hevc", "hevc", 0, milliseconds(4000)});
    return timeline.snapshot();
}

TimeNs target_for_cycle(std::uint64_t cycle) {
    if (cycle % 12 == 0) return milliseconds(3950);
    if (cycle % 12 == 1) return milliseconds(4050);
    const auto mixed = cycle * 2'654'435'761ULL + 1'013'904'223ULL;
    return milliseconds(200 + static_cast<TimeNs>(mixed % 7'600));
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        if (argc != 4) {
            throw std::invalid_argument(
                "usage: ffgui_ges_playback_soak <4k-h264> <4k-hevc> <seconds>");
        }
        const auto h264 = std::filesystem::absolute(argv[1]);
        const auto hevc = std::filesystem::absolute(argv[2]);
        if (!std::filesystem::is_regular_file(h264) ||
            !std::filesystem::is_regular_file(hevc)) {
            throw std::invalid_argument("both 4K soak media files must exist");
        }
        const auto seconds = std::max(10, std::stoi(argv[3]));
        const auto spans = make_timeline(h264, hevc);

        Probe probe;
        GesSequencePlayer player{"appsink", "fakesink"};
        player.set_video_frame_callback([&probe](D3D11VideoFrame frame) {
            {
                std::scoped_lock lock(probe.mutex);
                probe.serial = frame.serial;
                probe.pts = frame.pts;
            }
            probe.changed.notify_all();
        });
        player.set_error_callback([&probe](std::string message) {
            {
                std::scoped_lock lock(probe.mutex);
                probe.error = std::move(message);
            }
            probe.changed.notify_all();
        });
        player.set_timeline(spans);

        const auto deadline = Clock::now() + std::chrono::seconds(seconds);
        std::uint64_t cycle = 0;
        std::uint64_t memoryBaseline = 0;
        double maximumLatency = 0.0;
        while (Clock::now() < deadline) {
            if (cycle > 0 && cycle % 25 == 0) {
                player.stop();
                player.set_timeline(spans);
            } else {
                player.pause();
            }

            const auto target = target_for_cycle(cycle);
            std::uint64_t previousSerial = 0;
            {
                std::scoped_lock lock(probe.mutex);
                previousSerial = probe.serial;
                if (!probe.error.empty()) {
                    throw std::runtime_error("GStreamer error: " + probe.error);
                }
            }
            const auto started = Clock::now();
            player.seek(target);
            player.play();
            {
                std::unique_lock lock(probe.mutex);
                const auto received = probe.changed.wait_for(lock, std::chrono::seconds(3), [&] {
                    return !probe.error.empty() ||
                        (probe.serial > previousSerial &&
                         probe.pts >= target - milliseconds(100) &&
                         probe.pts <= target + milliseconds(500));
                });
                if (!received) {
                    throw std::runtime_error(
                        "timed out at cycle " + std::to_string(cycle) + ", target " +
                        std::to_string(target) + " ns, last PTS " +
                        std::to_string(probe.pts) + " ns, serial " +
                        std::to_string(probe.serial));
                }
                if (!probe.error.empty()) {
                    throw std::runtime_error("GStreamer error: " + probe.error);
                }
            }
            const auto latency = std::chrono::duration<double, std::milli>(
                Clock::now() - started).count();
            maximumLatency = std::max(maximumLatency, latency);
            if (latency >= 2500.0) {
                throw std::runtime_error("single seek latency exceeded 2500 ms");
            }
            ++cycle;
            if (cycle == 5) memoryBaseline = private_bytes();
        }

        player.stop();
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        const auto memoryFinal = private_bytes();
        const auto memoryGrowth = memoryFinal > memoryBaseline
            ? memoryFinal - memoryBaseline
            : 0;
        constexpr std::uint64_t memoryBudget = 128ULL * 1024ULL * 1024ULL;
        if (cycle < 10) throw std::runtime_error("soak completed too few seek cycles");
        if (memoryGrowth > memoryBudget) {
            throw std::runtime_error(
                "private memory grew by " + std::to_string(memoryGrowth / 1024 / 1024) +
                " MiB, exceeding the 128 MiB budget");
        }

        std::cout << "4K playback soak passed: " << cycle << " PTS-matched seeks in "
                  << seconds << " s, max latency " << maximumLatency << " ms, private growth "
                  << static_cast<double>(memoryGrowth) / 1024.0 / 1024.0 << " MiB\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "4K playback soak failed: " << error.what() << '\n';
        return 1;
    }
}
