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
    std::filesystem::path source_path;
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
    [[nodiscard]] const std::unordered_map<std::string, MediaAsset>& assets() const noexcept {
        return assets_;
    }

    void append_clip(Clip clip);
    void insert_clip(std::size_t index, Clip clip);
    void insert_clips(std::size_t index, std::vector<Clip> clips);
    void insert_clip_at(
        TimeNs timeline_position,
        Clip clip,
        std::string left_clip_id,
        std::string right_clip_id);
    void trim_clip(const std::string& clip_id, TimeNs source_in, TimeNs duration);
    void trim_clip_to_frame_boundaries(
        const std::string& clip_id, TimeNs source_in, TimeNs duration);
    void move_clip(const std::string& clip_id, std::size_t insertion_index);
    void erase_clip(const std::string& clip_id);
    void erase_clips(const std::vector<std::string>& clip_ids);
    void split_at(
        TimeNs timeline_position,
        std::string left_clip_id,
        std::string right_clip_id);
    [[nodiscard]] bool can_undo() const noexcept { return !undo_stack_.empty(); }
    [[nodiscard]] bool can_redo() const noexcept { return !redo_stack_.empty(); }
    bool undo();
    bool redo();
    void clear_history() noexcept;

    [[nodiscard]] const std::vector<Clip>& clips() const noexcept { return clips_; }
    [[nodiscard]] std::vector<TimelineSpan> snapshot() const;
    [[nodiscard]] TimeNs duration() const;
    [[nodiscard]] std::uint64_t revision() const noexcept { return revision_; }
    [[nodiscard]] std::optional<MappedPosition> locate(TimeNs timeline_position) const;
    [[nodiscard]] std::optional<TimeNs> next_frame_time(TimeNs timeline_position) const;
    [[nodiscard]] std::optional<TimeNs> previous_frame_time(TimeNs timeline_position) const;
    [[nodiscard]] std::optional<TimeNs> nearest_frame_time(TimeNs timeline_position) const;
    [[nodiscard]] std::optional<TimeNs> timeline_time_for_source(
        const std::string& clip_id,
        TimeNs source_time) const;

private:
    [[nodiscard]] std::size_t index_of(const std::string& clip_id) const;
    void validate_clip(const Clip& clip, std::optional<std::size_t> replacing = std::nullopt) const;
    void record_edit();

    std::unordered_map<std::string, MediaAsset> assets_;
    std::vector<Clip> clips_;
    std::vector<std::vector<Clip>> undo_stack_;
    std::vector<std::vector<Clip>> redo_stack_;
    std::uint64_t revision_{};
};

}  // namespace ffgui
