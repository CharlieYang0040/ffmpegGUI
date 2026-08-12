#pragma once

#include "playback/sequence_player.hpp"

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>
#include <functional>
#include <memory>
#include <vector>

#include <gst/app/gstappsink.h>

typedef struct _GESPipeline GESPipeline;
typedef struct _GESTimeline GESTimeline;
typedef struct _GstElement GstElement;
typedef struct _GstBuffer GstBuffer;
typedef struct _GstPad GstPad;

namespace ffgui {

struct AudioContinuityMetrics final {
    std::uint64_t buffer_count{};
    TimeNs maximum_positive_gap{};
};

enum class PreviewCpuFormat { bgra8, rgba16le };

struct PreviewVideoFrame final {
    std::shared_ptr<void> sample;
    std::shared_ptr<void> texture_owner;
    void* texture{};
    std::uint32_t width{};
    std::uint32_t height{};
    std::uint32_t texture_subresource{};
    TimeNs pts{};
    std::uint64_t serial{};
    void* device{};
    std::shared_ptr<std::vector<std::uint8_t>> cpu_pixels;
    std::uint32_t cpu_stride{};
    PreviewCpuFormat cpu_format{PreviewCpuFormat::bgra8};
};

class GesSequencePlayer final : public SequencePlayer {
public:
    explicit GesSequencePlayer(
        std::string video_sink_factory = "fakesink",
        std::string audio_sink_factory = "fakesink");
    ~GesSequencePlayer() override;

    GesSequencePlayer(const GesSequencePlayer&) = delete;
    GesSequencePlayer& operator=(const GesSequencePlayer&) = delete;

    void set_timeline(std::vector<TimelineSpan> timeline) override;
    void set_timeline(
        std::vector<TimelineSpan> timeline,
        std::vector<CaptionCue> captions);
    void seek(TimeNs timeline_position) override;
    void play() override;
    void pause() override;
    void stop() override;
    void set_position_callback(PositionCallback callback) override;
    void set_state_callback(StateCallback callback) override;
    void set_error_callback(ErrorCallback callback) override;
    void set_video_window_handle(std::uintptr_t window_handle);
    void set_d3d11_device(void* device);
    void set_video_frame_callback(std::function<void(PreviewVideoFrame)> callback);
    void set_scope_frame_callback(std::function<void(PreviewVideoFrame)> callback);
    void set_scope_capture_enabled(bool enabled) noexcept {
        scope_capture_enabled_.store(enabled, std::memory_order_release);
        if (enabled) scope_last_pts_.store(GST_CLOCK_TIME_NONE, std::memory_order_release);
    }
    void set_float_output_enabled(bool enabled);
    void set_legacy_source_color_enabled(bool enabled);
    void set_color_pipeline(ColorPipelineSettings settings, std::string output_space);

    [[nodiscard]] TimeNs duration() const noexcept;
    [[nodiscard]] TimeNs position() const noexcept;
    [[nodiscard]] PlaybackState state() const noexcept;
    void reset_audio_continuity_metrics() noexcept;
    [[nodiscard]] AudioContinuityMetrics audio_continuity_metrics() const noexcept;
    [[nodiscard]] std::uint64_t video_frames_received() const noexcept {
        return video_frame_serial_.load();
    }
    [[nodiscard]] std::uint64_t source_automation_bindings() const noexcept {
        return source_automation_bindings_.load();
    }
    [[nodiscard]] std::uint64_t source_color_lut_bindings() const noexcept {
        return source_color_lut_bindings_.load();
    }
    [[nodiscard]] std::uint64_t source_gpu_color_lut_bindings() const noexcept {
        return source_gpu_color_lut_bindings_.load();
    }
    [[nodiscard]] std::uint64_t source_gpu_ocio_shader_bindings() const noexcept {
        return source_gpu_ocio_shader_bindings_.load();
    }
    [[nodiscard]] bool direct_d3d_compositor_enabled() const noexcept {
        return direct_d3d_compositor_enabled_;
    }
    [[nodiscard]] std::uint64_t d3d_compositor_instances() const noexcept {
        return d3d_compositor_instances_.load();
    }
    [[nodiscard]] std::uint64_t d3d_download_instances() const noexcept {
        return d3d_download_instances_.load();
    }
    [[nodiscard]] std::uint64_t system_compositor_instances() const noexcept {
        return system_compositor_instances_.load();
    }
    [[nodiscard]] std::uint64_t d3d_composition_frames() const noexcept;
    [[nodiscard]] std::uint64_t d3d_composition_meta_frames() const noexcept;
    [[nodiscard]] std::uint64_t d3d_blended_frames() const noexcept;

private:
    void rebuild_pipeline_locked(
        const std::vector<TimelineSpan>& timeline,
        const std::vector<CaptionCue>& captions);
    void destroy_pipeline_locked() noexcept;
    void notify_state(PlaybackState state_value);
    void monitor(std::stop_token stop_token);
    static void audio_handoff(GstElement*, GstBuffer*, GstPad*, void* user_data);
    static GstFlowReturn new_video_sample(GstAppSink* sink, void* user_data);

    std::string video_sink_factory_;
    std::string audio_sink_factory_;
    mutable std::mutex mutex_;
    mutable std::mutex callback_mutex_;
    GESPipeline* pipeline_{};
    GESTimeline* timeline_{};
    GstElement* video_sink_{};
    std::uintptr_t video_window_handle_{};
    PositionCallback position_callback_;
    StateCallback state_callback_;
    ErrorCallback error_callback_;
    std::function<void(PreviewVideoFrame)> video_frame_callback_;
    std::function<void(PreviewVideoFrame)> scope_frame_callback_;
    mutable std::mutex cut_points_mutex_;
    std::vector<TimeNs> hard_cut_points_;
    std::atomic<void*> d3d11_device_handle_{nullptr};
    std::atomic<std::uint64_t> video_frame_serial_{0};
    std::atomic<std::uint64_t> scope_last_pts_{GST_CLOCK_TIME_NONE};
    std::atomic<bool> scope_capture_enabled_{true};
    std::atomic<std::uint64_t> source_automation_bindings_{0};
    std::atomic<std::uint64_t> source_color_lut_bindings_{0};
    std::atomic<std::uint64_t> source_gpu_color_lut_bindings_{0};
    std::atomic<std::uint64_t> source_gpu_ocio_shader_bindings_{0};
    std::atomic<std::uint64_t> d3d_compositor_instances_{0};
    std::atomic<std::uint64_t> d3d_download_instances_{0};
    std::atomic<std::uint64_t> system_compositor_instances_{0};
    std::atomic<std::uint64_t> d3d_composition_frames_{0};
    std::atomic<std::uint64_t> d3d_composition_meta_frames_{0};
    std::atomic<std::uint64_t> d3d_blended_frames_{0};
    std::atomic<bool> float_output_enabled_{false};
    std::atomic<bool> legacy_source_color_enabled_{true};
    mutable std::mutex color_settings_mutex_;
    ColorPipelineSettings color_pipeline_;
    std::string color_output_space_;
    std::vector<std::string> registered_lut_ids_;
    std::vector<std::string> registered_ocio_shader_ids_;
    bool d3d11_color_lut_available_{};
    bool direct_d3d_compositor_enabled_{};
    std::uint64_t lut_generation_{};
    std::atomic<TimeNs> duration_ns_{0};
    std::atomic<TimeNs> position_ns_{0};
    std::atomic<PlaybackState> state_{PlaybackState::stopped};
    std::atomic<std::uint64_t> audio_buffer_count_{0};
    std::atomic<TimeNs> audio_last_end_ns_{-1};
    std::atomic<TimeNs> audio_maximum_gap_ns_{0};
    std::jthread monitor_thread_;
};

}  // namespace ffgui
