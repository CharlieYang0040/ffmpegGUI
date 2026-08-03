#include "integration/ges/ges_sequence_player.hpp"

#include <ges/ges.h>
#include <gst/gst.h>
#include <gst/video/videooverlay.h>

#include <chrono>
#include <limits>
#include <stdexcept>
#include <utility>

namespace ffgui {
namespace {

std::string path_to_utf8(const std::filesystem::path& path) {
    const auto value = path.u8string();
    return {reinterpret_cast<const char*>(value.data()), value.size()};
}

std::runtime_error glib_error(const std::string& prefix, GError* error) {
    std::string message = prefix;
    if (error != nullptr && error->message != nullptr) {
        message += ": ";
        message += error->message;
        g_error_free(error);
    }
    return std::runtime_error(message);
}

void require_ges(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

}  // namespace

GesSequencePlayer::GesSequencePlayer(
    std::string video_sink_factory,
    std::string audio_sink_factory)
    : video_sink_factory_(std::move(video_sink_factory)),
      audio_sink_factory_(std::move(audio_sink_factory)) {
    gst_init(nullptr, nullptr);
    if (!ges_init()) {
        throw std::runtime_error("failed to initialize GStreamer Editing Services");
    }
    monitor_thread_ = std::jthread([this](std::stop_token token) { monitor(token); });
}

GesSequencePlayer::~GesSequencePlayer() {
    monitor_thread_.request_stop();
    if (monitor_thread_.joinable()) {
        monitor_thread_.join();
    }
    std::scoped_lock lock(mutex_);
    destroy_pipeline_locked();
}

void GesSequencePlayer::set_timeline(std::vector<TimelineSpan> timeline) {
    {
        std::scoped_lock lock(mutex_);
        rebuild_pipeline_locked(timeline);
    }
    position_ns_.store(0);
    state_.store(PlaybackState::stopped);
    notify_state(PlaybackState::stopped);
}

void GesSequencePlayer::seek(TimeNs timeline_position) {
    const auto target = std::max<TimeNs>(0, std::min(timeline_position, duration_ns_.load()));
    std::scoped_lock lock(mutex_);
    if (pipeline_ == nullptr) {
        return;
    }
    const auto flags = static_cast<GstSeekFlags>(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_ACCURATE);
    if (!gst_element_seek_simple(GST_ELEMENT(pipeline_), GST_FORMAT_TIME, flags, target)) {
        throw std::runtime_error("GES timeline seek failed");
    }
    position_ns_.store(target);
}

void GesSequencePlayer::play() {
    {
        std::scoped_lock lock(mutex_);
        if (pipeline_ == nullptr) {
            return;
        }
        const auto result = gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_PLAYING);
        if (result == GST_STATE_CHANGE_FAILURE) {
            throw std::runtime_error("GES pipeline failed to start playback");
        }
    }
    state_.store(PlaybackState::playing);
    notify_state(PlaybackState::playing);
}

void GesSequencePlayer::pause() {
    {
        std::scoped_lock lock(mutex_);
        if (pipeline_ == nullptr) {
            return;
        }
        const auto result = gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_PAUSED);
        if (result == GST_STATE_CHANGE_FAILURE) {
            throw std::runtime_error("GES pipeline failed to pause");
        }
    }
    state_.store(PlaybackState::paused);
    notify_state(PlaybackState::paused);
}

void GesSequencePlayer::stop() {
    {
        std::scoped_lock lock(mutex_);
        if (pipeline_ == nullptr) {
            return;
        }
        gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_READY);
    }
    position_ns_.store(0);
    state_.store(PlaybackState::stopped);
    notify_state(PlaybackState::stopped);
}

void GesSequencePlayer::set_position_callback(PositionCallback callback) {
    std::scoped_lock lock(mutex_);
    position_callback_ = std::move(callback);
}

void GesSequencePlayer::set_state_callback(StateCallback callback) {
    std::scoped_lock lock(mutex_);
    state_callback_ = std::move(callback);
}

void GesSequencePlayer::set_error_callback(ErrorCallback callback) {
    std::scoped_lock lock(mutex_);
    error_callback_ = std::move(callback);
}

void GesSequencePlayer::set_video_window_handle(std::uintptr_t window_handle) {
    std::scoped_lock lock(mutex_);
    video_window_handle_ = window_handle;
    if (video_sink_ != nullptr && GST_IS_VIDEO_OVERLAY(video_sink_)) {
        gst_video_overlay_set_window_handle(
            GST_VIDEO_OVERLAY(video_sink_),
            static_cast<guintptr>(video_window_handle_));
    }
}

TimeNs GesSequencePlayer::duration() const noexcept {
    return duration_ns_.load();
}

TimeNs GesSequencePlayer::position() const noexcept {
    return position_ns_.load();
}

PlaybackState GesSequencePlayer::state() const noexcept {
    return state_.load();
}

void GesSequencePlayer::reset_audio_continuity_metrics() noexcept {
    audio_buffer_count_.store(0);
    audio_last_end_ns_.store(-1);
    audio_maximum_gap_ns_.store(0);
}

AudioContinuityMetrics GesSequencePlayer::audio_continuity_metrics() const noexcept {
    return AudioContinuityMetrics{audio_buffer_count_.load(), audio_maximum_gap_ns_.load()};
}

void GesSequencePlayer::audio_handoff(GstElement*, GstBuffer* buffer, GstPad*, void* user_data) {
    auto* player = static_cast<GesSequencePlayer*>(user_data);
    if (player == nullptr || buffer == nullptr || !GST_BUFFER_PTS_IS_VALID(buffer)) return;
    const auto pts = static_cast<TimeNs>(GST_BUFFER_PTS(buffer));
    const auto duration = GST_BUFFER_DURATION_IS_VALID(buffer)
        ? static_cast<TimeNs>(GST_BUFFER_DURATION(buffer))
        : 0;
    const auto end = duration <= std::numeric_limits<TimeNs>::max() - pts
        ? pts + duration
        : std::numeric_limits<TimeNs>::max();
    const auto previousEnd = player->audio_last_end_ns_.exchange(end);
    player->audio_buffer_count_.fetch_add(1);
    if (previousEnd < 0 || pts <= previousEnd) return;
    const auto gap = pts - previousEnd;
    auto maximum = player->audio_maximum_gap_ns_.load();
    while (gap > maximum &&
           !player->audio_maximum_gap_ns_.compare_exchange_weak(maximum, gap)) {
    }
}

void GesSequencePlayer::rebuild_pipeline_locked(const std::vector<TimelineSpan>& spans) {
    destroy_pipeline_locked();
    if (spans.empty()) {
        duration_ns_.store(0);
        return;
    }

    auto* new_timeline = ges_timeline_new_audio_video();
    auto* layer = ges_layer_new();
    if (new_timeline == nullptr || layer == nullptr) {
        if (new_timeline != nullptr) {
            gst_object_unref(new_timeline);
        }
        if (layer != nullptr) {
            gst_object_unref(layer);
        }
        throw std::runtime_error("failed to create GES timeline");
    }
    gst_object_ref_sink(new_timeline);
    if (!ges_timeline_add_layer(new_timeline, layer)) {
        gst_object_unref(layer);
        gst_object_unref(new_timeline);
        throw std::runtime_error("failed to add GES layer");
    }

    try {
        for (const auto& span : spans) {
            GError* error = nullptr;
            const auto path = path_to_utf8(span.source_path);
            gchar* uri = gst_filename_to_uri(path.c_str(), &error);
            if (uri == nullptr) {
                throw glib_error("failed to convert media path to URI", error);
            }
            auto* uri_clip = ges_uri_clip_new(uri);
            g_free(uri);
            if (uri_clip == nullptr) {
                throw std::runtime_error("failed to create GES URI clip");
            }

            auto* element = GES_TIMELINE_ELEMENT(uri_clip);
            const bool configured =
                ges_timeline_element_set_start(element, span.timeline_in) &&
                ges_timeline_element_set_inpoint(element, span.clip.source_in) &&
                ges_timeline_element_set_duration(element, span.clip.duration);
            if (!configured || !ges_layer_add_clip(layer, GES_CLIP(uri_clip))) {
                gst_object_unref(uri_clip);
                throw std::runtime_error("failed to configure GES clip");
            }
        }

        auto* new_pipeline = ges_pipeline_new();
        if (new_pipeline == nullptr) {
            throw std::runtime_error("failed to create GES pipeline");
        }
        gst_object_ref_sink(new_pipeline);
        if (!ges_pipeline_set_timeline(new_pipeline, new_timeline) ||
            !ges_pipeline_set_mode(new_pipeline, GES_PIPELINE_MODE_PREVIEW)) {
            gst_object_unref(new_pipeline);
            throw std::runtime_error("failed to attach timeline to GES pipeline");
        }

        if (!video_sink_factory_.empty()) {
            auto* sink = gst_element_factory_make(video_sink_factory_.c_str(), nullptr);
            if (sink == nullptr) {
                gst_object_unref(new_pipeline);
                throw std::runtime_error("missing video sink: " + video_sink_factory_);
            }
            gst_object_ref_sink(sink);
            if (video_sink_factory_ == "fakesink") {
                g_object_set(sink, "sync", TRUE, nullptr);
            }
            if (video_window_handle_ != 0 && GST_IS_VIDEO_OVERLAY(sink)) {
                gst_video_overlay_set_window_handle(
                    GST_VIDEO_OVERLAY(sink),
                    static_cast<guintptr>(video_window_handle_));
            }
            ges_pipeline_preview_set_video_sink(new_pipeline, sink);
            video_sink_ = GST_ELEMENT(gst_object_ref(sink));
            gst_object_unref(sink);
        }
        if (!audio_sink_factory_.empty()) {
            auto* sink = gst_element_factory_make(audio_sink_factory_.c_str(), nullptr);
            if (sink == nullptr) {
                gst_object_unref(new_pipeline);
                throw std::runtime_error("missing audio sink: " + audio_sink_factory_);
            }
            gst_object_ref_sink(sink);
            if (audio_sink_factory_ == "fakesink") {
                g_object_set(sink, "sync", TRUE, "signal-handoffs", TRUE, nullptr);
                g_signal_connect(sink, "handoff", G_CALLBACK(GesSequencePlayer::audio_handoff), this);
            }
            ges_pipeline_preview_set_audio_sink(new_pipeline, sink);
            gst_object_unref(sink);
        }

        timeline_ = new_timeline;
        pipeline_ = new_pipeline;
        duration_ns_.store(spans.back().timeline_out);
    } catch (...) {
        gst_object_unref(new_timeline);
        throw;
    }
}

void GesSequencePlayer::destroy_pipeline_locked() noexcept {
    if (pipeline_ != nullptr) {
        gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_NULL);
        gst_object_unref(pipeline_);
        pipeline_ = nullptr;
    }
    if (timeline_ != nullptr) {
        gst_object_unref(timeline_);
        timeline_ = nullptr;
    }
    if (video_sink_ != nullptr) {
        gst_object_unref(video_sink_);
        video_sink_ = nullptr;
    }
    duration_ns_.store(0);
    position_ns_.store(0);
}

void GesSequencePlayer::notify_state(PlaybackState state_value) {
    StateCallback callback;
    {
        std::scoped_lock lock(mutex_);
        callback = state_callback_;
    }
    if (callback) {
        callback(state_value);
    }
}

void GesSequencePlayer::monitor(std::stop_token stop_token) {
    using namespace std::chrono_literals;
    while (!stop_token.stop_requested()) {
        PositionCallback callback;
        StateCallback state_callback;
        ErrorCallback error_callback;
        std::string error_message;
        bool state_changed = false;
        TimeNs current_position = position_ns_.load();
        {
            std::scoped_lock lock(mutex_);
            if (pipeline_ != nullptr) {
                auto* bus = gst_element_get_bus(GST_ELEMENT(pipeline_));
                while (auto* message = gst_bus_pop(bus)) {
                    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_EOS) {
                        current_position = duration_ns_.load();
                        position_ns_.store(current_position);
                        state_.store(PlaybackState::stopped);
                        state_changed = true;
                    } else if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
                        GError* error = nullptr;
                        gchar* debug = nullptr;
                        gst_message_parse_error(message, &error, &debug);
                        error_message = error && error->message
                            ? error->message
                            : "GStreamer playback failed";
                        if (error != nullptr) {
                            g_error_free(error);
                        }
                        g_free(debug);
                        state_.store(PlaybackState::stopped);
                        state_changed = true;
                    }
                    gst_message_unref(message);
                }
                gst_object_unref(bus);

                if (state_.load() == PlaybackState::playing) {
                    gint64 queried = 0;
                    if (gst_element_query_position(
                            GST_ELEMENT(pipeline_), GST_FORMAT_TIME, &queried)) {
                        current_position = queried;
                        position_ns_.store(current_position);
                    }
                    callback = position_callback_;
                }
                if (state_changed) {
                    state_callback = state_callback_;
                }
                if (!error_message.empty()) {
                    error_callback = error_callback_;
                }
            }
        }
        if (callback) {
            callback(current_position);
        }
        if (state_callback) {
            state_callback(PlaybackState::stopped);
        }
        if (error_callback) {
            error_callback(std::move(error_message));
        }
        std::this_thread::sleep_for(15ms);
    }
}

}  // namespace ffgui
