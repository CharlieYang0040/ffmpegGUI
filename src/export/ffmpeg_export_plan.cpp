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
    auto extension = request.output_path.extension().string();
    std::ranges::transform(extension, extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    if (extension == ".gif" || request.gif.enabled) return false;
    if (!request.prefer_stream_copy || request.concat_script_path.empty() ||
        request.clips.empty() || !request.captions.empty() || request.stamp.enabled ||
        request.hdr10 || request.output_width > 0 ||
        request.output_height > 0 || request.output_fps > 0) {
        return false;
    }
    const auto& source = request.clips.front().source_path;
    return std::all_of(request.clips.begin(), request.clips.end(), [&](const auto& clip) {
        return clip.source_path == source && clip.asset_duration > 0 &&
               clip.audio_gain == 1.0 && !clip.audio_muted &&
               clip.audio_fade_in == 0 && clip.audio_fade_out == 0 &&
               clip.playback_rate == 1.0 && clip.brightness == 0.0 &&
               clip.contrast == 1.0 && clip.saturation == 1.0 &&
               clip.transition_in == 0 && clip.color_lut_path.empty() &&
               clip.color_clut_pattern.empty() &&
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

std::string ass_alpha(int opacity_percent) {
    const auto alpha = 255 - std::clamp(opacity_percent, 0, 100) * 255 / 100;
    std::ostringstream stream;
    stream << std::uppercase << std::hex << std::setw(2) << std::setfill('0') << alpha;
    return stream.str();
}

std::string rec2100_master_display(int peak_nits) {
    const auto peak = std::clamp(peak_nits, 100, 10'000) * 10'000;
    std::ostringstream stream;
    stream << "G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L("
           << peak << ",1)";
    return stream.str();
}

void append_hdr10_signaling(
    std::vector<std::string>& arguments,
    const ExportRequest& request,
    ExportVideoEncoder encoder) {
    arguments.insert(
        arguments.end(),
        {"-color_primaries", "bt2020", "-color_trc", "smpte2084",
         "-colorspace", "bt2020nc", "-color_range", "tv"});
    if (encoder == ExportVideoEncoder::hevc_nvenc) {
        arguments.insert(arguments.end(), {"-pix_fmt", "p010le"});
        arguments.insert(
            arguments.end(),
            {"-bsf:v",
             "hevc_metadata=colour_primaries=9:transfer_characteristics=16:"
             "matrix_coefficients=9"});
        return;
    }
    if (encoder == ExportVideoEncoder::libx265) {
        arguments.insert(arguments.end(), {"-pix_fmt", "yuv420p10le"});
        std::ostringstream params;
        params << "hdr-opt=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:"
                  "colormatrix=bt2020nc:master-display="
               << rec2100_master_display(request.hdr_peak_nits)
               << ":max-cll=" << std::clamp(request.max_cll, 0, 10'000) << ','
               << std::clamp(request.max_fall, 0, 10'000);
        arguments.insert(arguments.end(), {"-x265-params", params.str()});
        return;
    }
    if (encoder == ExportVideoEncoder::libx264) {
        arguments.insert(
            arguments.end(),
            {"-x264-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc"});
    }
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
    if ((request.output_width == 0) != (request.output_height == 0) ||
        request.output_width < 0 || request.output_height < 0 || request.output_fps < 0 ||
        request.output_fps > 240) {
        throw std::invalid_argument("export resolution or frame rate is invalid");
    }
    if (request.hdr10 &&
        (request.hdr_peak_nits < 100 || request.hdr_peak_nits > 10'000 ||
         request.sdr_white_nits < 80 || request.sdr_white_nits > 500 ||
         request.max_cll < 0 || request.max_fall < 0 ||
         request.max_cll > 10'000 || request.max_fall > 10'000)) {
        throw std::invalid_argument("HDR10 mastering metadata is invalid");
    }

    FfmpegExportPlan plan;
    auto extension = request.output_path.extension().string();
    std::ranges::transform(extension, extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    const bool movFamily = extension == ".mp4" || extension == ".mov" || extension == ".m4v";
    const bool gifOutput = extension == ".gif" || request.gif.enabled;
    if (gifOutput &&
        (request.gif.width < 16 || request.gif.width > 4096 ||
         request.gif.height < 16 || request.gif.height > 4096 ||
         request.gif.fps < 1 || request.gif.fps > 60 ||
         request.gif.colors < 2 || request.gif.colors > 256)) {
        throw std::invalid_argument("GIF output settings are invalid");
    }
    plan.arguments = {"-hide_banner", "-n", "-progress", "pipe:2", "-nostats"};
    for (std::size_t index = 0; index < request.clips.size(); ++index) {
        const auto& clip = request.clips[index];
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
        if (!std::isfinite(clip.brightness) || clip.brightness < -1.0 ||
            clip.brightness > 1.0 || !std::isfinite(clip.contrast) ||
            clip.contrast < 0.0 || clip.contrast > 2.0 ||
            !std::isfinite(clip.saturation) || clip.saturation < 0.0 ||
            clip.saturation > 2.0) {
            throw std::invalid_argument("export clip has invalid color settings");
        }
        const auto maximumTransition = index == 0 ? 0 : std::min(
            request.clips[index - 1].timeline_duration(), clip.timeline_duration()) / 2;
        if (clip.transition_in < 0 || clip.transition_in > maximumTransition) {
            throw std::invalid_argument("export clip has invalid dissolve duration");
        }
        plan.duration = checked_add(plan.duration, clip.timeline_duration());
        if (index > 0) plan.duration -= clip.transition_in;
    }
    for (const auto& caption : request.captions) {
        if (caption.text.empty() || caption.timeline_in < 0 || caption.duration <= 0 ||
            checked_add(caption.timeline_in, caption.duration) > plan.duration ||
            !std::isfinite(caption.position_x) || !std::isfinite(caption.position_y) ||
            caption.position_x < 0.0 || caption.position_x > 1.0 ||
            caption.position_y < 0.0 || caption.position_y > 1.0 ||
            caption.font_size < 12 || caption.font_size > 160 ||
            caption.background_opacity < 0 || caption.background_opacity > 100) {
            throw std::invalid_argument("export caption is outside the timeline or empty");
        }
    }
    if (request.stamp.enabled &&
        (request.stamp.bar_percent < 4 || request.stamp.bar_percent > 25 ||
         request.stamp.background_opacity < 0 ||
         request.stamp.background_opacity > 100)) {
        throw std::invalid_argument("export stamp bar size is invalid");
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

    const bool hasTransitions = std::ranges::any_of(
        request.clips,
        [](const ExportClipInput& clip) { return clip.transition_in > 0; });
    // xfade requires both inputs to use a constant, identical frame rate.  Keeping VFR
    // timestamps here can make framesync hold the outgoing clip throughout the dissolve.
    const auto compositionFps = gifOutput ? request.gif.fps :
        (request.output_fps > 0 ? request.output_fps : (hasTransitions ? 30 : 0));
    std::string filter;
    for (std::size_t index = 0; index < request.clips.size(); ++index) {
        const auto& clip = request.clips[index];
        plan.arguments.insert(
            plan.arguments.end(),
            {"-ss", seconds(clip.source_in), "-t", seconds(clip.duration),
             "-i", path_string(clip.source_path)});
    }
    std::vector<int> clutInputs(request.clips.size(), -1);
    auto nextInput = static_cast<int>(request.clips.size());
    for (std::size_t index = 0; index < request.clips.size(); ++index) {
        const auto& clip = request.clips[index];
        if (clip.color_clut_pattern.empty()) continue;
        const auto fps = clip.color_clut_fps > 0 ? clip.color_clut_fps :
            (compositionFps > 0 ? compositionFps : 30);
        plan.arguments.insert(
            plan.arguments.end(),
            {"-framerate", std::to_string(fps), "-start_number", "1",
             "-i", path_string(clip.color_clut_pattern)});
        clutInputs[index] = nextInput++;
    }
    for (std::size_t index = 0; index < request.clips.size(); ++index) {
        const auto& clip = request.clips[index];
        const auto suffix = std::to_string(index);
        filter += "[" + suffix + ":v:0]";
        if (clutInputs[index] >= 0) {
            filter += "[" + std::to_string(clutInputs[index]) +
                ":v:0]haldclut=interp=trilinear,";
        } else if (!clip.color_lut_path.empty()) {
            filter += "lut3d=file='" + filter_path(clip.color_lut_path) +
                "':interp=tetrahedral,";
        } else if (clip.brightness != 0.0 || clip.contrast != 1.0 || clip.saturation != 1.0) {
            filter += "eq=brightness=" + decimal(clip.brightness) +
                ":contrast=" + decimal(clip.contrast) +
                ":saturation=" + decimal(clip.saturation) + ",";
        }
        if (request.output_width > 0) {
            filter += "scale=" + std::to_string(request.output_width) + ":" +
                std::to_string(request.output_height) +
                ":force_original_aspect_ratio=decrease,pad=" +
                std::to_string(request.output_width) + ":" +
                std::to_string(request.output_height) + ":(ow-iw)/2:(oh-ih)/2,setsar=1,";
        }
        filter += "settb=AVTB,setpts=(PTS-STARTPTS)/" + decimal(clip.playback_rate) +
                  ",trim=duration=" + seconds(clip.timeline_duration());
        if (compositionFps > 0) {
            filter += ",fps=" + std::to_string(compositionFps) +
                      ":round=near:eof_action=pass"
                      ",tpad=stop_mode=clone:stop_duration=" +
                      decimal(1.0 / static_cast<double>(compositionFps)) +
                      ",trim=duration=" + seconds(clip.timeline_duration());
        }
        // Rebase once more after trim/fps so every xfade input starts at zero with the
        // same time base and pixel format, including MKV and VFR sources.
        filter += request.hdr10
            ? ",format=yuv420p10le,settb=AVTB,setpts=PTS-STARTPTS[v" + suffix + "];"
            : ",format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[v" + suffix + "];";
        if (!gifOutput && clip.has_audio) {
            filter += "[" + suffix + ":a:0]aresample=48000:async=1:first_pts=0,"
                      "apad=whole_dur=" + seconds(clip.duration) +
                      ",atrim=duration=" + seconds(clip.duration) +
                      ",asetpts=PTS-STARTPTS" + atempo_chain(clip.playback_rate);
        } else if (!gifOutput) {
            filter += "anullsrc=r=48000:cl=stereo:d=" + seconds(clip.duration) +
                      atempo_chain(clip.playback_rate);
        }
        if (!gifOutput) {
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
        }
    }
    std::string videoLabel = "v0";
    std::string audioLabel = "a0";
    TimeNs composedDuration = request.clips.front().timeline_duration();
    for (std::size_t index = 1; index < request.clips.size(); ++index) {
        const auto suffix = std::to_string(index);
        const auto transition = request.clips[index].transition_in;
        const auto nextVideo = "vc" + suffix;
        const auto nextAudio = "ac" + suffix;
        if (transition > 0) {
            filter += "[" + videoLabel + "][v" + suffix + "]xfade=transition=fade:duration=" +
                seconds(transition) + ":offset=" + seconds(composedDuration - transition) +
                "[" + nextVideo + "];";
            if (!gifOutput) {
                filter += "[" + audioLabel + "][a" + suffix + "]acrossfade=d=" +
                    seconds(transition) + ":c1=tri:c2=tri[" + nextAudio + "];";
            }
        } else if (gifOutput) {
            filter += "[" + videoLabel + "][v" + suffix +
                "]concat=n=2:v=1:a=0[" + nextVideo + "];";
        } else {
            filter += "[" + videoLabel + "][" + audioLabel + "][v" + suffix +
                "][a" + suffix + "]concat=n=2:v=1:a=1[" + nextVideo + "][" +
                nextAudio + "];";
        }
        composedDuration = checked_add(composedDuration, request.clips[index].timeline_duration()) -
            transition;
        videoLabel = nextVideo;
        if (!gifOutput) audioLabel = nextAudio;
    }
    const auto stampBarHeight = request.stamp.enabled
        ? 720 * request.stamp.bar_percent / 100 : 0;
    const auto videoOffsetY = request.stamp.enabled && request.stamp.expand_canvas
        ? stampBarHeight : 0;
    const auto playResolutionY = 720 + videoOffsetY * 2;
    if (request.stamp.enabled && request.stamp.expand_canvas) {
        const auto ratio = decimal(request.stamp.bar_percent / 100.0);
        const auto opacity = decimal(request.stamp.background_opacity / 100.0);
        filter += "[" + videoLabel + "]split=3[vstampcenter][vstamptop][vstampbottom];";
        filter += "[vstamptop]crop=iw:max(2\\,trunc(ih*" + ratio +
            "/2)*2):0:0,drawbox=color=black@" + opacity + ":t=fill[vstamptopbar];";
        filter += "[vstampbottom]crop=iw:max(2\\,trunc(ih*" + ratio +
            "/2)*2):0:ih-oh,drawbox=color=black@" + opacity +
            ":t=fill[vstampbottombar];";
        filter += "[vstamptopbar][vstampcenter][vstampbottombar]"
                  "vstack=inputs=3[vstampexpanded];";
        videoLabel = "vstampexpanded";
    }
    const bool hasGraphics = !request.captions.empty() || request.stamp.enabled;
    if (!hasGraphics) {
        filter += "[" + videoLabel + "]null[vout]";
        if (!gifOutput) filter += ";[" + audioLabel + "]anull[aout]";
    } else {
        if (request.subtitle_script_path.empty()) {
            throw std::invalid_argument("graphic overlay export requires an ASS script path");
        }
        filter += "[" + videoLabel + "]null[vbase];";
        if (!gifOutput) filter += "[" + audioLabel + "]anull[aout];";
        filter += "[vbase]ass=filename='" +
                  filter_path(request.subtitle_script_path) + "'[vout]";
        plan.subtitle_script =
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: " +
            std::to_string(playResolutionY) + "\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            "Style: Default,Malgun Gothic,36,&H00FFFFFF,&H000000FF,&H00101010,"
            "&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,40,40,42,1\n";
        for (std::size_t index = 0; index < request.captions.size(); ++index) {
            const auto& caption = request.captions[index];
            if (caption.background_opacity <= 0) continue;
            const auto color = "&H" + ass_alpha(caption.background_opacity) + "000000";
            plan.subtitle_script += "Style: TextBackground" + std::to_string(index) +
                ",Malgun Gothic,36,&H00FFFFFF,&H000000FF," + color + ',' + color +
                ",-1,0,0,0,100,100,0,0,3,7,0,5,20,20,20,1\n";
        }
        plan.subtitle_script +=
            "\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n";
        if (request.stamp.enabled) {
            const auto barHeight = stampBarHeight;
            const auto bottom = request.stamp.expand_canvas
                ? videoOffsetY + 720 : 720 - barHeight;
            const auto end = ass_time(plan.duration);
            const auto rectangle = [&](int top, int bottomValue) {
                return std::string{"{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c&H000000&\\1a&H"} +
                    ass_alpha(request.stamp.background_opacity) + "&}m 0 " +
                    std::to_string(top) + " l 1280 " + std::to_string(top) + " 1280 " +
                    std::to_string(bottomValue) + " 0 " + std::to_string(bottomValue);
            };
            if (!request.stamp.expand_canvas) {
                plan.subtitle_script += "Dialogue: 0,0:00:00.00," + end +
                    ",Default,,0,0,0,," + rectangle(0, barHeight) + '\n';
                plan.subtitle_script += "Dialogue: 0,0:00:00.00," + end +
                    ",Default,,0,0,0,," + rectangle(720 - barHeight, 720) + '\n';
            }
            if (!request.stamp.information.empty()) {
                plan.subtitle_script += "Dialogue: 1,0:00:00.00," + end +
                    ",Default,,0,0,0,,{\\an4\\pos(28," + std::to_string(barHeight / 2) +
                    ")\\fs24}" + ass_text(request.stamp.information) + '\n';
            }
            if (!request.stamp.worker.empty()) {
                plan.subtitle_script += "Dialogue: 1,0:00:00.00," + end +
                    ",Default,,0,0,0,,{\\an6\\pos(1252," + std::to_string(barHeight / 2) +
                    ")\\fs24}작업자  " + ass_text(request.stamp.worker) + '\n';
            }
            for (TimeNs start = 0; start < plan.duration; start += kNanosecondsPerSecond) {
                const auto finish = std::min(
                    checked_add(start, kNanosecondsPerSecond), plan.duration);
                const auto secondsValue = start / kNanosecondsPerSecond;
                std::ostringstream timecode;
                timecode << std::setw(2) << std::setfill('0') << secondsValue / 3600 << ':'
                         << std::setw(2) << (secondsValue / 60) % 60 << ':'
                         << std::setw(2) << secondsValue % 60;
                plan.subtitle_script += "Dialogue: 1," + ass_time(start) + ',' +
                    ass_time(finish) + ",Default,,0,0,0,,{\\an6\\pos(1252," +
                    std::to_string(bottom + barHeight / 2) + ")\\fs24}" +
                    timecode.str() + '\n';
            }
        }
        for (std::size_t index = 0; index < request.captions.size(); ++index) {
            const auto& caption = request.captions[index];
            const auto x = std::clamp(
                static_cast<int>(std::lround(caption.position_x * 1280)), 0, 1280);
            const auto y = std::clamp(
                videoOffsetY + static_cast<int>(std::lround(caption.position_y * 720)),
                videoOffsetY, videoOffsetY + 720);
            const auto style = caption.background_opacity > 0
                ? "TextBackground" + std::to_string(index) : "Default";
            plan.subtitle_script += "Dialogue: 2," + ass_time(caption.timeline_in) + ',' +
                ass_time(checked_add(caption.timeline_in, caption.duration)) +
                ',' + style + ",,0,0,0,,{\\an5\\pos(" + std::to_string(x) + ',' +
                std::to_string(y) + ")\\fs" + std::to_string(caption.font_size) + "}" +
                ass_text(caption.text) + '\n';
        }
    }
    if (gifOutput) {
        const auto dither = request.gif.dither == GifDither::bayer ? "bayer" :
            (request.gif.dither == GifDither::sierra2_4a ? "sierra2_4a" : "none");
        filter += ";[vout]fps=" + std::to_string(request.gif.fps) +
            ",scale=" + std::to_string(request.gif.width) + ":" +
            std::to_string(request.gif.height) +
            ":force_original_aspect_ratio=decrease:flags=lanczos,pad=" +
            std::to_string(request.gif.width) + ":" + std::to_string(request.gif.height) +
            ":(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,split[gifframes][gifpalettein];";
        filter += "[gifpalettein]palettegen=max_colors=" +
            std::to_string(request.gif.colors) +
            ":reserve_transparent=0:stats_mode=diff[gifpalette];";
        filter += "[gifframes][gifpalette]paletteuse=dither=" + std::string{dither} +
            (request.gif.dither == GifDither::bayer ? ":bayer_scale=3" : "") +
            ":diff_mode=rectangle[gifout]";
        plan.arguments.insert(
            plan.arguments.end(),
            {"-filter_complex", std::move(filter), "-map", "[gifout]", "-an",
             "-loop", request.gif.loop ? "0" : "-1", "-final_delay", "0",
             path_string(request.output_path)});
        return plan;
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
    if (request.hdr10 && !gifOutput) {
        append_hdr10_signaling(plan.arguments, request, request.video_encoder);
    }
    plan.arguments.insert(
        plan.arguments.end(),
        {"-c:a", "aac", "-b:a", high ? "256k" : (compact ? "128k" : "192k")});
    if (movFamily) plan.arguments.insert(plan.arguments.end(), {"-movflags", "+faststart"});
    plan.arguments.push_back(path_string(request.output_path));
    return plan;
}

}  // namespace ffgui
