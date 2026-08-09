#pragma once

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

namespace ffgui {

enum class ColorPipelineMode { legacy, aces_managed, custom_ocio };

struct ColorPipelineSettings final {
    ColorPipelineMode mode{ColorPipelineMode::legacy};
    std::string ocio_config_path;
    std::string working_space{"ACEScg"};
    std::string display;
    std::string view;
    std::string output_space;
    bool display_transform_bypassed{};
    bool hdr_monitoring{};
    int hdr_peak_nits{1000};
    int sdr_white_nits{203};
    int max_cll{1000};
    int max_fall{400};

    bool operator==(const ColorPipelineSettings&) const = default;
    void validate() const;
};

enum class GradeNodeType {
    primary,
    log_wheels,
    rgb_mixer,
    rgb_curves,
    hue_curves,
    hdr_zones,
    color_warper,
    lut,
    qualifier,
    power_window
};

struct CurvePoint final {
    double x{};
    double y{};
    bool operator==(const CurvePoint&) const = default;
};

struct GradeNode final {
    std::string id;
    std::string name;
    GradeNodeType type{GradeNodeType::primary};
    bool enabled{true};
    double mix{1.0};
    std::unordered_map<std::string, double> parameters;
    std::unordered_map<std::string, std::vector<CurvePoint>> curves;
    std::string external_path;

    bool operator==(const GradeNode&) const = default;
    [[nodiscard]] bool lut_representable() const noexcept;
    [[nodiscard]] bool render_supported() const noexcept;
    void validate() const;
};

class GradeGraph final {
public:
    [[nodiscard]] const std::vector<GradeNode>& nodes() const noexcept { return nodes_; }
    [[nodiscard]] GradeNode* node(const std::string& id) noexcept;
    [[nodiscard]] const GradeNode* node(const std::string& id) const noexcept;
    void add(GradeNode node);
    void remove(const std::string& id);
    void move(const std::string& id, std::size_t insertion_index);
    [[nodiscard]] bool lut_representable() const noexcept;
    [[nodiscard]] std::vector<std::string> lut_incompatible_nodes() const;
    [[nodiscard]] std::vector<std::string> render_unsupported_nodes() const;

    bool operator==(const GradeGraph&) const = default;

private:
    std::vector<GradeNode> nodes_;
};

enum class LutEncoding { acescct, log2, working_space };

struct LutExportRequest final {
    std::string input_space;
    std::string output_space;
    LutEncoding encoding{LutEncoding::acescct};
    int cube_size{33};
    bool include_display_transform{};
    bool unreal_ocio_bundle{true};
    bool legacy_unreal_png{};

    void validate(const GradeGraph& graph) const;
};

[[nodiscard]] GradeNode make_default_grade_node(GradeNodeType type, std::string id);
[[nodiscard]] std::string grade_node_type_name(GradeNodeType type);

}  // namespace ffgui
