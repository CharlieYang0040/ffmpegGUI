#include "core/media_asset.hpp"
#include "core/ffprobe_parser.hpp"
#include "core/timeline_model.hpp"

#include <exception>
#include <filesystem>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

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

void test_ffprobe_timestamp_parser_preserves_vfr() {
    require(ffgui::parse_ffprobe_seconds("12.345678901") == 12'345'678'901, "exact decimal ns");
    const auto pts = ffgui::parse_ffprobe_frame_pts(
        "-0.100000,\r\n-0.066000\n0.000000\n0.000000\n0.200000\n");
    require(pts.size() == 4, "duplicate frame timestamps must collapse");
    require(pts[0] == 0 && pts[1] == 34'000'000, "negative start must normalize to zero");
    require(pts[2] == 100'000'000 && pts[3] == 300'000'000, "VFR gaps must remain exact");
    require(ffgui::estimated_media_end(pts) == 500'000'000, "last frame duration estimate");
}

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"vfr_frame_lookup", test_vfr_frame_lookup},
        {"magnetic_trim_closes_space", test_magnetic_trim_closes_space},
        {"sequence_to_source_mapping", test_sequence_to_source_mapping},
        {"split_preserves_duration_and_source_boundary", test_split_preserves_duration_and_source_boundary},
        {"reorder_uses_insertion_index_after_removal", test_reorder_uses_insertion_index_after_removal},
        {"invalid_edits_are_rejected_without_mutation", test_invalid_edits_are_rejected_without_mutation},
        {"undo_redo_covers_structural_edits", test_undo_redo_covers_structural_edits},
        {"ffprobe_timestamp_parser_preserves_vfr", test_ffprobe_timestamp_parser_preserves_vfr},
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
