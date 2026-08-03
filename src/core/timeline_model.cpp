#include "core/timeline_model.hpp"

#include <algorithm>
#include <iterator>
#include <stdexcept>
#include <unordered_set>
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
    TimeNs insertionTime = 0;
    for (std::size_t candidate = 0; candidate < index; ++candidate) {
        insertionTime = checked_add(insertionTime, clips_[candidate].duration);
    }
    record_edit();
    ripple_captions_for_insert(insertionTime, clip.duration);
    clips_.insert(clips_.begin() + static_cast<std::ptrdiff_t>(index), std::move(clip));
}

void TimelineModel::insert_clips(std::size_t index, std::vector<Clip> clips) {
    if (index > clips_.size()) {
        throw std::out_of_range("clip insertion index is outside the timeline");
    }
    if (clips.empty()) return;
    std::unordered_set<std::string> batchIds;
    for (const auto& clip : clips) {
        validate_clip(clip);
        if (!batchIds.insert(clip.id).second) {
            throw std::invalid_argument("duplicate clip id in insertion batch: " + clip.id);
        }
    }
    TimeNs insertionTime = 0;
    for (std::size_t candidate = 0; candidate < index; ++candidate) {
        insertionTime = checked_add(insertionTime, clips_[candidate].duration);
    }
    TimeNs insertedDuration = 0;
    for (const auto& clip : clips) insertedDuration = checked_add(insertedDuration, clip.duration);
    record_edit();
    ripple_captions_for_insert(insertionTime, insertedDuration);
    clips_.insert(
        clips_.begin() + static_cast<std::ptrdiff_t>(index),
        std::make_move_iterator(clips.begin()),
        std::make_move_iterator(clips.end()));
}

void TimelineModel::insert_clip_at(
    TimeNs timeline_position,
    Clip clip,
    std::string left_clip_id,
    std::string right_clip_id) {
    const auto total = duration();
    if (timeline_position < 0 || timeline_position > total) {
        throw std::out_of_range("clip insertion time is outside the timeline");
    }
    validate_clip(clip);

    TimeNs cursor = 0;
    for (std::size_t index = 0; index < clips_.size(); ++index) {
        const auto clipEnd = checked_add(cursor, clips_[index].duration);
        if (timeline_position == cursor) {
            record_edit();
            ripple_captions_for_insert(timeline_position, clip.duration);
            clips_.insert(clips_.begin() + static_cast<std::ptrdiff_t>(index), std::move(clip));
            return;
        }
        if (timeline_position < clipEnd) {
            const auto& original = clips_[index];
            if (left_clip_id.empty() || right_clip_id.empty() ||
                left_clip_id == right_clip_id || left_clip_id == clip.id ||
                right_clip_id == clip.id) {
                throw std::invalid_argument("insert split ids must be distinct and non-empty");
            }
            const auto idExists = [this, index](const std::string& id) {
                for (std::size_t candidate = 0; candidate < clips_.size(); ++candidate) {
                    if (candidate != index && clips_[candidate].id == id) return true;
                }
                return false;
            };
            if (idExists(left_clip_id) || idExists(right_clip_id)) {
                throw std::invalid_argument("insert split id already exists");
            }

            const auto local = timeline_position - cursor;
            auto left = original;
            left.id = std::move(left_clip_id);
            left.duration = local;
            left.audio.fade_out = 0;
            auto right = original;
            right.id = std::move(right_clip_id);
            right.source_in = checked_add(original.source_in, local);
            right.duration = original.duration - local;
            right.audio.fade_in = 0;
            validate_clip(left, index);
            validate_clip(right, index);
            record_edit();
            ripple_captions_for_insert(timeline_position, clip.duration);
            clips_[index] = std::move(left);
            clips_.insert(
                clips_.begin() + static_cast<std::ptrdiff_t>(index + 1), std::move(clip));
            clips_.insert(
                clips_.begin() + static_cast<std::ptrdiff_t>(index + 2), std::move(right));
            return;
        }
        cursor = clipEnd;
    }

    record_edit();
    ripple_captions_for_insert(timeline_position, clip.duration);
    clips_.push_back(std::move(clip));
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
    TimeNs clipStart = 0;
    for (std::size_t candidate = 0; candidate < index; ++candidate) {
        clipStart = checked_add(clipStart, clips_[candidate].duration);
    }
    const auto oldDuration = clips_[index].duration;
    record_edit();
    if (range_duration < oldDuration) {
        ripple_captions_for_delete(
            checked_add(clipStart, range_duration), checked_add(clipStart, oldDuration));
    } else if (range_duration > oldDuration) {
        ripple_captions_for_insert(checked_add(clipStart, oldDuration), range_duration - oldDuration);
    }
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
    move_clips({clip_id}, insertion_index);
}

void TimelineModel::move_clips(
    const std::vector<std::string>& clip_ids,
    std::size_t insertion_index) {
    if (clip_ids.empty()) return;
    const std::unordered_set<std::string> selected(clip_ids.begin(), clip_ids.end());
    if (selected.size() != clip_ids.size()) {
        throw std::invalid_argument("clip move selection contains duplicate ids");
    }
    for (const auto& id : selected) static_cast<void>(index_of(id));

    std::vector<Clip> moving;
    std::vector<Clip> remaining;
    moving.reserve(selected.size());
    remaining.reserve(clips_.size() - selected.size());
    for (const auto& clip : clips_) {
        (selected.contains(clip.id) ? moving : remaining).push_back(clip);
    }
    if (insertion_index > remaining.size()) {
        throw std::out_of_range("clip move index is outside the remaining timeline");
    }
    remaining.insert(
        remaining.begin() + static_cast<std::ptrdiff_t>(insertion_index),
        moving.begin(),
        moving.end());
    if (remaining == clips_) return;
    record_edit();
    clips_ = std::move(remaining);
}

void TimelineModel::erase_clip(const std::string& clip_id) {
    const auto index = index_of(clip_id);
    TimeNs timelineIn = 0;
    for (std::size_t candidate = 0; candidate < index; ++candidate) {
        timelineIn = checked_add(timelineIn, clips_[candidate].duration);
    }
    record_edit();
    ripple_captions_for_delete(timelineIn, checked_add(timelineIn, clips_[index].duration));
    clips_.erase(clips_.begin() + static_cast<std::ptrdiff_t>(index));
}

void TimelineModel::erase_clips(const std::vector<std::string>& clip_ids) {
    if (clip_ids.empty()) return;
    const std::unordered_set<std::string> uniqueIds(clip_ids.begin(), clip_ids.end());
    for (const auto& id : uniqueIds) {
        static_cast<void>(index_of(id));
    }
    std::vector<std::pair<TimeNs, TimeNs>> ranges;
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        const auto end = checked_add(cursor, clip.duration);
        if (uniqueIds.contains(clip.id)) ranges.emplace_back(cursor, end);
        cursor = end;
    }
    record_edit();
    for (auto iterator = ranges.rbegin(); iterator != ranges.rend(); ++iterator) {
        ripple_captions_for_delete(iterator->first, iterator->second);
    }
    std::erase_if(clips_, [&uniqueIds](const Clip& clip) {
        return uniqueIds.contains(clip.id);
    });
}

void TimelineModel::erase_range(
    TimeNs timeline_in,
    TimeNs timeline_out,
    std::string right_remainder_id) {
    const auto total = duration();
    if (timeline_in < 0 || timeline_out > total || timeline_in >= timeline_out) {
        throw std::invalid_argument("timeline removal range is invalid");
    }

    std::vector<Clip> candidate;
    candidate.reserve(clips_.size() + 1);
    TimeNs cursor = 0;
    for (const auto& clip : clips_) {
        const auto clipEnd = checked_add(cursor, clip.duration);
        if (clipEnd <= timeline_in || cursor >= timeline_out) {
            candidate.push_back(clip);
            cursor = clipEnd;
            continue;
        }

        const auto leftDuration = timeline_in > cursor ? timeline_in - cursor : TimeNs{0};
        const auto rightDuration = timeline_out < clipEnd ? clipEnd - timeline_out : TimeNs{0};
        if (leftDuration > 0) {
            auto left = clip;
            left.duration = leftDuration;
            left.audio.fade_out = 0;
            candidate.push_back(std::move(left));
        }
        if (rightDuration > 0) {
            auto right = clip;
            right.source_in = checked_add(clip.source_in, clip.duration - rightDuration);
            right.duration = rightDuration;
            right.audio.fade_in = 0;
            if (leftDuration > 0) {
                if (right_remainder_id.empty()) {
                    throw std::invalid_argument("range split remainder id must not be empty");
                }
                right.id = std::move(right_remainder_id);
            }
            candidate.push_back(std::move(right));
        }
        cursor = clipEnd;
    }

    std::unordered_set<std::string> ids;
    for (const auto& clip : candidate) {
        if (!ids.insert(clip.id).second) {
            throw std::invalid_argument("range removal produced a duplicate clip id");
        }
        const auto* sourceAsset = asset(clip.asset_id);
        if (sourceAsset == nullptr || !sourceAsset->contains_range(clip.source_in, clip.duration)) {
            throw std::invalid_argument("range removal produced an invalid source range");
        }
    }
    record_edit();
    ripple_captions_for_delete(timeline_in, timeline_out);
    clips_ = std::move(candidate);
}

void TimelineModel::add_caption(CaptionCue caption) {
    add_captions({std::move(caption)});
}

void TimelineModel::add_captions(std::vector<CaptionCue> captions) {
    if (captions.empty()) return;
    std::unordered_set<std::string> batchIds;
    for (const auto& caption : captions) {
        validate_caption(caption);
        if (!batchIds.insert(caption.id).second) {
            throw std::invalid_argument("duplicate caption id in insertion batch: " + caption.id);
        }
    }
    record_edit();
    captions_.insert(
        captions_.end(),
        std::make_move_iterator(captions.begin()),
        std::make_move_iterator(captions.end()));
    std::ranges::sort(captions_, {}, &CaptionCue::timeline_in);
}

void TimelineModel::update_caption(CaptionCue caption) {
    const auto index = caption_index_of(caption.id);
    validate_caption(caption, index);
    if (captions_[index] == caption) return;
    record_edit();
    captions_[index] = std::move(caption);
    std::ranges::sort(captions_, {}, &CaptionCue::timeline_in);
}

void TimelineModel::erase_caption(const std::string& caption_id) {
    const auto index = caption_index_of(caption_id);
    record_edit();
    captions_.erase(captions_.begin() + static_cast<std::ptrdiff_t>(index));
}

void TimelineModel::set_clips_audio(
    const std::vector<std::string>& clip_ids,
    ClipAudio audio) {
    if (clip_ids.empty()) return;
    if (!std::isfinite(audio.gain) || audio.gain < 0.0 || audio.gain > 4.0 ||
        audio.fade_in < 0 || audio.fade_out < 0) {
        throw std::invalid_argument("clip audio settings are invalid");
    }
    const std::unordered_set<std::string> uniqueIds(clip_ids.begin(), clip_ids.end());
    if (uniqueIds.size() != clip_ids.size()) {
        throw std::invalid_argument("clip audio selection contains duplicate ids");
    }
    bool changed = false;
    for (const auto& id : uniqueIds) {
        const auto index = index_of(id);
        changed = changed || clips_[index].audio != audio;
    }
    if (!changed) return;
    record_edit();
    for (auto& clip : clips_) {
        if (uniqueIds.contains(clip.id)) clip.audio = audio;
    }
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

    auto left = original;
    left.id = std::move(left_clip_id);
    left.duration = mapped->clip_time;
    left.audio.fade_out = 0;
    auto right = original;
    right.id = std::move(right_clip_id);
    right.source_in = checked_add(original.source_in, mapped->clip_time);
    right.duration = original.duration - mapped->clip_time;
    right.audio.fade_in = 0;

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
    redo_stack_.push_back(EditState{std::move(clips_), std::move(captions_)});
    clips_ = std::move(undo_stack_.back().clips);
    captions_ = std::move(undo_stack_.back().captions);
    undo_stack_.pop_back();
    ++revision_;
    return true;
}

bool TimelineModel::redo() {
    if (redo_stack_.empty()) {
        return false;
    }
    undo_stack_.push_back(EditState{std::move(clips_), std::move(captions_)});
    clips_ = std::move(redo_stack_.back().clips);
    captions_ = std::move(redo_stack_.back().captions);
    redo_stack_.pop_back();
    ++revision_;
    return true;
}

void TimelineModel::clear_history() noexcept {
    undo_stack_.clear();
    redo_stack_.clear();
}

void TimelineModel::record_edit() {
    undo_stack_.push_back(EditState{clips_, captions_});
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

std::size_t TimelineModel::caption_index_of(const std::string& caption_id) const {
    const auto found = std::ranges::find(captions_, caption_id, &CaptionCue::id);
    if (found == captions_.end()) {
        throw std::invalid_argument("unknown caption id: " + caption_id);
    }
    return static_cast<std::size_t>(std::distance(captions_.begin(), found));
}

void TimelineModel::validate_caption(
    const CaptionCue& caption,
    std::optional<std::size_t> replacing) const {
    if (caption.id.empty() || caption.text.empty() || caption.timeline_in < 0 ||
        caption.duration <= 0 || caption.timeline_out() > duration()) {
        throw std::invalid_argument("caption is outside the timeline or empty");
    }
    for (std::size_t index = 0; index < captions_.size(); ++index) {
        if ((!replacing.has_value() || replacing.value() != index) &&
            captions_[index].id == caption.id) {
            throw std::invalid_argument("duplicate caption id: " + caption.id);
        }
    }
}

void TimelineModel::ripple_captions_for_insert(
    TimeNs timeline_position,
    TimeNs inserted_duration) {
    if (inserted_duration <= 0) return;
    for (auto& caption : captions_) {
        if (caption.timeline_in >= timeline_position) {
            caption.timeline_in = checked_add(caption.timeline_in, inserted_duration);
        }
    }
}

void TimelineModel::ripple_captions_for_delete(TimeNs timeline_in, TimeNs timeline_out) {
    const auto removed = timeline_out - timeline_in;
    std::vector<CaptionCue> transformed;
    transformed.reserve(captions_.size());
    for (auto caption : captions_) {
        const auto captionOut = caption.timeline_out();
        if (captionOut <= timeline_in) {
            transformed.push_back(std::move(caption));
        } else if (caption.timeline_in >= timeline_out) {
            caption.timeline_in -= removed;
            transformed.push_back(std::move(caption));
        } else if (caption.timeline_in < timeline_in && captionOut > timeline_out) {
            caption.duration -= removed;
            transformed.push_back(std::move(caption));
        } else if (caption.timeline_in < timeline_in) {
            caption.duration = timeline_in - caption.timeline_in;
            if (caption.duration > 0) transformed.push_back(std::move(caption));
        } else if (captionOut > timeline_out) {
            caption.timeline_in = timeline_in;
            caption.duration = captionOut - timeline_out;
            if (caption.duration > 0) transformed.push_back(std::move(caption));
        }
    }
    captions_ = std::move(transformed);
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
    if (!std::isfinite(clip.audio.gain) || clip.audio.gain < 0.0 || clip.audio.gain > 4.0 ||
        clip.audio.fade_in < 0 || clip.audio.fade_out < 0) {
        throw std::invalid_argument("clip audio settings are invalid");
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
