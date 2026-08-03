#include "core/timeline_model.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace ffgui {

void TimelineModel::add_asset(MediaAsset asset_value) {
    const auto id = asset_value.id();
    const auto [iterator, inserted] = assets_.emplace(id, std::move(asset_value));
    static_cast<void>(iterator);
    if (!inserted) {
        throw std::invalid_argument("duplicate asset id: " + id);
    }
}

const MediaAsset* TimelineModel::asset(const std::string& asset_id) const noexcept {
    const auto found = assets_.find(asset_id);
    return found == assets_.end() ? nullptr : &found->second;
}

void TimelineModel::append_clip(Clip clip) {
    insert_clip(clips_.size(), std::move(clip));
}

void TimelineModel::insert_clip(std::size_t index, Clip clip) {
    if (index > clips_.size()) {
        throw std::out_of_range("clip insertion index is outside the timeline");
    }
    validate_clip(clip);
    record_edit();
    clips_.insert(clips_.begin() + static_cast<std::ptrdiff_t>(index), std::move(clip));
}

void TimelineModel::trim_clip(const std::string& clip_id, TimeNs source_in, TimeNs range_duration) {
    const auto index = index_of(clip_id);
    Clip replacement = clips_[index];
    replacement.source_in = source_in;
    replacement.duration = range_duration;
    validate_clip(replacement, index);
    if (replacement.source_in == clips_[index].source_in &&
        replacement.duration == clips_[index].duration) {
        return;
    }
    record_edit();
    clips_[index] = std::move(replacement);
}

void TimelineModel::trim_clip_to_frame_boundaries(
    const std::string& clip_id,
    TimeNs source_in,
    TimeNs range_duration) {
    const auto index = index_of(clip_id);
    const auto& current = clips_[index];
    const auto* sourceAsset = asset(current.asset_id);
    if (sourceAsset == nullptr || !sourceAsset->contains_range(source_in, range_duration)) {
        throw std::invalid_argument("clip source range is outside the asset");
    }
    if (sourceAsset->frame_pts().empty()) {
        trim_clip(clip_id, source_in, range_duration);
        return;
    }

    const auto requestedOut = checked_add(source_in, range_duration);
    auto snappedIn = sourceAsset->nearest_frame_boundary(source_in);
    auto snappedOut = sourceAsset->nearest_frame_boundary(requestedOut);
    if (snappedOut <= snappedIn) {
        if (source_in != current.source_in) {
            const auto previous = sourceAsset->previous_frame_boundary(snappedOut);
            if (!previous.has_value()) throw std::invalid_argument("trim must keep one frame");
            snappedIn = previous.value();
        } else {
            const auto next = sourceAsset->next_frame_boundary(snappedIn);
            if (!next.has_value()) throw std::invalid_argument("trim must keep one frame");
            snappedOut = next.value();
        }
    }
    trim_clip(clip_id, snappedIn, snappedOut - snappedIn);
}

void TimelineModel::move_clip(const std::string& clip_id, std::size_t insertion_index) {
    const auto old_index = index_of(clip_id);
    if (insertion_index >= clips_.size()) {
        throw std::out_of_range("clip move index is outside the remaining timeline");
    }

    record_edit();
    Clip moving = std::move(clips_[old_index]);
    clips_.erase(clips_.begin() + static_cast<std::ptrdiff_t>(old_index));
    if (insertion_index > clips_.size()) {
        throw std::out_of_range("clip move index is outside the remaining timeline");
    }
    clips_.insert(
        clips_.begin() + static_cast<std::ptrdiff_t>(insertion_index),
        std::move(moving));
}

void TimelineModel::erase_clip(const std::string& clip_id) {
    const auto index = index_of(clip_id);
    record_edit();
    clips_.erase(clips_.begin() + static_cast<std::ptrdiff_t>(index));
}

void TimelineModel::split_at(
    TimeNs timeline_position,
    std::string left_clip_id,
    std::string right_clip_id) {
    if (left_clip_id.empty() || right_clip_id.empty() || left_clip_id == right_clip_id) {
        throw std::invalid_argument("split clip ids must be distinct and non-empty");
    }
    const auto mapped = locate(timeline_position);
    if (!mapped.has_value()) {
        throw std::out_of_range("split position is outside the timeline");
    }
    const auto index = index_of(mapped->clip_id);
    const Clip original = clips_[index];
    if (mapped->clip_time <= 0 || mapped->clip_time >= original.duration) {
        throw std::invalid_argument("split position must be inside a clip");
    }

    Clip left{std::move(left_clip_id), original.asset_id, original.source_in, mapped->clip_time};
    Clip right{
        std::move(right_clip_id),
        original.asset_id,
        checked_add(original.source_in, mapped->clip_time),
        original.duration - mapped->clip_time};

    validate_clip(left);
    validate_clip(right);
    record_edit();
    clips_[index] = std::move(left);
    clips_.insert(clips_.begin() + static_cast<std::ptrdiff_t>(index + 1), std::move(right));
}

bool TimelineModel::undo() {
    if (undo_stack_.empty()) {
        return false;
    }
    redo_stack_.push_back(std::move(clips_));
    clips_ = std::move(undo_stack_.back());
    undo_stack_.pop_back();
    ++revision_;
    return true;
}

bool TimelineModel::redo() {
    if (redo_stack_.empty()) {
        return false;
    }
    undo_stack_.push_back(std::move(clips_));
    clips_ = std::move(redo_stack_.back());
    redo_stack_.pop_back();
    ++revision_;
    return true;
}

void TimelineModel::clear_history() noexcept {
    undo_stack_.clear();
    redo_stack_.clear();
}

void TimelineModel::record_edit() {
    undo_stack_.push_back(clips_);
    redo_stack_.clear();
    ++revision_;
}

std::vector<TimelineSpan> TimelineModel::snapshot() const {
    std::vector<TimelineSpan> spans;
    spans.reserve(clips_.size());
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        const auto end = checked_add(cursor, clip.duration);
        const auto* source_asset = asset(clip.asset_id);
        if (source_asset == nullptr) {
            throw std::logic_error("timeline references a missing asset: " + clip.asset_id);
        }
        spans.push_back(TimelineSpan{clip, source_asset->path(), cursor, end});
        cursor = end;
    }
    return spans;
}

TimeNs TimelineModel::duration() const {
    TimeNs total = 0;
    for (const auto& clip : clips_) {
        total = checked_add(total, clip.duration);
    }
    return total;
}

std::optional<MappedPosition> TimelineModel::locate(TimeNs timeline_position) const {
    if (timeline_position < 0) {
        return std::nullopt;
    }
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        const auto end = checked_add(cursor, clip.duration);
        if (timeline_position < end) {
            const auto local = timeline_position - cursor;
            const auto source = checked_add(clip.source_in, local);
            const auto* source_asset = asset(clip.asset_id);
            return MappedPosition{
                clip.id,
                clip.asset_id,
                timeline_position,
                local,
                source,
                source_asset ? source_asset->frame_at_or_before(source) : std::nullopt};
        }
        cursor = end;
    }
    return std::nullopt;
}

std::optional<TimeNs> TimelineModel::timeline_time_for_source(
    const std::string& clip_id,
    TimeNs source_time) const {
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        if (clip.id == clip_id) {
            if (source_time < clip.source_in || source_time >= clip.source_out()) {
                return std::nullopt;
            }
            return checked_add(cursor, source_time - clip.source_in);
        }
        cursor = checked_add(cursor, clip.duration);
    }
    return std::nullopt;
}

std::optional<TimeNs> TimelineModel::next_frame_time(TimeNs timeline_position) const {
    const auto total = duration();
    if (clips_.empty() || timeline_position < 0 || timeline_position >= total) {
        return std::nullopt;
    }
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        const auto clipEnd = checked_add(cursor, clip.duration);
        if (timeline_position < clipEnd) {
            const auto* sourceAsset = asset(clip.asset_id);
            if (sourceAsset == nullptr) return std::nullopt;
            const auto sourceTime = checked_add(
                clip.source_in, timeline_position - cursor);
            const auto& framePts = sourceAsset->frame_pts();
            const auto next = std::upper_bound(framePts.begin(), framePts.end(), sourceTime);
            if (next != framePts.end() && *next < clip.source_out()) {
                return checked_add(cursor, *next - clip.source_in);
            }
            return clipEnd;
        }
        cursor = clipEnd;
    }
    return std::nullopt;
}

std::optional<TimeNs> TimelineModel::previous_frame_time(TimeNs timeline_position) const {
    const auto total = duration();
    if (clips_.empty() || timeline_position <= 0 || timeline_position > total) {
        return std::nullopt;
    }
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        const auto clipEnd = checked_add(cursor, clip.duration);
        if (timeline_position <= clipEnd) {
            const auto* sourceAsset = asset(clip.asset_id);
            if (sourceAsset == nullptr) return std::nullopt;
            const auto localTime = std::min(timeline_position - cursor, clip.duration);
            const auto sourceTime = checked_add(clip.source_in, localTime);
            const auto& framePts = sourceAsset->frame_pts();
            auto previous = std::lower_bound(framePts.begin(), framePts.end(), sourceTime);
            if (previous != framePts.begin()) {
                --previous;
                if (*previous >= clip.source_in) {
                    return checked_add(cursor, *previous - clip.source_in);
                }
            }
            return cursor;
        }
        cursor = clipEnd;
    }
    return std::nullopt;
}

std::optional<TimeNs> TimelineModel::nearest_frame_time(TimeNs timeline_position) const {
    if (timeline_position == duration() && !clips_.empty()) return timeline_position;
    const auto mapped = locate(timeline_position);
    if (!mapped.has_value()) return std::nullopt;
    const auto* sourceAsset = asset(mapped->asset_id);
    if (sourceAsset == nullptr || sourceAsset->frame_pts().empty()) return timeline_position;
    const auto clipIndex = index_of(mapped->clip_id);
    const auto& clip = clips_[clipIndex];
    const auto snappedSource = std::clamp(
        sourceAsset->nearest_frame_boundary(mapped->source_time),
        clip.source_in,
        clip.source_out());
    return checked_add(
        timeline_position - mapped->clip_time, snappedSource - clip.source_in);
}

std::size_t TimelineModel::index_of(const std::string& clip_id) const {
    const auto found = std::find_if(
        clips_.begin(), clips_.end(), [&clip_id](const Clip& clip) { return clip.id == clip_id; });
    if (found == clips_.end()) {
        throw std::invalid_argument("unknown clip id: " + clip_id);
    }
    return static_cast<std::size_t>(std::distance(clips_.begin(), found));
}

void TimelineModel::validate_clip(const Clip& clip, std::optional<std::size_t> replacing) const {
    if (clip.id.empty()) {
        throw std::invalid_argument("clip id must not be empty");
    }
    if (clip.asset_id.empty()) {
        throw std::invalid_argument("clip asset id must not be empty");
    }
    const auto* source_asset = asset(clip.asset_id);
    if (source_asset == nullptr) {
        throw std::invalid_argument("unknown asset id: " + clip.asset_id);
    }
    if (!source_asset->contains_range(clip.source_in, clip.duration)) {
        throw std::invalid_argument("clip source range is outside the asset");
    }
    for (std::size_t index = 0; index < clips_.size(); ++index) {
        if (replacing.has_value() && index == replacing.value()) {
            continue;
        }
        if (clips_[index].id == clip.id) {
            throw std::invalid_argument("duplicate clip id: " + clip.id);
        }
    }
}

}  // namespace ffgui
