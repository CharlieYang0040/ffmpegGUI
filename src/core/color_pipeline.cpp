#include "core/color_pipeline.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <ranges>
#include <stdexcept>

namespace ffgui {

void ColorPipelineSettings::validate() const {
    if (mode == ColorPipelineMode::custom_ocio && ocio_config_path.empty()) {
        throw std::invalid_argument("custom OCIO mode requires a configuration path");
    }
    if (working_space.empty() || hdr_peak_nits < 100 || hdr_peak_nits > 10'000 ||
        sdr_white_nits < 80 || sdr_white_nits > 500 || max_cll < 0 || max_fall < 0 ||
        max_cll > 10'000 || max_fall > 10'000) {
        throw std::invalid_argument("color pipeline display settings are invalid");
    }
}

bool GradeNode::lut_representable() const noexcept {
    return type != GradeNodeType::qualifier && type != GradeNodeType::power_window;
}

bool GradeNode::render_supported() const noexcept {
    return type == GradeNodeType::primary || type == GradeNodeType::log_wheels ||
           type == GradeNodeType::rgb_mixer || type == GradeNodeType::rgb_curves ||
           type == GradeNodeType::hue_curves || type == GradeNodeType::hdr_zones ||
           type == GradeNodeType::color_warper || type == GradeNodeType::lut;
}

void GradeNode::validate() const {
    if (id.empty() || name.empty() || !std::isfinite(mix) || mix < 0.0 || mix > 1.0) {
        throw std::invalid_argument("grade node identity or mix is invalid");
    }
    for (const auto& [nameValue, value] : parameters) {
        if (nameValue.empty() || !std::isfinite(value)) {
            throw std::invalid_argument("grade node parameter is invalid");
        }
    }
    for (const auto& [curveName, points] : curves) {
        if (curveName.empty() || !std::ranges::is_sorted(points, {}, &CurvePoint::x) ||
            std::adjacent_find(points.begin(), points.end(),
                [](const CurvePoint& left, const CurvePoint& right) {
                    return left.x >= right.x;
                }) != points.end() ||
            std::ranges::any_of(points, [](const CurvePoint& point) {
                return !std::isfinite(point.x) || !std::isfinite(point.y);
            })) {
            throw std::invalid_argument("grade node curve is invalid");
        }
    }
    for (const auto& [parameterName, keyframes] : parameter_keyframes) {
        if (parameterName.empty() || !parameters.contains(parameterName) ||
            !std::ranges::is_sorted(keyframes, {}, &GradeParameterKeyframe::source_time) ||
            std::adjacent_find(keyframes.begin(), keyframes.end(),
                [](const auto& left, const auto& right) {
                    return left.source_time >= right.source_time;
                }) != keyframes.end() ||
            std::ranges::any_of(keyframes, [](const auto& keyframe) {
                return keyframe.source_time < 0 || !std::isfinite(keyframe.value);
            })) {
            throw std::invalid_argument("grade parameter keyframes are invalid");
        }
    }
    if (type == GradeNodeType::lut && external_path.empty()) {
        throw std::invalid_argument("LUT node requires a file path");
    }
    if (type == GradeNodeType::lut) {
        auto extension = std::filesystem::path{
            std::u8string(external_path.begin(), external_path.end())}.extension().string();
        std::ranges::transform(extension, extension.begin(),
            [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
        if (extension != ".cube" && extension != ".3dl" &&
            extension != ".clf" && extension != ".ctf") {
            throw std::invalid_argument("LUT node supports Cube, 3DL, CLF and CTF files");
        }
    }
}

GradeNode* GradeGraph::node(const std::string& id) noexcept {
    const auto found = std::ranges::find(nodes_, id, &GradeNode::id);
    return found == nodes_.end() ? nullptr : &*found;
}

const GradeNode* GradeGraph::node(const std::string& id) const noexcept {
    const auto found = std::ranges::find(nodes_, id, &GradeNode::id);
    return found == nodes_.end() ? nullptr : &*found;
}

void GradeGraph::add(GradeNode value) {
    value.validate();
    if (node(value.id) != nullptr) throw std::invalid_argument("duplicate grade node id");
    nodes_.push_back(std::move(value));
}

void GradeGraph::remove(const std::string& id) {
    const auto found = std::ranges::find(nodes_, id, &GradeNode::id);
    if (found == nodes_.end()) throw std::out_of_range("grade node was not found");
    nodes_.erase(found);
}

void GradeGraph::move(const std::string& id, std::size_t insertion_index) {
    if (insertion_index > nodes_.size()) throw std::out_of_range("grade node insertion is outside graph");
    const auto found = std::ranges::find(nodes_, id, &GradeNode::id);
    if (found == nodes_.end()) throw std::out_of_range("grade node was not found");
    auto value = std::move(*found);
    const auto old = static_cast<std::size_t>(std::distance(nodes_.begin(), found));
    nodes_.erase(found);
    if (insertion_index > old) --insertion_index;
    nodes_.insert(nodes_.begin() + static_cast<std::ptrdiff_t>(insertion_index), std::move(value));
}

bool GradeGraph::lut_representable() const noexcept {
    return std::ranges::all_of(nodes_, &GradeNode::lut_representable);
}

std::vector<std::string> GradeGraph::lut_incompatible_nodes() const {
    std::vector<std::string> result;
    for (const auto& value : nodes_) {
        if (!value.lut_representable()) result.push_back(value.name);
    }
    return result;
}

std::vector<std::string> GradeGraph::render_unsupported_nodes() const {
    std::vector<std::string> result;
    for (const auto& value : nodes_) {
        if (value.enabled && !value.render_supported()) result.push_back(value.name);
    }
    return result;
}

void LutExportRequest::validate(const GradeGraph& graph) const {
    if (input_space.empty() || output_space.empty() || (cube_size != 33 && cube_size != 65)) {
        throw std::invalid_argument("LUT export spaces or cube size are invalid");
    }
    if (!graph.lut_representable()) {
        throw std::invalid_argument("grade graph contains spatial nodes that cannot be baked into a LUT");
    }
}

std::string grade_node_type_name(GradeNodeType type) {
    switch (type) {
    case GradeNodeType::primary: return "Primary";
    case GradeNodeType::log_wheels: return "Log Wheels";
    case GradeNodeType::rgb_mixer: return "RGB Mixer";
    case GradeNodeType::rgb_curves: return "RGB Curves";
    case GradeNodeType::hue_curves: return "Hue Curves";
    case GradeNodeType::hdr_zones: return "HDR Zones";
    case GradeNodeType::color_warper: return "Color Warper";
    case GradeNodeType::lut: return "LUT / Look";
    case GradeNodeType::qualifier: return "Qualifier";
    case GradeNodeType::power_window: return "Power Window";
    }
    return "Color Node";
}

GradeNode make_default_grade_node(GradeNodeType type, std::string id) {
    GradeNode node;
    node.id = std::move(id);
    node.type = type;
    node.name = grade_node_type_name(type);
    if (type == GradeNodeType::primary) {
        node.parameters = {
            {"exposure", 0.0}, {"temperature", 0.0}, {"tint", 0.0},
            {"contrast", 1.0}, {"pivot", 0.435}, {"saturation", 1.0},
            {"hue", 0.0}, {"colorBoost", 0.0}, {"liftR", 0.0}, {"liftG", 0.0},
            {"liftB", 0.0}, {"gammaR", 1.0}, {"gammaG", 1.0}, {"gammaB", 1.0},
            {"gainR", 1.0}, {"gainG", 1.0}, {"gainB", 1.0},
            {"offsetR", 0.0}, {"offsetG", 0.0}, {"offsetB", 0.0}};
    } else if (type == GradeNodeType::log_wheels) {
        node.parameters = {
            {"shadowR", 0.0}, {"shadowG", 0.0}, {"shadowB", 0.0},
            {"midtoneR", 0.0}, {"midtoneG", 0.0}, {"midtoneB", 0.0},
            {"highlightR", 0.0}, {"highlightG", 0.0}, {"highlightB", 0.0},
            {"offsetR", 0.0}, {"offsetG", 0.0}, {"offsetB", 0.0},
            {"lowRange", 0.25}, {"highRange", 0.75}};
    } else if (type == GradeNodeType::rgb_mixer) {
        node.parameters = {
            {"rr", 1.0}, {"rg", 0.0}, {"rb", 0.0},
            {"gr", 0.0}, {"gg", 1.0}, {"gb", 0.0},
            {"br", 0.0}, {"bg", 0.0}, {"bb", 1.0}};
    } else if (type == GradeNodeType::rgb_curves) {
        node.curves.emplace("master", std::vector<CurvePoint>{{0.0, 0.0}, {1.0, 1.0}});
        node.curves.emplace("red", std::vector<CurvePoint>{{0.0, 0.0}, {1.0, 1.0}});
        node.curves.emplace("green", std::vector<CurvePoint>{{0.0, 0.0}, {1.0, 1.0}});
        node.curves.emplace("blue", std::vector<CurvePoint>{{0.0, 0.0}, {1.0, 1.0}});
    } else if (type == GradeNodeType::hue_curves) {
        for (const auto* name : {
                 "hueVsHue", "hueVsSat", "hueVsLum", "lumVsSat",
                 "satVsSat", "satVsLum", "lumVsLum"}) {
            node.curves.emplace(name, std::vector<CurvePoint>{{0.0, 0.0}, {1.0, 1.0}});
        }
    } else if (type == GradeNodeType::hdr_zones) {
        node.parameters = {
            {"blackExposure", 0.0}, {"shadowExposure", 0.0},
            {"midtoneExposure", 0.0}, {"highlightExposure", 0.0},
            {"specularExposure", 0.0}, {"blackCenter", -4.0},
            {"shadowCenter", -2.0}, {"midtoneCenter", 0.0},
            {"highlightCenter", 2.0}, {"specularCenter", 4.0},
            {"zoneWidth", 2.0}};
    } else if (type == GradeNodeType::color_warper) {
        for (int index = 0; index < 12; ++index) {
            node.parameters["hueShift" + std::to_string(index)] = 0.0;
            node.parameters["satScale" + std::to_string(index)] = 1.0;
        }
        for (int index = 0; index < 8; ++index) {
            node.parameters["lumScale" + std::to_string(index)] = 1.0;
        }
    }
    return node;
}

}  // namespace ffgui
