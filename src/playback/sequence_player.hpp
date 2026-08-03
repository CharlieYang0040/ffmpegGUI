#pragma once

#include "core/timeline_model.hpp"

#include <functional>
#include <vector>

namespace ffgui {

enum class PlaybackState {
    stopped,
    paused,
    playing,
};

class SequencePlayer {
public:
    using PositionCallback = std::function<void(TimeNs)>;
    using StateCallback = std::function<void(PlaybackState)>;

    virtual ~SequencePlayer() = default;
    virtual void set_timeline(std::vector<TimelineSpan> timeline) = 0;
    virtual void seek(TimeNs timeline_position) = 0;
    virtual void play() = 0;
    virtual void pause() = 0;
    virtual void stop() = 0;
    virtual void set_position_callback(PositionCallback callback) = 0;
    virtual void set_state_callback(StateCallback callback) = 0;
};

}  // namespace ffgui
