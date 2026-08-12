#include "color/scope_analyzer.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace ffgui {
namespace {

constexpr std::array<float, 3> displayLuma{0.2126F, 0.7152F, 0.0722F};

std::uint8_t quantize(float value) {
    return static_cast<std::uint8_t>(std::lround(
        std::clamp(std::isfinite(value) ? value : 0.0F, 0.0F, 1.0F) * 255.0F));
}

void increment(std::vector<std::uint16_t>& values, std::size_t index) {
    if (values[index] != std::numeric_limits<std::uint16_t>::max()) ++values[index];
}

class ScopeAccumulator final {
public:
    ScopeAccumulator(
        std::size_t source_width, std::size_t source_height,
        std::uint64_t serial, ScopeReferenceStage stage, std::size_t maximum_samples)
        : source_width_(source_width), source_height_(source_height) {
        if (source_width == 0 || source_height == 0 || maximum_samples == 0) {
            throw std::invalid_argument("scope dimensions or sample budget are invalid");
        }
        result_.serial = serial;
        result_.stage = stage;
        result_.waveform.assign(
            ScopeAnalysis::waveform_width * ScopeAnalysis::waveform_height, 0);
        for (auto& channel : result_.rgb_parade) {
            channel.assign(
                ScopeAnalysis::waveform_width * ScopeAnalysis::waveform_height, 0);
        }
        result_.vectorscope.assign(
            ScopeAnalysis::vectorscope_size * ScopeAnalysis::vectorscope_size, 0);
        const auto total = source_width * source_height;
        step_ = total <= maximum_samples ? 1 :
            static_cast<std::size_t>(std::ceil(
                std::sqrt(static_cast<double>(total) / maximum_samples)));
    }

    [[nodiscard]] std::size_t step() const noexcept { return step_; }

    void add(std::size_t x, const std::array<float, 3>& rgb) {
        const auto red = quantize(rgb[0]);
        const auto green = quantize(rgb[1]);
        const auto blue = quantize(rgb[2]);
        const auto lumaValue = std::clamp(
            rgb[0] * displayLuma[0] + rgb[1] * displayLuma[1] + rgb[2] * displayLuma[2],
            0.0F, 1.0F);
        const auto luma = quantize(lumaValue);
        ++result_.histogram[0][red];
        ++result_.histogram[1][green];
        ++result_.histogram[2][blue];
        ++result_.histogram[3][luma];

        const auto scopeX = (std::min(x, source_width_ - 1) *
            (ScopeAnalysis::waveform_width - 1)) / (source_width_ - (source_width_ > 1 ? 1 : 0));
        const auto waveY = ScopeAnalysis::waveform_height - 1 -
            (static_cast<std::size_t>(luma) * (ScopeAnalysis::waveform_height - 1) / 255);
        increment(result_.waveform, waveY * ScopeAnalysis::waveform_width + scopeX);
        const std::array<std::uint8_t, 3> channels{red, green, blue};
        for (std::size_t channel = 0; channel < channels.size(); ++channel) {
            const auto y = ScopeAnalysis::waveform_height - 1 -
                (static_cast<std::size_t>(channels[channel]) *
                    (ScopeAnalysis::waveform_height - 1) / 255);
            increment(result_.rgb_parade[channel],
                      y * ScopeAnalysis::waveform_width + scopeX);
        }

        const auto cb = std::clamp(
            0.5F + (rgb[2] - lumaValue) / (2.0F * (1.0F - displayLuma[2])),
            0.0F, 1.0F);
        const auto cr = std::clamp(
            0.5F + (rgb[0] - lumaValue) / (2.0F * (1.0F - displayLuma[0])),
            0.0F, 1.0F);
        const auto vectorX = static_cast<std::size_t>(std::lround(
            cb * static_cast<float>(ScopeAnalysis::vectorscope_size - 1)));
        const auto vectorY = ScopeAnalysis::vectorscope_size - 1 -
            static_cast<std::size_t>(std::lround(
                cr * static_cast<float>(ScopeAnalysis::vectorscope_size - 1)));
        increment(result_.vectorscope,
                  vectorY * ScopeAnalysis::vectorscope_size + vectorX);
        ++result_.sampled_pixels;
    }

    [[nodiscard]] ScopeAnalysis finish() && { return std::move(result_); }

private:
    std::size_t source_width_{};
    std::size_t source_height_{};
    std::size_t step_{1};
    ScopeAnalysis result_;
};

}  // namespace

static ScopeAnalysis analyze_scope_8bit(
    const std::uint8_t* pixels,
    std::size_t width,
    std::size_t height,
    std::size_t stride,
    std::uint64_t serial,
    ScopeReferenceStage stage,
    std::size_t maximum_samples,
    bool bgra) {
    if (pixels == nullptr || width == 0 || height == 0 || stride < width * 4) {
        throw std::invalid_argument("8-bit scope frame storage is invalid");
    }
    ScopeAccumulator accumulator(width, height, serial, stage, maximum_samples);
    const auto step = accumulator.step();
    for (std::size_t y = 0; y < height; y += step) {
        const auto* row = pixels + y * stride;
        for (std::size_t x = 0; x < width; x += step) {
            const auto* pixel = row + x * 4;
            accumulator.add(x, {
                static_cast<float>(pixel[bgra ? 2 : 0]) / 255.0F,
                static_cast<float>(pixel[1]) / 255.0F,
                static_cast<float>(pixel[bgra ? 0 : 2]) / 255.0F});
        }
    }
    return std::move(accumulator).finish();
}

ScopeAnalysis analyze_scope_bgra8(
    const std::uint8_t* pixels,
    std::size_t width,
    std::size_t height,
    std::size_t stride,
    std::uint64_t serial,
    ScopeReferenceStage stage,
    std::size_t maximum_samples) {
    return analyze_scope_8bit(
        pixels, width, height, stride, serial, stage, maximum_samples, true);
}

ScopeAnalysis analyze_scope_rgba8(
    const std::uint8_t* pixels,
    std::size_t width,
    std::size_t height,
    std::size_t stride,
    std::uint64_t serial,
    ScopeReferenceStage stage,
    std::size_t maximum_samples) {
    return analyze_scope_8bit(
        pixels, width, height, stride, serial, stage, maximum_samples, false);
}

ScopeAnalysis analyze_scope_float(
    const FloatImageFrame& frame,
    std::uint64_t serial,
    ScopeReferenceStage stage,
    std::size_t maximum_samples) {
    if (frame.width <= 0 || frame.height <= 0 || frame.rgba.size() !=
            static_cast<std::size_t>(frame.width) * frame.height * 4) {
        throw std::invalid_argument("float scope frame storage is invalid");
    }
    ScopeAccumulator accumulator(
        static_cast<std::size_t>(frame.width), static_cast<std::size_t>(frame.height),
        serial, stage, maximum_samples);
    const auto step = accumulator.step();
    for (std::size_t y = 0; y < static_cast<std::size_t>(frame.height); y += step) {
        for (std::size_t x = 0; x < static_cast<std::size_t>(frame.width); x += step) {
            const auto index = (y * static_cast<std::size_t>(frame.width) + x) * 4;
            accumulator.add(x, {frame.rgba[index], frame.rgba[index + 1], frame.rgba[index + 2]});
        }
    }
    return std::move(accumulator).finish();
}

}  // namespace ffgui
