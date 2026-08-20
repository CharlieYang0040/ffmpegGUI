#pragma once

#include "core/color_pipeline.hpp"
#include "media/oiio_frame_source.hpp"

#include <cstddef>
#include <cstdint>
#include <string>

namespace ffgui {

struct PixelInspection final {
    float red{};
    float green{};
    float blue{};
    float alpha{1.0F};
    float luma{};
    bool out_of_gamut{};
    bool valid{};
};

[[nodiscard]] float rec709_luma(float red, float green, float blue) noexcept;
[[nodiscard]] float encode_scene_scope_value(float linear) noexcept;
[[nodiscard]] bool display_out_of_gamut(float red, float green, float blue) noexcept;
[[nodiscard]] PixelInspection inspect_rgba32f(
    const float* rgba, std::size_t width, std::size_t height, std::size_t x, std::size_t y);
[[nodiscard]] PixelInspection inspect_bgra8(
    const std::uint8_t* pixels, std::size_t width, std::size_t height, std::size_t stride,
    std::size_t x, std::size_t y);

void apply_review_overlay_rgba32f(
    float* rgba, std::size_t width, std::size_t height, ReviewOverlayMode mode);
void apply_review_overlay_bgra8(
    std::uint8_t* pixels, std::size_t width, std::size_t height, std::size_t stride,
    ReviewOverlayMode mode);
void wipe_rgba32f(
    float* display, const float* bypass, std::size_t width, std::size_t height, float split = 0.5F);

[[nodiscard]] std::string format_pixel_inspection(const PixelInspection& pixel);

}  // namespace ffgui
