#pragma once

#include "color/color_frame_processor.hpp"

#include <memory>
#include <string>

namespace ffgui {

[[nodiscard]] bool register_gst_color_lut_filter();
void publish_gst_color_lut(std::string id, std::shared_ptr<const ColorCube> cube);
[[nodiscard]] std::shared_ptr<const ColorCube> find_published_gst_color_lut(
    const std::string& id);
void remove_gst_color_lut(const std::string& id) noexcept;

}  // namespace ffgui
