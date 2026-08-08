#pragma once

#include "core/media_asset.hpp"

#include <cstddef>
#include <cmath>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace ffgui {

struct ClipAudio final {
    double gain{1.0};
    bool muted{};
    TimeNs fade_in{};
    TimeNs fade_out{};

    bool operator==(const ClipAudio&) const = default;
};

struct ClipColor final {
    double brightness{};
    double contrast{1.0};
    double saturation{1.0};

    bool operator==(const ClipColor&) const = default;
};

struct Clip final {
    std::string id;
    std::string asset_id;
    TimeNs source_in{};
    TimeNs duration{};
    ClipAudio audio{};
    double playback_rate{1.0};
    ClipColor color{};

    bool operator==(const Clip&) const = default;

    [[nodiscard]] TimeNs source_out() const { return checked_add(source_in, duration); }
    [[nodiscard]] TimeNs timeline_duration() const {
        return static_cast<TimeNs>(std::llround(
            static_cast<long double>(duration) / static_cast<long double>(playback_rate)));
    }
    [[nodiscard]] TimeNs source_offset_for_timeline(TimeNs timeline_offset) const {
        return static_cast<TimeNs>(std::llround(
            static_cast<long double>(timeline_offset) *
            static_cast<long double>(playback_rate)));
    }
    [[nodiscard]] TimeNs timeline_offset_for_source(TimeNs source_offset) const {
        return static_cast<TimeNs>(std::llround(
            static_cast<long double>(source_offset) /
            static_cast<long double>(playback_rate)));
    }
};

struct TimelineSpan final {
    Clip clip;
    std::filesystem::path source_path;
    TimeNs timeline_in{};
    TimeNs timeline_out{};
    bool has_audio{};
};

struct MappedPosition final {
    std::string clip_id;
    std::string asset_id;
    TimeNs timeline_time{};
    TimeNs clip_time{};
    TimeNs source_offset{};
    TimeNs source_time{};
    std::optional<std::size_t> source_frame;
};

struct CaptionCue final {
    std::string id;
    std::string text;
    TimeNs timeline_in{};
    TimeNs duration{};

    bool operator==(const CaptionCue&) const = default;
    [[nodiscard]] TimeNs timeline_out() const { return checked_add(timeline_in, duration); }
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
    void trim_all_clip_edges(std::size_t front_frames, std::size_t back_frames);
    void move_clip(const std::string& clip_id, std::size_t insertion_index);
    void move_clips(const std::vector<std::string>& clip_ids, std::size_t insertion_index);
    void erase_clip(const std::string& clip_id);
    void erase_clips(const std::vector<std::string>& clip_ids);
    void erase_range(
        TimeNs timeline_in,
        TimeNs timeline_out,
        std::string right_remainder_id);
    void set_clips_audio(const std::vector<std::string>& clip_ids, ClipAudio audio);
    void set_clips_playback_rate(
        const std::vector<std::string>& clip_ids,
        double playback_rate);
    void set_clips_color(const std::vector<std::string>& clip_ids, ClipColor color);
    void add_caption(CaptionCue caption);
    void add_captions(std::vector<CaptionCue> captions);
    void update_caption(CaptionCue caption);
    void erase_caption(const std::string& caption_id);
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
    [[nodiscard]] const std::vector<CaptionCue>& captions() const noexcept { return captions_; }
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
    struct EditState final {
        std::vector<Clip> clips;
        std::vector<CaptionCue> captions;
    };

    [[nodiscard]] std::size_t index_of(const std::string& clip_id) const;
    [[nodiscard]] std::size_t caption_index_of(const std::string& caption_id) const;
    void validate_clip(const Clip& clip, std::optional<std::size_t> replacing = std::nullopt) const;
    void validate_caption(
        const CaptionCue& caption,
        std::optional<std::size_t> replacing = std::nullopt) const;
    void ripple_captions_for_insert(TimeNs timeline_position, TimeNs inserted_duration);
    void ripple_captions_for_delete(TimeNs timeline_in, TimeNs timeline_out);
    void record_edit();

    std::unordered_map<std::string, MediaAsset> assets_;
    std::vector<Clip> clips_;
    std::vector<CaptionCue> captions_;
    std::vector<EditState> undo_stack_;
    std::vector<EditState> redo_stack_;
    std::uint64_t revision_{};
};

}  // namespace ffgui
