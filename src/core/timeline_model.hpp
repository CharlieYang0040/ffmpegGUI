#pragma once

#include "core/media_asset.hpp"

#include <cstddef>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace ffgui {

struct Clip final {
    std::string id;
    std::string asset_id;
    TimeNs source_in{};
    TimeNs duration{};

    [[nodiscard]] TimeNs source_out() const { return checked_add(source_in, duration); }
};

struct TimelineSpan final {
    Clip clip;
    TimeNs timeline_in{};
    TimeNs timeline_out{};
};

struct MappedPosition final {
    std::string clip_id;
    std::string asset_id;
    TimeNs timeline_time{};
    TimeNs clip_time{};
    TimeNs source_time{};
    std::optional<std::size_t> source_frame;
};

class TimelineModel final {
public:
    void add_asset(MediaAsset asset);
    [[nodiscard]] const MediaAsset* asset(const std::string& asset_id) const noexcept;

    void append_clip(Clip clip);
    void insert_clip(std::size_t index, Clip clip);
    void trim_clip(const std::string& clip_id, TimeNs source_in, TimeNs duration);
    void move_clip(const std::string& clip_id, std::size_t insertion_index);
    void erase_clip(const std::string& clip_id);
    void split_at(
        TimeNs timeline_position,
        std::string left_clip_id,
        std::string right_clip_id);

    [[nodiscard]] const std::vector<Clip>& clips() const noexcept { return clips_; }
    [[nodiscard]] std::vector<TimelineSpan> snapshot() const;
    [[nodiscard]] TimeNs duration() const;
    [[nodiscard]] std::optional<MappedPosition> locate(TimeNs timeline_position) const;
    [[nodiscard]] std::optional<TimeNs> timeline_time_for_source(
        const std::string& clip_id,
        TimeNs source_time) const;

private:
    [[nodiscard]] std::size_t index_of(const std::string& clip_id) const;
    void validate_clip(const Clip& clip, std::optional<std::size_t> replacing = std::nullopt) const;

    std::unordered_map<std::string, MediaAsset> assets_;
    std::vector<Clip> clips_;
};

}  // namespace ffgui
