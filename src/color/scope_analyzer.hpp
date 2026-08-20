#pragma once

#include "media/oiio_frame_source.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ffgui {

enum class ScopeReferenceStage { pre_grade, post_grade, post_display };

struct ScopeAnalysis final {
    static constexpr std::size_t histogram_bins = 256;
    static constexpr std::size_t waveform_width = 256;
    static constexpr std::size_t waveform_height = 128;
    static constexpr std::size_t vectorscope_size = 256;

    std::uint64_t serial{};
    ScopeReferenceStage stage{ScopeReferenceStage::post_display};
    bool scene_referred{};
    bool approximate{};
    std::size_t sampled_pixels{};
    std::size_t out_of_gamut_pixels{};
    float peak_luma{};
    std::array<std::array<std::uint32_t, histogram_bins>, 4> histogram{};
    std::vector<std::uint16_t> waveform;
    std::array<std::vector<std::uint16_t>, 3> rgb_parade;
    std::vector<std::uint16_t> vectorscope;
};

[[nodiscard]] ScopeAnalysis analyze_scope_bgra8(
    const std::uint8_t* pixels,
    std::size_t width,
    std::size_t height,
    std::size_t stride,
    std::uint64_t serial = 0,
    ScopeReferenceStage stage = ScopeReferenceStage::post_display,
    std::size_t maximum_samples = 230'400);

[[nodiscard]] ScopeAnalysis analyze_scope_rgba8(
    const std::uint8_t* pixels,
    std::size_t width,
    std::size_t height,
    std::size_t stride,
    std::uint64_t serial = 0,
    ScopeReferenceStage stage = ScopeReferenceStage::post_display,
    std::size_t maximum_samples = 230'400);

[[nodiscard]] ScopeAnalysis analyze_scope_float(
    const FloatImageFrame& frame,
    std::uint64_t serial = 0,
    ScopeReferenceStage stage = ScopeReferenceStage::post_display,
    std::size_t maximum_samples = 230'400);

}  // namespace ffgui
