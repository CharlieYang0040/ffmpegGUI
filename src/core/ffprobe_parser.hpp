#pragma once

#include "core/time.hpp"

#include <string_view>
#include <vector>

namespace ffgui {

struct ParsedFrameTimeline final {
    std::vector<TimeNs> frame_pts;
    std::vector<TimeNs> keyframe_pts;
};

[[nodiscard]] TimeNs parse_ffprobe_seconds(std::string_view value);
[[nodiscard]] std::vector<TimeNs> parse_ffprobe_frame_pts(std::string_view output);
[[nodiscard]] ParsedFrameTimeline parse_ffprobe_frame_timeline(std::string_view output);
[[nodiscard]] TimeNs estimated_media_end(const std::vector<TimeNs>& frame_pts);

}  // namespace ffgui
