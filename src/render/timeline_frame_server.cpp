#include "render/timeline_frame_server.hpp"

#include <algorithm>
#include <ranges>
#include <stdexcept>

namespace ffgui {

TimelineFrameServer::TimelineFrameServer(std::size_t cache_bytes) : cache_(cache_bytes) {}

RenderedTimelineFrame TimelineFrameServer::render(
    const TimelineModel& timeline,
    TimeNs timeline_time,
    const ColorPipelineSettings& color_pipeline,
    const std::string& output_space) {
    const auto position = timeline.locate(timeline_time);
    if (!position.has_value()) throw std::out_of_range("timeline frame position is outside media");
    const auto* asset = timeline.asset(position->asset_id);
    if (asset == nullptr || !asset->image_sequence().has_value()) {
        throw std::invalid_argument("float timeline frame server currently requires an image sequence");
    }
    const auto clip = std::ranges::find(timeline.clips(), position->clip_id, &Clip::id);
    if (clip == timeline.clips().end()) throw std::logic_error("located clip is no longer available");
    const auto& sequence = *asset->image_sequence();
    const auto offset = position->source_frame.has_value()
        ? static_cast<int>(*position->source_frame)
        : static_cast<int>(std::max<TimeNs>(0, position->source_time) /
                           std::max<TimeNs>(1, sequence.frame_rate.frame_duration()));
    const auto requested = std::clamp(
        sequence.first_frame + offset, sequence.first_frame, sequence.last_frame);
    const auto resolved = sequence.has_frame(requested)
        ? requested : sequence.nearest_present_frame(requested);
    ImageFrameRequest request{
        sequence.frame_path(resolved), sequence.exr_part, sequence.channel_mapping};
    auto source = cache_.get(request);
    auto processed = process_color_frame(
        *source, asset->source_color(), color_pipeline, clip->grade, output_space);
    return RenderedTimelineFrame{
        std::move(source), std::move(processed), clip->id, asset->id(), requested, resolved,
        requested != resolved};
}

}  // namespace ffgui
