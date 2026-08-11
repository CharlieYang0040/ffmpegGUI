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
    const TimelineModel& timeline,
    TimeNs timeline_time,
    const ColorPipelineSettings& color_pipeline,
    const std::string& output_space) {
    const auto spans = timeline.snapshot();
    const auto active = std::ranges::find_if(
        spans | std::views::reverse, [timeline_time](const auto& span) {
            return timeline_time >= span.timeline_in && timeline_time < span.timeline_out;
        });
    if (active == spans.rend()) {
        throw std::out_of_range("timeline frame position is outside media");
    }

    const auto renderSpan = [this, &timeline, &color_pipeline, &output_space, timeline_time]
        (const TimelineSpan& span) {
        const auto* asset = timeline.asset(span.clip.asset_id);
        if (asset == nullptr || !asset->image_sequence().has_value()) {
            throw std::invalid_argument(
                "float timeline frame server currently requires an image sequence");
        }
        const auto& sequence = *asset->image_sequence();
        const auto local = std::clamp<TimeNs>(
            timeline_time - span.timeline_in, 0, span.clip.timeline_duration());
        const auto sourceTime = checked_add(
            span.clip.source_in, span.clip.source_offset_for_timeline(local));
        const auto sourceFrame = asset->frame_at_or_before(sourceTime);
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
        auto combinedGrade = compose_clip_grade(span.clip);
        auto processed = process_color_frame(
            *source, asset->source_color(), color_pipeline, combinedGrade, output_space);
        return RenderedTimelineFrame{
            std::move(source), std::move(processed), span.clip.id, asset->id(), requested,
            resolved, requested != resolved};
    };

    auto result = renderSpan(*active);
    if (active->clip.transition_in <= 0 || timeline_time >=
        checked_add(active->timeline_in, active->clip.transition_in)) {
        return result;
    }
    const auto currentIndex = static_cast<std::size_t>(
        std::distance(active, spans.rend()) - 1);
    if (currentIndex == 0) return result;
    auto previous = renderSpan(spans[currentIndex - 1]);
    if (previous.processed.width != result.processed.width ||
        previous.processed.height != result.processed.height) {
        throw std::invalid_argument("dissolve inputs must have matching dimensions");
    }
    const auto mix = std::clamp(
        static_cast<float>(timeline_time - active->timeline_in) /
            static_cast<float>(active->clip.transition_in), 0.0F, 1.0F);
    for (std::size_t index = 0; index < result.processed.rgba.size(); ++index) {
        result.processed.rgba[index] = std::lerp(
            previous.processed.rgba[index], result.processed.rgba[index], mix);
    }
    return result;
}

}  // namespace ffgui
