#include "export/ffmpeg_export_plan.hpp"

#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <algorithm>
#include <cctype>
#include <cmath>

namespace ffgui {
namespace {

std::string seconds(TimeNs value) {
    if (value < 0) {
        throw std::invalid_argument("export time cannot be negative");
    }
    std::ostringstream stream;
    stream << value / kNanosecondsPerSecond << '.' << std::setw(9) << std::setfill('0')
           << value % kNanosecondsPerSecond;
    return stream.str();
}

std::string path_string(const std::filesystem::path& path) {
    const auto utf8 = path.u8string();
    return {reinterpret_cast<const char*>(utf8.data()), utf8.size()};
}

bool is_boundary(const ExportClipInput& clip, TimeNs value) {
    return value == clip.asset_duration ||
           std::binary_search(clip.keyframe_pts.begin(), clip.keyframe_pts.end(), value);
}

std::pair<TimeNs, TimeNs> normalized_fades(const ExportClipInput& clip) {
    const auto timelineDuration = clip.timeline_duration();
    auto fadeIn = std::min(clip.audio_fade_in, timelineDuration);
    auto fadeOut = std::min(clip.audio_fade_out, timelineDuration);
    const auto total = checked_add(fadeIn, fadeOut);
    if (total > timelineDuration) {
        const auto ratio = static_cast<long double>(timelineDuration) /
                           static_cast<long double>(total);
        fadeIn = static_cast<TimeNs>(static_cast<long double>(fadeIn) * ratio);
        fadeOut = timelineDuration - fadeIn;
    }
    return {fadeIn, fadeOut};
}

bool can_stream_copy(const ExportRequest& request) {
    if (!request.prefer_stream_copy || request.concat_script_path.empty() ||
        request.clips.empty() || !request.captions.empty()) {
        return false;
    }
    const auto& source = request.clips.front().source_path;
    return std::all_of(request.clips.begin(), request.clips.end(), [&](const auto& clip) {
        return clip.source_path == source && clip.asset_duration > 0 &&
               clip.audio_gain == 1.0 && !clip.audio_muted &&
               clip.audio_fade_in == 0 && clip.audio_fade_out == 0 &&
               clip.playback_rate == 1.0 &&
               is_boundary(clip, clip.source_in) &&
               is_boundary(clip, checked_add(clip.source_in, clip.duration));
    });
}

std::string concat_path(const std::filesystem::path& path) {
    auto value = path_string(path);
    std::replace(value.begin(), value.end(), '\\', '/');
    std::string escaped;
    for (const auto character : value) {
        if (character == '\'') escaped += "'\\''";
        else escaped += character;
    }
    return escaped;
}

std::string filter_path(const std::filesystem::path& path) {
    auto value = path_string(path);
    std::replace(value.begin(), value.end(), '\\', '/');
    std::string escaped;
    for (const auto character : value) {
        if (character == ':' || character == '\'' || character == ',' ||
            character == '[' || character == ']') escaped += '\\';
        escaped += character;
    }
    return escaped;
}

std::string ass_time(TimeNs value) {
    const auto centiseconds = value / 10'000'000;
    std::ostringstream stream;
    stream << centiseconds / 360'000 << ':' << std::setw(2) << std::setfill('0')
           << (centiseconds / 6'000) % 60 << ':' << std::setw(2)
           << (centiseconds / 100) % 60 << '.' << std::setw(2) << centiseconds % 100;
    return stream.str();
}

std::string ass_text(const std::string& text) {
    std::string escaped;
    for (const auto character : text) {
        if (character == '\n') {
            escaped += "\\N";
        } else if (character != '\r') {
            if (character == '\\' || character == '{' || character == '}') escaped += '\\';
            escaped += character;
        }
    }
    return escaped;
}

std::string decimal(double value) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(6) << value;
    return stream.str();
}

std::string atempo_chain(double rate) {
    std::string chain;
    while (rate < 0.5) {
        chain += ",atempo=0.500000";
        rate /= 0.5;
    }
    while (rate > 2.0) {
        chain += ",atempo=2.000000";
        rate /= 2.0;
    }
    if (std::abs(rate - 1.0) > 0.0000005) chain += ",atempo=" + decimal(rate);
    return chain;
}

}  // namespace

FfmpegExportPlan compile_ffmpeg_export(const ExportRequest& request) {
    if (request.clips.empty()) {
        throw std::invalid_argument("cannot export an empty timeline");
    }
    if (request.output_path.empty()) {
        throw std::invalid_argument("export output path is empty");
    }

    FfmpegExportPlan plan;
    auto extension = request.output_path.extension().string();
    std::ranges::transform(extension, extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    const bool movFamily = extension == ".mp4" || extension == ".mov" || extension == ".m4v";
    plan.arguments = {"-hide_banner", "-y", "-progress", "pipe:2", "-nostats"};
    for (const auto& clip : request.clips) {
        if (clip.source_path.empty() || clip.duration <= 0 || clip.source_in < 0) {
            throw std::invalid_argument("export clip has an invalid source range");
        }
        if (!std::isfinite(clip.audio_gain) || clip.audio_gain < 0.0 ||
            clip.audio_gain > 4.0 || clip.audio_fade_in < 0 || clip.audio_fade_out < 0) {
            throw std::invalid_argument("export clip has invalid audio settings");
        }
        if (!std::isfinite(clip.playback_rate) || clip.playback_rate < 0.25 ||
            clip.playback_rate > 4.0 || clip.timeline_duration() <= 0) {
            throw std::invalid_argument("export clip has invalid playback rate");
        }
        plan.duration = checked_add(plan.duration, clip.timeline_duration());
    }
    for (const auto& caption : request.captions) {
        if (caption.text.empty() || caption.timeline_in < 0 || caption.duration <= 0 ||
            checked_add(caption.timeline_in, caption.duration) > plan.duration) {
            throw std::invalid_argument("export caption is outside the timeline or empty");
        }
    }
    if (can_stream_copy(request)) {
        plan.mode = ExportMode::stream_copy;
        plan.concat_script = "ffconcat version 1.0\n";
        for (const auto& clip : request.clips) {
            plan.concat_script += "file '" + concat_path(clip.source_path) + "'\n";
            plan.concat_script += "inpoint " + seconds(clip.source_in) + "\n";
            plan.concat_script += "outpoint " + seconds(checked_add(clip.source_in, clip.duration)) + "\n";
        }
        plan.arguments.insert(
            plan.arguments.end(),
            {"-f", "concat", "-safe", "0", "-i", path_string(request.concat_script_path),
             "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero"});
        if (movFamily) plan.arguments.insert(plan.arguments.end(), {"-movflags", "+faststart"});
        plan.arguments.push_back(path_string(request.output_path));
        return plan;
    }

    std::string filter;
    std::string concatInputs;
    for (std::size_t index = 0; index < request.clips.size(); ++index) {
        const auto& clip = request.clips[index];
        plan.arguments.insert(
            plan.arguments.end(),
            {"-ss", seconds(clip.source_in), "-t", seconds(clip.duration),
             "-i", path_string(clip.source_path)});

        const auto suffix = std::to_string(index);
        filter += "[" + suffix + ":v:0]setpts=(PTS-STARTPTS)/" +
                  decimal(clip.playback_rate) + "[v" + suffix + "];";
        if (clip.has_audio) {
            filter += "[" + suffix + ":a:0]aresample=48000:async=1:first_pts=0,"
                      "apad=whole_dur=" + seconds(clip.duration) +
                      ",atrim=duration=" + seconds(clip.duration) +
                      ",asetpts=PTS-STARTPTS" + atempo_chain(clip.playback_rate);
        } else {
            filter += "anullsrc=r=48000:cl=stereo:d=" + seconds(clip.duration) +
                      atempo_chain(clip.playback_rate);
        }
        const auto gain = clip.audio_muted ? 0.0 : clip.audio_gain;
        filter += ",volume=" + std::to_string(gain);
        const auto [fadeIn, fadeOut] = normalized_fades(clip);
        if (fadeIn > 0) {
            filter += ",afade=t=in:st=0:d=" + seconds(fadeIn);
        }
        if (fadeOut > 0) {
            filter += ",afade=t=out:st=" + seconds(clip.timeline_duration() - fadeOut) +
                      ":d=" + seconds(fadeOut);
        }
        filter += "[a" + suffix + "];";
        concatInputs += "[v" + suffix + "][a" + suffix + "]";
    }
    filter += concatInputs + "concat=n=" + std::to_string(request.clips.size()) + ":v=1:a=1";
    if (request.captions.empty()) {
        filter += "[vout][aout]";
    } else {
        if (request.subtitle_script_path.empty()) {
            throw std::invalid_argument("caption export requires an ASS script path");
        }
        filter += "[vbase][aout];[vbase]ass=filename='" +
                  filter_path(request.subtitle_script_path) + "'[vout]";
        plan.subtitle_script =
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            "Style: Default,Malgun Gothic,36,&H00FFFFFF,&H000000FF,&H00101010,"
            "&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,40,40,42,1\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n";
        for (const auto& caption : request.captions) {
            plan.subtitle_script += "Dialogue: 0," + ass_time(caption.timeline_in) + ',' +
                ass_time(checked_add(caption.timeline_in, caption.duration)) +
                ",Default,,0,0,0,," + ass_text(caption.text) + '\n';
        }
    }
    plan.arguments.insert(
        plan.arguments.end(),
        {"-filter_complex", std::move(filter), "-map", "[vout]", "-map", "[aout]"});

    const bool high = request.quality == ExportQuality::high;
    const bool compact = request.quality == ExportQuality::compact;
    if (request.video_encoder == ExportVideoEncoder::h264_nvenc) {
        plan.arguments.insert(
            plan.arguments.end(),
            {"-c:v", "h264_nvenc", "-preset", high ? "p5" : (compact ? "p3" : "p4"),
             "-cq", high ? "16" : (compact ? "25" : "20"), "-b:v", "0"});
    } else if (request.video_encoder == ExportVideoEncoder::libx264) {
        plan.arguments.insert(
            plan.arguments.end(),
            {"-c:v", "libx264", "-preset", high ? "slow" : (compact ? "fast" : "medium"),
             "-crf", high ? "16" : (compact ? "24" : "20")});
    } else if (request.video_encoder == ExportVideoEncoder::hevc_nvenc) {
        plan.arguments.insert(
            plan.arguments.end(),
            {"-c:v", "hevc_nvenc", "-preset", high ? "p5" : (compact ? "p3" : "p4"),
             "-cq", high ? "18" : (compact ? "28" : "23"), "-b:v", "0"});
        if (movFamily) plan.arguments.insert(plan.arguments.end(), {"-tag:v", "hvc1"});
    } else {
        plan.arguments.insert(
            plan.arguments.end(),
            {"-c:v", "libx265", "-preset", high ? "slow" : (compact ? "fast" : "medium"),
             "-crf", high ? "18" : (compact ? "28" : "23")});
        if (movFamily) plan.arguments.insert(plan.arguments.end(), {"-tag:v", "hvc1"});
    }
    plan.arguments.insert(
        plan.arguments.end(),
        {"-c:a", "aac", "-b:a", high ? "256k" : (compact ? "128k" : "192k")});
    if (movFamily) plan.arguments.insert(plan.arguments.end(), {"-movflags", "+faststart"});
    plan.arguments.push_back(path_string(request.output_path));
    return plan;
}

}  // namespace ffgui
