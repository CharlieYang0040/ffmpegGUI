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

enum class GifDither { bayer, sierra2_4a, none };

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
    double brightness{};
    double contrast{1.0};
    double saturation{1.0};
    TimeNs transition_in{};
    std::filesystem::path color_lut_path;
    std::filesystem::path color_clut_pattern;
    int color_clut_fps{};

    [[nodiscard]] TimeNs timeline_duration() const {
        return static_cast<TimeNs>(std::llround(
            static_cast<long double>(duration) / static_cast<long double>(playback_rate)));
    }
};

struct ExportCaptionInput final {
    std::string text;
    TimeNs timeline_in{};
    TimeNs duration{};
    double position_x{0.5};
    double position_y{0.5};
    int font_size{44};
    int background_opacity{};
};

struct ExportStampInput final {
    bool enabled{};
    std::string worker;
    std::string information;
    int bar_percent{9};
    int background_opacity{90};
    bool expand_canvas{};
};

struct GifExportSettings final {
    bool enabled{};
    int width{640};
    int height{360};
    int fps{12};
    int colors{128};
    GifDither dither{GifDither::bayer};
    bool loop{true};
};

struct ExportRequest final {
    std::vector<ExportClipInput> clips;
    std::filesystem::path output_path;
    ExportVideoEncoder video_encoder{ExportVideoEncoder::h264_nvenc};
    bool prefer_stream_copy{true};
    std::filesystem::path concat_script_path;
    std::vector<ExportCaptionInput> captions;
    ExportStampInput stamp;
    std::filesystem::path subtitle_script_path;
    ExportQuality quality{ExportQuality::balanced};
    int output_width{};
    int output_height{};
    int output_fps{};
    GifExportSettings gif;
    bool hdr10{};
    int hdr_peak_nits{1000};
    int sdr_white_nits{203};
    int max_cll{1000};
    int max_fall{400};
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
