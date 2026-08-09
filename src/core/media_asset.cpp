#include "core/media_asset.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace ffgui {

MediaAsset::MediaAsset(
    std::string id,
    std::filesystem::path path,
    TimeNs duration,
    std::vector<TimeNs> frame_pts,
    std::vector<float> audio_peaks,
    std::vector<TimeNs> keyframe_pts,
    MediaKind kind,
    std::optional<ImageSequenceDescriptor> image_sequence,
    SourceColorDescriptor source_color,
    std::filesystem::path playback_path,
    std::filesystem::path export_path)
    : id_(std::move(id)),
      path_(std::move(path)),
      duration_(duration),
      frame_pts_(std::move(frame_pts)),
      audio_peaks_(std::move(audio_peaks)),
      keyframe_pts_(std::move(keyframe_pts)),
      kind_(kind),
      image_sequence_(std::move(image_sequence)),
      source_color_(std::move(source_color)),
      playback_path_(playback_path.empty() ? path_ : std::move(playback_path)),
      export_path_(export_path.empty() ? path_ : std::move(export_path)) {
    if (id_.empty()) {
        throw std::invalid_argument("asset id must not be empty");
    }
    if (path_.empty()) {
        throw std::invalid_argument("asset path must not be empty");
    }
    if (duration_ <= 0) {
        throw std::invalid_argument("asset duration must be positive");
    }
    if (kind_ == MediaKind::image_sequence && !image_sequence_.has_value()) {
        throw std::invalid_argument("image sequence asset requires a descriptor");
    }
    if (!frame_pts_.empty()) {
        if (frame_pts_.front() != 0) {
            throw std::invalid_argument("frame timestamps must be normalized to zero");
        }
        if (!std::is_sorted(frame_pts_.begin(), frame_pts_.end())) {
            throw std::invalid_argument("frame timestamps must be sorted");
        }
        if (std::adjacent_find(frame_pts_.begin(), frame_pts_.end()) != frame_pts_.end()) {
            throw std::invalid_argument("frame timestamps must be strictly increasing");
        }
        if (frame_pts_.back() >= duration_) {
            throw std::invalid_argument("frame timestamps must be inside asset duration");
        }
    }
    if (std::any_of(audio_peaks_.begin(), audio_peaks_.end(), [](float peak) {
            return peak < 0.0F || peak > 1.0F;
        })) {
        throw std::invalid_argument("audio peaks must be normalized between zero and one");
    }
    if (!std::is_sorted(keyframe_pts_.begin(), keyframe_pts_.end()) ||
        std::adjacent_find(keyframe_pts_.begin(), keyframe_pts_.end()) != keyframe_pts_.end() ||
        std::any_of(keyframe_pts_.begin(), keyframe_pts_.end(), [this](TimeNs pts) {
            return pts < 0 || pts >= duration_ ||
                   !std::binary_search(frame_pts_.begin(), frame_pts_.end(), pts);
        })) {
        throw std::invalid_argument("keyframe timestamps must be unique source frame timestamps");
    }
}

bool MediaAsset::contains_range(TimeNs source_in, TimeNs range_duration) const noexcept {
    return source_in >= 0 && range_duration > 0 && source_in < duration_ &&
           range_duration <= duration_ - source_in;
}

std::optional<std::size_t> MediaAsset::frame_at_or_before(TimeNs source_time) const noexcept {
    if (frame_pts_.empty() || source_time < 0 || source_time >= duration_) {
        return std::nullopt;
    }
    const auto after = std::upper_bound(frame_pts_.begin(), frame_pts_.end(), source_time);
    if (after == frame_pts_.begin()) {
        return std::nullopt;
    }
    return static_cast<std::size_t>(std::distance(frame_pts_.begin(), after) - 1);
}

std::optional<TimeNs> MediaAsset::frame_time(std::size_t frame_index) const noexcept {
    if (frame_index >= frame_pts_.size()) {
        return std::nullopt;
    }
    return frame_pts_[frame_index];
}

TimeNs MediaAsset::nearest_frame_boundary(TimeNs source_time) const noexcept {
    source_time = std::clamp(source_time, TimeNs{0}, duration_);
    if (frame_pts_.empty() || source_time == duration_) return source_time;
    const auto next = std::lower_bound(frame_pts_.begin(), frame_pts_.end(), source_time);
    if (next != frame_pts_.end() && *next == source_time) return source_time;
    const auto nextTime = next != frame_pts_.end() ? *next : duration_;
    const auto previousTime = next != frame_pts_.begin() ? *std::prev(next) : TimeNs{0};
    return source_time - previousTime <= nextTime - source_time ? previousTime : nextTime;
}

std::optional<TimeNs> MediaAsset::previous_frame_boundary(TimeNs source_time) const noexcept {
    if (source_time <= 0) return std::nullopt;
    source_time = std::min(source_time, duration_);
    const auto previous = std::lower_bound(frame_pts_.begin(), frame_pts_.end(), source_time);
    if (previous == frame_pts_.begin()) return TimeNs{0};
    return *std::prev(previous);
}

std::optional<TimeNs> MediaAsset::next_frame_boundary(TimeNs source_time) const noexcept {
    if (source_time < 0) return TimeNs{0};
    if (source_time >= duration_) return std::nullopt;
    const auto next = std::upper_bound(frame_pts_.begin(), frame_pts_.end(), source_time);
    return next != frame_pts_.end() ? *next : duration_;
}

}  // namespace ffgui
