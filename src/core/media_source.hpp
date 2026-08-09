#pragma once

#include "core/time.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace ffgui {

enum class MediaKind { video, animated_image, still_image, image_sequence };

struct RationalFrameRate final {
    int numerator{24};
    int denominator{1};

    bool operator==(const RationalFrameRate&) const = default;
    [[nodiscard]] double value() const noexcept;
    [[nodiscard]] TimeNs frame_duration() const;
};

struct SourceColorDescriptor final {
    std::string input_color_space;
    std::string primaries;
    std::string transfer;
    std::string matrix;
    std::string range;
    std::string icc_profile;
    bool unresolved{};

    bool operator==(const SourceColorDescriptor&) const = default;
};

struct ImageSequenceDescriptor final {
    std::filesystem::path directory;
    std::string prefix;
    std::string suffix;
    int padding{};
    int first_frame{};
    int last_frame{};
    RationalFrameRate frame_rate{};
    std::vector<int> present_frames;
    std::vector<int> missing_frames;
    std::string exr_part;
    std::string exr_view;
    std::string exr_layer;
    bool deep{};
    std::vector<std::string> available_parts;
    std::vector<std::string> available_layers;
    std::vector<std::string> available_channels;
    std::vector<std::string> channel_mapping{"R", "G", "B", "A"};

    bool operator==(const ImageSequenceDescriptor&) const = default;
    [[nodiscard]] std::size_t frame_count() const noexcept;
    [[nodiscard]] bool has_frame(int frame) const noexcept;
    [[nodiscard]] int nearest_present_frame(int frame) const;
    [[nodiscard]] std::filesystem::path frame_path(int frame) const;
};

[[nodiscard]] bool is_supported_still_extension(const std::filesystem::path& path);
[[nodiscard]] bool is_exr_extension(const std::filesystem::path& path);
[[nodiscard]] std::optional<ImageSequenceDescriptor> detect_image_sequence(
    const std::filesystem::path& selected,
    RationalFrameRate default_frame_rate = {});

}  // namespace ffgui
