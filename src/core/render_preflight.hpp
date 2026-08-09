#pragma once

#include "core/color_pipeline.hpp"
#include "core/timeline_model.hpp"

#include <string>
#include <vector>

namespace ffgui {

enum class PreflightSeverity { warning, blocker };

struct PreflightIssue final {
    PreflightSeverity severity{PreflightSeverity::warning};
    std::string code;
    std::string message;
    std::string asset_id;
    std::vector<int> frames;
};

struct RenderPreflightReport final {
    std::vector<PreflightIssue> issues;
    [[nodiscard]] bool can_render() const noexcept;
    [[nodiscard]] std::size_t warning_count() const noexcept;
    [[nodiscard]] std::size_t blocker_count() const noexcept;
};

[[nodiscard]] RenderPreflightReport build_render_preflight(
    const TimelineModel& timeline, const ColorPipelineSettings& color_pipeline);

}  // namespace ffgui
