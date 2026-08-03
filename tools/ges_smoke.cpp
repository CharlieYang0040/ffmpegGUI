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
        timeline.add_asset(MediaAsset{"asset-a", first, milliseconds(2000)});
        timeline.add_asset(MediaAsset{"asset-b", second, milliseconds(2000)});
        timeline.add_asset(MediaAsset{"asset-c", third, milliseconds(2300)});
        timeline.append_clip(Clip{"shot-a", "asset-a", milliseconds(200), milliseconds(650)});
        timeline.append_clip(Clip{"shot-b", "asset-b", milliseconds(350), milliseconds(700)});
        timeline.append_clip(Clip{"shot-vfr", "asset-c", milliseconds(300), milliseconds(900)});
        timeline.append_clip(Clip{"shot-c", "asset-a", milliseconds(1000), milliseconds(500)});

        GesSequencePlayer player;
        player.set_timeline(timeline.snapshot());
        if (player.duration() != milliseconds(2750)) {
            throw std::runtime_error("GES sequence duration does not match TimelineModel");
        }

        player.pause();
        player.seek(milliseconds(1200));
        player.play();
        wait_for_position(player, milliseconds(1450), std::chrono::seconds(8));

        player.stop();
        player.play();
        wait_for_position(player, milliseconds(2650), std::chrono::seconds(12));
        player.stop();

        std::cout << "GES continuous playback passed: 4 shots including VFR, "
                  << player.duration() / 1'000'000 << " ms\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "GES smoke failed: " << error.what() << '\n';
        return 1;
    }
}
