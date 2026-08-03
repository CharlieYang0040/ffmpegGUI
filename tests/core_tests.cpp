#include "core/media_asset.hpp"
#include "core/ffprobe_parser.hpp"
#include "core/timeline_model.hpp"
#include "export/ffmpeg_export_plan.hpp"

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
    request.captions = {{"첫 줄\nsecond", 500'000'000, 1'250'000'000}};
    request.subtitle_script_path = std::filesystem::path{"D:/cache/job.ass"};
    const auto plan = ffgui::compile_ffmpeg_export(request);
    require(plan.mode == ffgui::ExportMode::transcode,
            "burned captions must disable stream copy");
    std::string arguments;
    for (const auto& argument : plan.arguments) arguments += argument + '\n';
    require(arguments.contains("ass=filename='D\\:/cache/job.ass'"),
            "caption ASS file must be attached to the video graph");
    require(plan.subtitle_script.contains("Dialogue: 0,0:00:00.50,0:00:01.75"),
            "caption timestamps must retain centisecond ASS precision");
    require(plan.subtitle_script.contains("첫 줄\\Nsecond"),
            "caption text and line breaks must reach the ASS script");
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

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"vfr_frame_lookup", test_vfr_frame_lookup},
        {"magnetic_trim_closes_space", test_magnetic_trim_closes_space},
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
        {"clip_audio_edits_are_atomic_and_follow_split_edges", test_clip_audio_edits_are_atomic_and_follow_split_edges},
        {"caption_edits_and_ripple_mapping_share_undo_state", test_caption_edits_and_ripple_mapping_share_undo_state},
        {"ffprobe_timestamp_parser_preserves_vfr", test_ffprobe_timestamp_parser_preserves_vfr},
        {"ffprobe_frame_timeline_preserves_keyframes", test_ffprobe_frame_timeline_preserves_keyframes},
        {"ffmpeg_export_plan_preserves_clip_ranges_and_audio", test_ffmpeg_export_plan_preserves_clip_ranges_and_audio},
        {"ffmpeg_export_plan_applies_clip_audio_controls", test_ffmpeg_export_plan_applies_clip_audio_controls},
        {"ffmpeg_export_plan_burns_timeline_captions", test_ffmpeg_export_plan_burns_timeline_captions},
        {"ffmpeg_export_plan_rejects_invalid_requests", test_ffmpeg_export_plan_rejects_invalid_requests},
        {"ffmpeg_export_plan_uses_stream_copy_only_for_safe_keyframe_cuts", test_ffmpeg_export_plan_uses_stream_copy_only_for_safe_keyframe_cuts},
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
