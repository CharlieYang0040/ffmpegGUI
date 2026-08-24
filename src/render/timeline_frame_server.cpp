#include "render/timeline_frame_server.hpp"

#include <algorithm>
#include <cmath>
#include <ranges>
#include <stdexcept>

namespace ffgui {

GradeGraph compose_clip_grade(const Clip& clip) {
    GradeGraph combined;
    if (clip.color.brightness != 0.0 || clip.color.contrast != 1.0 ||
        clip.color.saturation != 1.0) {
        auto controls = make_default_grade_node(
            GradeNodeType::primary, "legacy-clip-controls");
        controls.name = "Clip color controls";
        controls.parameters["contrast"] = clip.color.contrast;
        controls.parameters["pivot"] = 0.5;
        controls.parameters["saturation"] = clip.color.saturation;
        controls.parameters["offsetR"] = clip.color.brightness;
        controls.parameters["offsetG"] = clip.color.brightness;
        controls.parameters["offsetB"] = clip.color.brightness;
        combined.add(std::move(controls));
    }
    for (const auto& node : clip.grade.nodes()) combined.add(node);
    return combined;
}

TimelineFrameServer::TimelineFrameServer(std::size_t cache_bytes) : cache_(cache_bytes) {}

RenderedTimelineFrame TimelineFrameServer::render(
    const Clip& clip,
    TimeNs timeline_in,
    const MediaAsset& asset,
    TimeNs timeline_time,
    const ColorPipelineSettings& color_pipeline,
    const std::string& output_space,
    ColorProcessStage stage,
    const Clip* previous_clip,
    TimeNs previous_timeline_in,
    const MediaAsset* previous_asset) {
    const auto renderClip = [this, &color_pipeline, &output_space, timeline_time, stage](
        const Clip& sourceClip, TimeNs clipIn, const MediaAsset& sourceAsset) {
        if (!sourceAsset.image_sequence().has_value()) {
            throw std::invalid_argument(
                "float timeline frame server currently requires an image sequence");
        }
        const auto& sequence = *sourceAsset.image_sequence();
        const auto local = std::clamp<TimeNs>(
            timeline_time - clipIn, 0, sourceClip.timeline_duration());
        const auto sourceTime = checked_add(
            sourceClip.source_in, sourceClip.source_offset_for_timeline(local));
        const auto sourceFrame = sourceAsset.frame_at_or_before(sourceTime);
        const auto offset = sourceFrame.has_value()
            ? static_cast<int>(*sourceFrame)
            : static_cast<int>(std::max<TimeNs>(0, sourceTime) /
                std::max<TimeNs>(1, sequence.frame_rate.frame_duration()));
        const auto requested = std::clamp(
            sequence.first_frame + offset, sequence.first_frame, sequence.last_frame);
        const auto resolved = sequence.has_frame(requested)
            ? requested : sequence.nearest_present_frame(requested);
        auto source = cache_.get(ImageFrameRequest{
            sequence.frame_path(resolved), sequence.exr_part,
            sequence.channel_mapping, sequence.exr_view});
        auto combinedGrade = compose_clip_grade(sourceClip);
        auto processed = process_color_frame(
            *source, sourceAsset.source_color(), color_pipeline, combinedGrade, output_space,
            sourceTime, stage);
        if (sourceClip.video_muted) {
            for (std::size_t index = 0; index + 3 < processed.rgba.size(); index += 4) {
                processed.rgba[index] = 0.0F;
                processed.rgba[index + 1] = 0.0F;
                processed.rgba[index + 2] = 0.0F;
            }
        }
        return RenderedTimelineFrame{
            std::move(source), std::move(processed), sourceClip.id, sourceAsset.id(), requested,
            resolved, requested != resolved};
    };

    auto result = renderClip(clip, timeline_in, asset);
    if (previous_clip == nullptr || previous_asset == nullptr || clip.transition_in <= 0 ||
        timeline_time >= checked_add(timeline_in, clip.transition_in)) {
        return result;
    }
    auto previous = renderClip(*previous_clip, previous_timeline_in, *previous_asset);
    if (previous.processed.width != result.processed.width ||
        previous.processed.height != result.processed.height) {
        throw std::invalid_argument("dissolve inputs must have matching dimensions");
    }
    const auto mix = std::clamp(
        static_cast<float>(timeline_time - timeline_in) /
            static_cast<float>(clip.transition_in), 0.0F, 1.0F);
    for (std::size_t index = 0; index < result.processed.rgba.size(); ++index) {
        result.processed.rgba[index] = std::lerp(
            previous.processed.rgba[index], result.processed.rgba[index], mix);
    }
    return result;
}

RenderedTimelineFrame TimelineFrameServer::render(
    const TimelineModel& timeline,
    TimeNs timeline_time,
    const ColorPipelineSettings& color_pipeline,
    const std::string& output_space,
    ColorProcessStage stage) {
    TimeNs cursor = 0;
    const Clip* matched = nullptr;
    TimeNs matchedIn = 0;
    std::size_t matchedIndex = 0;
    const auto& clips = timeline.clips();
    for (std::size_t index = 0; index < clips.size(); ++index) {
        const auto& clip = clips[index];
        if (index > 0) cursor -= clip.transition_in;
        const auto end = checked_add(cursor, clip.timeline_duration());
        if (timeline_time >= cursor && timeline_time < end) {
            matched = &clip;
            matchedIn = cursor;
            matchedIndex = index;
        }
        cursor = end;
    }
    if (matched == nullptr) {
        throw std::out_of_range("timeline frame position is outside media");
    }
    const auto* asset = timeline.asset(matched->asset_id);
    if (asset == nullptr) {
        throw std::invalid_argument(
            "float timeline frame server currently requires an image sequence");
    }
    const Clip* previousClip = nullptr;
    const MediaAsset* previousAsset = nullptr;
    TimeNs previousIn = 0;
    if (matched->transition_in > 0 && matchedIndex > 0 &&
        timeline_time < checked_add(matchedIn, matched->transition_in)) {
        previousClip = &clips[matchedIndex - 1];
        previousAsset = timeline.asset(previousClip->asset_id);
        previousIn = matchedIn + matched->transition_in - previousClip->timeline_duration();
    }
    return render(
        *matched, matchedIn, *asset, timeline_time, color_pipeline, output_space, stage,
        previousClip, previousIn, previousAsset);
}

}  // namespace ffgui
