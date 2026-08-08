#pragma once

#include "core/time.hpp"

#include <filesystem>
#include <cmath>
#include <string>
#include <vector>

namespace ffgui {

enum class ExportVideoEncoder {
    h264_nvenc,
    libx264,
    hevc_nvenc,
    libx265,
};

enum class ExportQuality { high, balanced, compact };

enum class ExportMode {
    stream_copy,
    transcode,
};

struct ExportClipInput final {
    std::filesystem::path source_path;
    TimeNs source_in{};
    TimeNs duration{};
    bool has_audio{};
    TimeNs asset_duration{};
    std::vector<TimeNs> keyframe_pts;
    double audio_gain{1.0};
    bool audio_muted{};
    TimeNs audio_fade_in{};
    TimeNs audio_fade_out{};
    double playback_rate{1.0};

    [[nodiscard]] TimeNs timeline_duration() const {
        return static_cast<TimeNs>(std::llround(
            static_cast<long double>(duration) / static_cast<long double>(playback_rate)));
    }
};

struct ExportCaptionInput final {
    std::string text;
    TimeNs timeline_in{};
    TimeNs duration{};
};

struct ExportRequest final {
    std::vector<ExportClipInput> clips;
    std::filesystem::path output_path;
    ExportVideoEncoder video_encoder{ExportVideoEncoder::h264_nvenc};
    bool prefer_stream_copy{true};
    std::filesystem::path concat_script_path;
    std::vector<ExportCaptionInput> captions;
    std::filesystem::path subtitle_script_path;
    ExportQuality quality{ExportQuality::balanced};
};

struct FfmpegExportPlan final {
    std::vector<std::string> arguments;
    TimeNs duration{};
    ExportMode mode{ExportMode::transcode};
    std::string concat_script;
    std::string subtitle_script;
};

[[nodiscard]] FfmpegExportPlan compile_ffmpeg_export(const ExportRequest& request);

}  // namespace ffgui
