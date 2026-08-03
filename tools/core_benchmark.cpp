#include "core/media_asset.hpp"
#include "core/timeline_model.hpp"

#include <chrono>
#include <filesystem>
#include <iostream>
#include <string>

int main() {
    using Clock = std::chrono::steady_clock;
    using namespace ffgui;

    TimelineModel timeline;
    timeline.add_asset(MediaAsset{
        "asset", std::filesystem::path{"benchmark.mp4"}, 3'600 * kNanosecondsPerSecond});

    constexpr std::size_t clipCount = 1000;
    constexpr TimeNs clipDuration = 2 * kNanosecondsPerSecond;
    for (std::size_t index = 0; index < clipCount; ++index) {
        timeline.append_clip(Clip{
            "clip-" + std::to_string(index),
            "asset",
            static_cast<TimeNs>(index) * clipDuration,
            clipDuration});
    }

    constexpr int iterations = 1000;
    const auto started = Clock::now();
    std::size_t consumed = 0;
    for (int iteration = 0; iteration < iterations; ++iteration) {
        consumed += timeline.snapshot().size();
    }
    const auto elapsed = std::chrono::duration<double, std::milli>(Clock::now() - started).count();
    const auto average = elapsed / iterations;

    std::cout << "1000-clip snapshot average: " << average << " ms ("
              << consumed << " spans consumed)\n";
    return average < 16.67 ? 0 : 1;
}
