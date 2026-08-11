#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace ffgui {

struct ImagePartMetadata final {
    int subimage{};
    std::string name;
    std::string view;
    int width{};
    int height{};
    bool deep{};
    bool has_alpha{};
    std::vector<std::string> channels;
    std::vector<std::string> layers;
};

struct ImageMetadata final {
    std::filesystem::path path;
    std::string format;
    std::string color_space;
    std::vector<ImagePartMetadata> parts;
};

[[nodiscard]] ImageMetadata probe_image_metadata(const std::filesystem::path& path);

}  // namespace ffgui
