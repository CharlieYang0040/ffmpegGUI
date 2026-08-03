#pragma once

#include "core/time.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace ffgui {

enum class ExportVideoEncoder {
    h264_nvenc,
    libx264,
};

struct ExportClipInput final {
    std::filesystem::path source_path;
    TimeNs source_in{};
    TimeNs duration{};
    bool has_audio{};
};

struct ExportRequest final {
    std::vector<ExportClipInput> clips;
    std::filesystem::path output_path;
    ExportVideoEncoder video_encoder{ExportVideoEncoder::h264_nvenc};
};

struct FfmpegExportPlan final {
    std::vector<std::string> arguments;
    TimeNs duration{};
};

[[nodiscard]] FfmpegExportPlan compile_ffmpeg_export(const ExportRequest& request);

}  // namespace ffgui
