#pragma once

#include <cstddef>
#include <filesystem>
#include <list>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace ffgui {

struct FloatImageFrame final {
    int width{};
    int height{};
    int source_subimage{};
    std::string source_part;
    std::string color_space;
    bool premultiplied{};
    std::vector<std::string> source_channels;
    std::vector<float> rgba;

    [[nodiscard]] std::size_t byte_size() const noexcept {
        return rgba.size() * sizeof(float);
    }
};

struct ImageFrameRequest final {
    std::filesystem::path path;
    std::string part;
    std::vector<std::string> channel_mapping{"R", "G", "B", "A"};
};

[[nodiscard]] FloatImageFrame read_float_image_frame(const ImageFrameRequest& request);
void write_selected_exr_frame(
    const ImageFrameRequest& request, const std::filesystem::path& output_path);

class ImageFrameCache final {
public:
    explicit ImageFrameCache(std::size_t maximum_bytes = 512ULL * 1024ULL * 1024ULL);
    [[nodiscard]] std::shared_ptr<const FloatImageFrame> get(const ImageFrameRequest& request);
    void invalidate(const std::filesystem::path& path);
    void clear();
    [[nodiscard]] std::size_t byte_size() const noexcept;
    [[nodiscard]] std::size_t entry_count() const noexcept;

private:
    struct Entry final {
        std::shared_ptr<const FloatImageFrame> frame;
        std::list<std::string>::iterator recency;
        std::filesystem::path source_path;
    };

    [[nodiscard]] static std::string key_for(const ImageFrameRequest& request);
    void evict_to_budget();

    std::size_t maximum_bytes_{};
    std::size_t bytes_{};
    mutable std::mutex mutex_;
    std::list<std::string> recency_;
    std::unordered_map<std::string, Entry> entries_;
};

}  // namespace ffgui
