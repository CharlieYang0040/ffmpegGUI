#include "core/render_preflight.hpp"

#include <algorithm>
#include <filesystem>
#include <ranges>
#include <unordered_set>

namespace ffgui {

bool RenderPreflightReport::can_render() const noexcept {
    return std::ranges::none_of(issues, [](const auto& issue) {
        return issue.severity == PreflightSeverity::blocker;
    });
}

std::size_t RenderPreflightReport::warning_count() const noexcept {
    return std::ranges::count(issues, PreflightSeverity::warning, &PreflightIssue::severity);
}

std::size_t RenderPreflightReport::blocker_count() const noexcept {
    return std::ranges::count(issues, PreflightSeverity::blocker, &PreflightIssue::severity);
}

RenderPreflightReport build_render_preflight(
    const TimelineModel& timeline, const ColorPipelineSettings& color_pipeline) {
    RenderPreflightReport report;
    std::unordered_set<std::string> inspected;
    for (const auto& clip : timeline.clips()) {
        if (!clip.grade.nodes().empty()) {
            report.issues.push_back({PreflightSeverity::blocker, "grade-render-not-connected",
                "Clip grade nodes require the unified float frame server before export",
                clip.asset_id, {}});
        }
        if (!inspected.insert(clip.asset_id).second) continue;
        const auto* asset = timeline.asset(clip.asset_id);
        if (asset == nullptr) {
            report.issues.push_back({PreflightSeverity::blocker, "missing-asset",
                "Timeline clip refers to an asset that is not registered", clip.asset_id, {}});
            continue;
        }
        if (!std::filesystem::is_regular_file(asset->export_path())) {
            report.issues.push_back({PreflightSeverity::blocker, "offline-media",
                "Media or its prepared render source is offline", asset->id(), {}});
        }
        if (asset->image_sequence().has_value()) {
            const auto& sequence = *asset->image_sequence();
            if (sequence.deep) {
                report.issues.push_back({PreflightSeverity::blocker, "deep-exr",
                    "Deep EXR compositing is outside this pipeline", asset->id(), {}});
            }
            if (!sequence.missing_frames.empty()) {
                report.issues.push_back({PreflightSeverity::warning, "missing-frames",
                    "Missing sequence frames will use nearest-frame substitution",
                    asset->id(), sequence.missing_frames});
            }
        }
        if (color_pipeline.mode != ColorPipelineMode::legacy &&
            (asset->source_color().unresolved || asset->source_color().input_color_space.empty())) {
            report.issues.push_back({PreflightSeverity::blocker, "unresolved-color-space",
                "Managed color output requires an explicit input color space", asset->id(), {}});
        }
    }
    return report;
}

}  // namespace ffgui
