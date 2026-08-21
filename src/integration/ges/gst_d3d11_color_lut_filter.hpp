#pragma once

#include "color/ocio_engine.hpp"

#include <memory>
#include <string>

namespace ffgui {

[[nodiscard]] bool register_gst_d3d11_color_lut_filter();
[[nodiscard]] bool gst_d3d11_color_lut_available();
void publish_gst_d3d11_ocio_shader(
    std::string id, std::shared_ptr<const OcioGpuShader> shader);
[[nodiscard]] std::shared_ptr<const OcioGpuShader> find_published_gst_d3d11_ocio_shader(
    const std::string& id);
void remove_gst_d3d11_ocio_shader(const std::string& id) noexcept;

}  // namespace ffgui
