#pragma once

#include "core/color_pipeline.hpp"

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace ffgui {

struct LookExportFile final {
    std::string relative_path;
    std::string text;
};

struct LookExportPackage final {
    std::vector<LookExportFile> files;
    std::vector<std::uint8_t> ocioz;
    std::string cube;
    std::string dual_tone_mapping_note;
};

[[nodiscard]] std::string encoding_name(LutEncoding encoding);
[[nodiscard]] std::string bake_look_cube(
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const LutExportRequest& request,
    std::int64_t source_time = 0);
[[nodiscard]] LookExportPackage compile_look_export(
    const ColorPipelineSettings& settings,
    const GradeGraph& grade,
    const LutExportRequest& request,
    std::int64_t source_time = 0);
void write_look_export(
    const LookExportPackage& package, const std::filesystem::path& directory);

}  // namespace ffgui
