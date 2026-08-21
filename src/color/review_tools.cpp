#include "color/review_tools.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <sstream>

namespace ffgui {
namespace {

constexpr float kLumaR = 0.2126F;
constexpr float kLumaG = 0.7152F;
constexpr float kLumaB = 0.0722F;

std::array<float, 3> false_color_from_luma(float luma) {
    struct Stop final {
        float t;
        float r;
        float g;
        float b;
    };
    static constexpr std::array<Stop, 8> stops{{
        {0.00F, 0.04F, 0.00F, 0.18F},
        {0.10F, 0.08F, 0.18F, 0.90F},
        {0.18F, 0.00F, 0.72F, 0.88F},
        {0.36F, 0.04F, 0.78F, 0.16F},
        {0.50F, 0.18F, 0.86F, 0.10F},
        {0.64F, 0.94F, 0.84F, 0.08F},
        {0.82F, 0.95F, 0.38F, 0.06F},
        {1.00F, 0.96F, 0.08F, 0.10F},
    }};
    const auto value = std::clamp(luma, 0.0F, 1.0F);
    for (std::size_t index = 1; index < stops.size(); ++index) {
        if (value <= stops[index].t) {
            const auto span = stops[index].t - stops[index - 1].t;
            const auto mix = span > 0.0F ? (value - stops[index - 1].t) / span : 1.0F;
            return {
                std::lerp(stops[index - 1].r, stops[index].r, mix),
                std::lerp(stops[index - 1].g, stops[index].g, mix),
                std::lerp(stops[index - 1].b, stops[index].b, mix)};
        }
    }
    return {stops.back().r, stops.back().g, stops.back().b};
}

void overlay_rgb(float rgb[3], ReviewOverlayMode mode) {
    if (mode == ReviewOverlayMode::gamut_warning) {
        if (!display_out_of_gamut(rgb[0], rgb[1], rgb[2])) return;
        rgb[0] = std::lerp(std::clamp(rgb[0], 0.0F, 1.0F), 1.0F, 0.72F);
        rgb[1] = std::lerp(std::clamp(rgb[1], 0.0F, 1.0F), 0.08F, 0.72F);
        rgb[2] = std::lerp(std::clamp(rgb[2], 0.0F, 1.0F), 0.72F, 0.72F);
        return;
    }
    if (mode == ReviewOverlayMode::false_color) {
        const auto color = false_color_from_luma(encode_scene_scope_value(
            rec709_luma(rgb[0], rgb[1], rgb[2])));
        rgb[0] = color[0];
        rgb[1] = color[1];
        rgb[2] = color[2];
    }
}

}  // namespace

float rec709_luma(float red, float green, float blue) noexcept {
    return red * kLumaR + green * kLumaG + blue * kLumaB;
}

float encode_scene_scope_value(float linear) noexcept {
    if (!std::isfinite(linear) || linear <= 0.0F) return 0.0F;
    constexpr float breakpoint = 0.0078125F;
    constexpr float slope = 10.5402377416545F;
    constexpr float intercept = 0.0729055341958355F;
    if (linear > breakpoint) {
        return (std::log2(linear) + 9.72F) / 17.52F;
    }
    return slope * linear + intercept;
}

bool display_out_of_gamut(float red, float green, float blue) noexcept {
    return red < -1.0e-4F || green < -1.0e-4F || blue < -1.0e-4F ||
        red > 1.0001F || green > 1.0001F || blue > 1.0001F;
}

PixelInspection inspect_rgba32f(
    const float* rgba, std::size_t width, std::size_t height, std::size_t x, std::size_t y) {
    PixelInspection result;
    if (rgba == nullptr || width == 0 || height == 0 || x >= width || y >= height) return result;
    const auto* pixel = rgba + (y * width + x) * 4;
    result.red = std::isfinite(pixel[0]) ? pixel[0] : 0.0F;
    result.green = std::isfinite(pixel[1]) ? pixel[1] : 0.0F;
    result.blue = std::isfinite(pixel[2]) ? pixel[2] : 0.0F;
    result.alpha = std::isfinite(pixel[3]) ? pixel[3] : 0.0F;
    result.luma = rec709_luma(result.red, result.green, result.blue);
    result.out_of_gamut = display_out_of_gamut(result.red, result.green, result.blue);
    result.valid = true;
    return result;
}

PixelInspection inspect_bgra8(
    const std::uint8_t* pixels, std::size_t width, std::size_t height, std::size_t stride,
    std::size_t x, std::size_t y) {
    PixelInspection result;
    if (pixels == nullptr || width == 0 || height == 0 || stride < width * 4 ||
        x >= width || y >= height) {
        return result;
    }
    const auto* pixel = pixels + y * stride + x * 4;
    result.blue = static_cast<float>(pixel[0]) / 255.0F;
    result.green = static_cast<float>(pixel[1]) / 255.0F;
    result.red = static_cast<float>(pixel[2]) / 255.0F;
    result.alpha = static_cast<float>(pixel[3]) / 255.0F;
    result.luma = rec709_luma(result.red, result.green, result.blue);
    result.out_of_gamut = pixel[0] == 0 || pixel[0] == 255 || pixel[1] == 0 || pixel[1] == 255 ||
        pixel[2] == 0 || pixel[2] == 255;
    result.valid = true;
    return result;
}

void apply_review_overlay_rgba32f(
    float* rgba, std::size_t width, std::size_t height, ReviewOverlayMode mode) {
    if (rgba == nullptr || width == 0 || height == 0 || mode == ReviewOverlayMode::off) return;
    const auto pixels = width * height;
    for (std::size_t index = 0; index < pixels; ++index) {
        overlay_rgb(rgba + index * 4, mode);
    }
}

void apply_review_overlay_bgra8(
    std::uint8_t* pixels, std::size_t width, std::size_t height, std::size_t stride,
    ReviewOverlayMode mode) {
    if (pixels == nullptr || width == 0 || height == 0 || stride < width * 4 ||
        mode == ReviewOverlayMode::off) {
        return;
    }
    for (std::size_t y = 0; y < height; ++y) {
        auto* row = pixels + y * stride;
        for (std::size_t x = 0; x < width; ++x) {
            auto* pixel = row + x * 4;
            float rgb[]{
                static_cast<float>(pixel[2]) / 255.0F,
                static_cast<float>(pixel[1]) / 255.0F,
                static_cast<float>(pixel[0]) / 255.0F};
            if (mode == ReviewOverlayMode::gamut_warning) {
                const bool clipped = pixel[0] == 0 || pixel[0] == 255 || pixel[1] == 0 ||
                    pixel[1] == 255 || pixel[2] == 0 || pixel[2] == 255;
                if (!clipped) continue;
                rgb[0] = 1.0F;
                rgb[1] = 0.08F;
                rgb[2] = 0.72F;
            } else {
                overlay_rgb(rgb, mode);
            }
            pixel[0] = static_cast<std::uint8_t>(std::lround(std::clamp(rgb[2], 0.0F, 1.0F) * 255.0F));
            pixel[1] = static_cast<std::uint8_t>(std::lround(std::clamp(rgb[1], 0.0F, 1.0F) * 255.0F));
            pixel[2] = static_cast<std::uint8_t>(std::lround(std::clamp(rgb[0], 0.0F, 1.0F) * 255.0F));
        }
    }
}

void wipe_rgba32f(
    float* display, const float* bypass, std::size_t width, std::size_t height, float split) {
    if (display == nullptr || bypass == nullptr || width == 0 || height == 0) return;
    const auto cut = static_cast<std::size_t>(std::lround(
        std::clamp(split, 0.0F, 1.0F) * static_cast<float>(width)));
    for (std::size_t y = 0; y < height; ++y) {
        for (std::size_t x = 0; x < cut; ++x) {
            const auto index = (y * width + x) * 4;
            display[index] = bypass[index];
            display[index + 1] = bypass[index + 1];
            display[index + 2] = bypass[index + 2];
            display[index + 3] = bypass[index + 3];
        }
    }
}

std::string format_pixel_inspection(const PixelInspection& pixel) {
    if (!pixel.valid) return {};
    std::ostringstream text;
    text << std::fixed << std::setprecision(3)
         << "R " << pixel.red << "  G " << pixel.green << "  B " << pixel.blue
         << "  Y " << pixel.luma;
    if (pixel.out_of_gamut) text << "  · 범위 초과";
    return text.str();
}

}  // namespace ffgui
