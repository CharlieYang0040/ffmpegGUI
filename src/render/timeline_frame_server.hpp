#pragma once

#include "color/color_frame_processor.hpp"
#include "core/timeline_model.hpp"
#include "media/oiio_frame_source.hpp"

#include <memory>
#include <string>

namespace ffgui {

[[nodiscard]] GradeGraph compose_clip_grade(const Clip& clip);

struct RenderedTimelineFrame final {
    std::shared_ptr<const FloatImageFrame> source;
    FloatImageFrame processed;
    std::string clip_id;
    std::string asset_id;
    int requested_sequence_frame{};
    int resolved_sequence_frame{};
    bool substituted_missing_frame{};
};

class TimelineFrameServer final {
public:
    explicit TimelineFrameServer(std::size_t cache_bytes = 512ULL * 1024ULL * 1024ULL);

    [[nodiscard]] RenderedTimelineFrame render(
        const TimelineModel& timeline,
        TimeNs timeline_time,
        const ColorPipelineSettings& color_pipeline,
        const std::string& output_space,
        ColorProcessStage stage = ColorProcessStage::post_display);

    [[nodiscard]] RenderedTimelineFrame render(
        const Clip& clip,
        TimeNs timeline_in,
        const MediaAsset& asset,
        TimeNs timeline_time,
        const ColorPipelineSettings& color_pipeline,
        const std::string& output_space,
        ColorProcessStage stage = ColorProcessStage::post_display,
        const Clip* previous_clip = nullptr,
        TimeNs previous_timeline_in = 0,
        const MediaAsset* previous_asset = nullptr);

    void invalidate(const std::filesystem::path& path) { cache_.invalidate(path); }
    void clear() { cache_.clear(); }
    [[nodiscard]] std::size_t cache_bytes() const noexcept { return cache_.byte_size(); }

private:
    ImageFrameCache cache_;
};

}  // namespace ffgui
