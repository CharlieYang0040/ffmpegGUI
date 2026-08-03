#pragma once

#include "playback/sequence_player.hpp"

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>

typedef struct _GESPipeline GESPipeline;
typedef struct _GESTimeline GESTimeline;
typedef struct _GstElement GstElement;

namespace ffgui {

class GesSequencePlayer final : public SequencePlayer {
public:
    explicit GesSequencePlayer(
        std::string video_sink_factory = "fakesink",
        std::string audio_sink_factory = "fakesink");
    ~GesSequencePlayer() override;

    GesSequencePlayer(const GesSequencePlayer&) = delete;
    GesSequencePlayer& operator=(const GesSequencePlayer&) = delete;

    void set_timeline(std::vector<TimelineSpan> timeline) override;
    void seek(TimeNs timeline_position) override;
    void play() override;
    void pause() override;
    void stop() override;
    void set_position_callback(PositionCallback callback) override;
    void set_state_callback(StateCallback callback) override;
    void set_error_callback(ErrorCallback callback) override;
    void set_video_window_handle(std::uintptr_t window_handle);

    [[nodiscard]] TimeNs duration() const noexcept;
    [[nodiscard]] TimeNs position() const noexcept;
    [[nodiscard]] PlaybackState state() const noexcept;

private:
    void rebuild_pipeline_locked(const std::vector<TimelineSpan>& timeline);
    void destroy_pipeline_locked() noexcept;
    void notify_state(PlaybackState state_value);
    void monitor(std::stop_token stop_token);

    std::string video_sink_factory_;
    std::string audio_sink_factory_;
    mutable std::mutex mutex_;
    GESPipeline* pipeline_{};
    GESTimeline* timeline_{};
    GstElement* video_sink_{};
    std::uintptr_t video_window_handle_{};
    PositionCallback position_callback_;
    StateCallback state_callback_;
    ErrorCallback error_callback_;
    std::atomic<TimeNs> duration_ns_{0};
    std::atomic<TimeNs> position_ns_{0};
    std::atomic<PlaybackState> state_{PlaybackState::stopped};
    std::jthread monitor_thread_;
};

}  // namespace ffgui
