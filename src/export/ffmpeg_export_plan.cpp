#include "export/ffmpeg_export_plan.hpp"

#include <iomanip>
#include <sstream>
#include <stdexcept>

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

}  // namespace

FfmpegExportPlan compile_ffmpeg_export(const ExportRequest& request) {
    if (request.clips.empty()) {
        throw std::invalid_argument("cannot export an empty timeline");
    }
    if (request.output_path.empty()) {
        throw std::invalid_argument("export output path is empty");
    }

    FfmpegExportPlan plan;
    plan.arguments = {"-hide_banner", "-y", "-progress", "pipe:2", "-nostats"};
    std::string filter;
    std::string concatInputs;
    for (std::size_t index = 0; index < request.clips.size(); ++index) {
        const auto& clip = request.clips[index];
        if (clip.source_path.empty() || clip.duration <= 0 || clip.source_in < 0) {
            throw std::invalid_argument("export clip has an invalid source range");
        }
        plan.duration = checked_add(plan.duration, clip.duration);
        plan.arguments.insert(
            plan.arguments.end(),
            {"-ss", seconds(clip.source_in), "-t", seconds(clip.duration),
             "-i", path_string(clip.source_path)});

        const auto suffix = std::to_string(index);
        filter += "[" + suffix + ":v:0]setpts=PTS-STARTPTS[v" + suffix + "];";
        if (clip.has_audio) {
            filter += "[" + suffix + ":a:0]aresample=48000:async=1:first_pts=0,"
                      "apad=whole_dur=" + seconds(clip.duration) +
                      ",atrim=duration=" + seconds(clip.duration) +
                      ",asetpts=PTS-STARTPTS[a" + suffix + "];";
        } else {
            filter += "anullsrc=r=48000:cl=stereo:d=" + seconds(clip.duration) +
                      "[a" + suffix + "];";
        }
        concatInputs += "[v" + suffix + "][a" + suffix + "]";
    }
    filter += concatInputs + "concat=n=" + std::to_string(request.clips.size()) +
              ":v=1:a=1[vout][aout]";
    plan.arguments.insert(
        plan.arguments.end(),
        {"-filter_complex", std::move(filter), "-map", "[vout]", "-map", "[aout]"});

    if (request.video_encoder == ExportVideoEncoder::h264_nvenc) {
        plan.arguments.insert(
            plan.arguments.end(),
            {"-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-b:v", "0"});
    } else {
        plan.arguments.insert(
            plan.arguments.end(),
            {"-c:v", "libx264", "-preset", "medium", "-crf", "18"});
    }
    plan.arguments.insert(
        plan.arguments.end(),
        {"-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         path_string(request.output_path)});
    return plan;
}

}  // namespace ffgui
