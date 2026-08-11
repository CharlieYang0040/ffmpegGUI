#pragma once

#include "core/time.hpp"
#include "core/media_source.hpp"

#include <cstddef>
#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace ffgui {

class MediaAsset final {
public:
    MediaAsset(
        std::string id,
        std::filesystem::path path,
        TimeNs duration,
        std::vector<TimeNs> frame_pts = {},
        std::vector<float> audio_peaks = {},
        std::vector<TimeNs> keyframe_pts = {},
        MediaKind kind = MediaKind::video,
        std::optional<ImageSequenceDescriptor> image_sequence = std::nullopt,
        SourceColorDescriptor source_color = {},
        std::filesystem::path playback_path = {},
        std::filesystem::path export_path = {});

    [[nodiscard]] const std::string& id() const noexcept { return id_; }
    [[nodiscard]] const std::filesystem::path& path() const noexcept { return path_; }
    [[nodiscard]] const std::filesystem::path& playback_path() const noexcept {
        return playback_path_;
    }
    [[nodiscard]] const std::filesystem::path& export_path() const noexcept { return export_path_; }
    [[nodiscard]] MediaKind kind() const noexcept { return kind_; }
    [[nodiscard]] const std::optional<ImageSequenceDescriptor>& image_sequence() const noexcept {
        return image_sequence_;
    }
    [[nodiscard]] const SourceColorDescriptor& source_color() const noexcept { return source_color_; }
    void set_source_color(SourceColorDescriptor source_color) {
        source_color_ = std::move(source_color);
    }
    [[nodiscard]] TimeNs duration() const noexcept { return duration_; }
    [[nodiscard]] std::size_t frame_count() const noexcept { return frame_pts_.size(); }
    [[nodiscard]] const std::vector<TimeNs>& frame_pts() const noexcept { return frame_pts_; }
    [[nodiscard]] const std::vector<float>& audio_peaks() const noexcept { return audio_peaks_; }
    [[nodiscard]] const std::vector<TimeNs>& keyframe_pts() const noexcept { return keyframe_pts_; }

    [[nodiscard]] bool contains_range(TimeNs source_in, TimeNs range_duration) const noexcept;
    [[nodiscard]] std::optional<std::size_t> frame_at_or_before(TimeNs source_time) const noexcept;
    [[nodiscard]] std::optional<TimeNs> frame_time(std::size_t frame_index) const noexcept;
    [[nodiscard]] TimeNs nearest_frame_boundary(TimeNs source_time) const noexcept;
    [[nodiscard]] std::optional<TimeNs> previous_frame_boundary(TimeNs source_time) const noexcept;
    [[nodiscard]] std::optional<TimeNs> next_frame_boundary(TimeNs source_time) const noexcept;

private:
    std::string id_;
    std::filesystem::path path_;
    TimeNs duration_{};
    std::vector<TimeNs> frame_pts_;
    std::vector<float> audio_peaks_;
    std::vector<TimeNs> keyframe_pts_;
    MediaKind kind_{MediaKind::video};
    std::optional<ImageSequenceDescriptor> image_sequence_;
    SourceColorDescriptor source_color_;
    std::filesystem::path playback_path_;
    std::filesystem::path export_path_;
};

}  // namespace ffgui
