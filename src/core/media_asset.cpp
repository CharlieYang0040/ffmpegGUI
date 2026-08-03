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
    std::vector<float> audio_peaks)
    : id_(std::move(id)),
      path_(std::move(path)),
      duration_(duration),
      frame_pts_(std::move(frame_pts)),
      audio_peaks_(std::move(audio_peaks)) {
    if (id_.empty()) {
        throw std::invalid_argument("asset id must not be empty");
    }
    if (path_.empty()) {
        throw std::invalid_argument("asset path must not be empty");
    }
    if (duration_ <= 0) {
        throw std::invalid_argument("asset duration must be positive");
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

}  // namespace ffgui
