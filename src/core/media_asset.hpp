#pragma once

#include "core/time.hpp"

#include <cstddef>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace ffgui {

class MediaAsset final {
public:
    MediaAsset(
        std::string id,
        std::filesystem::path path,
        TimeNs duration,
        std::vector<TimeNs> frame_pts = {});

    [[nodiscard]] const std::string& id() const noexcept { return id_; }
    [[nodiscard]] const std::filesystem::path& path() const noexcept { return path_; }
    [[nodiscard]] TimeNs duration() const noexcept { return duration_; }
    [[nodiscard]] std::size_t frame_count() const noexcept { return frame_pts_.size(); }
    [[nodiscard]] const std::vector<TimeNs>& frame_pts() const noexcept { return frame_pts_; }

    [[nodiscard]] bool contains_range(TimeNs source_in, TimeNs range_duration) const noexcept;
    [[nodiscard]] std::optional<std::size_t> frame_at_or_before(TimeNs source_time) const noexcept;
    [[nodiscard]] std::optional<TimeNs> frame_time(std::size_t frame_index) const noexcept;

private:
    std::string id_;
    std::filesystem::path path_;
    TimeNs duration_{};
    std::vector<TimeNs> frame_pts_;
};

}  // namespace ffgui
