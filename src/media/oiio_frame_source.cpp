#include "media/oiio_frame_source.hpp"

#include <OpenImageIO/imageio.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <ranges>
#include <sstream>
#include <stdexcept>

namespace ffgui {
namespace {

std::size_t channel_index(const OIIO::ImageSpec& spec, const std::string& requested) {
    const auto exact = std::ranges::find(spec.channelnames, requested);
    if (exact != spec.channelnames.end()) {
        return static_cast<std::size_t>(std::distance(spec.channelnames.begin(), exact));
    }
    const auto separator = requested.rfind('.');
    const auto leaf = separator == std::string::npos ? requested : requested.substr(separator + 1);
    const auto fallback = std::ranges::find(spec.channelnames, leaf);
    return fallback == spec.channelnames.end()
        ? static_cast<std::size_t>(spec.nchannels)
        : static_cast<std::size_t>(std::distance(spec.channelnames.begin(), fallback));
}

}  // namespace

FloatImageFrame read_float_image_frame(const ImageFrameRequest& request) {
    if (request.path.empty() || request.channel_mapping.size() != 4) {
        throw std::invalid_argument("image frame request requires a path and RGBA mapping");
    }
    auto input = OIIO::ImageInput::open(request.path.string());
    if (!input) throw std::runtime_error("OpenImageIO could not open the image frame");

    int selected = -1;
    OIIO::ImageSpec spec;
    std::string discoveredParts;
    for (int subimage = 0;; ++subimage) {
        OIIO::ImageSpec candidate;
        if (subimage == 0) candidate = input->spec();
        else if (!input->seek_subimage(subimage, 0, candidate)) break;
        std::string name = candidate.get_string_attribute("oiio:subimagename");
        if (name.empty()) name = "part" + std::to_string(subimage);
        if (!discoveredParts.empty()) discoveredParts += ",";
        discoveredParts += name;
        if (request.part.empty() || request.part == name) {
            selected = subimage;
            spec = std::move(candidate);
            break;
        }
    }
    if (selected < 0) {
        input->close();
        throw std::invalid_argument(
            "requested image part was not found: " + request.part + " (available: " +
            discoveredParts + ")");
    }
    if (spec.deep) {
        input->close();
        throw std::invalid_argument("deep images are not supported by the flat frame source");
    }
    if (spec.width <= 0 || spec.height <= 0 || spec.nchannels <= 0) {
        input->close();
        throw std::runtime_error("image frame dimensions or channels are invalid");
    }

    const auto pixelCount = static_cast<std::size_t>(spec.width) * spec.height;
    std::vector<float> source(pixelCount * static_cast<std::size_t>(spec.nchannels));
    if (!input->read_image(selected, 0, 0, spec.nchannels, OIIO::span<float>(source))) {
        const auto error = input->geterror();
        input->close();
        throw std::runtime_error(error.empty() ? "OpenImageIO frame read failed" : error);
    }
    input->close();

    std::array<std::size_t, 4> mapped{};
    for (std::size_t index = 0; index < mapped.size(); ++index) {
        mapped[index] = channel_index(spec, request.channel_mapping[index]);
    }
    FloatImageFrame result;
    result.width = spec.width;
    result.height = spec.height;
    result.source_subimage = selected;
    result.source_part = spec.get_string_attribute("oiio:subimagename");
    if (result.source_part.empty()) result.source_part = "part" + std::to_string(selected);
    result.color_space = spec.get_string_attribute("oiio:ColorSpace");
    if (result.color_space == "lin_ap1_scene") result.color_space = "ACEScg";
    result.premultiplied = spec.alpha_channel >= 0 &&
        spec.get_int_attribute("oiio:UnassociatedAlpha", 0) == 0;
    result.source_channels = request.channel_mapping;
    result.rgba.resize(pixelCount * 4);
    for (std::size_t pixel = 0; pixel < pixelCount; ++pixel) {
        for (std::size_t channel = 0; channel < 4; ++channel) {
            result.rgba[pixel * 4 + channel] = mapped[channel] < static_cast<std::size_t>(spec.nchannels)
                ? source[pixel * static_cast<std::size_t>(spec.nchannels) + mapped[channel]]
                : channel == 3 ? 1.0F : 0.0F;
        }
    }
    return result;
}

void write_selected_exr_frame(
    const ImageFrameRequest& request, const std::filesystem::path& output_path) {
    const auto frame = read_float_image_frame(request);
    OIIO::ImageSpec spec(frame.width, frame.height, 4, OIIO::TypeDesc::HALF);
    spec.channelnames = {"R", "G", "B", "A"};
    spec.alpha_channel = 3;
    if (!frame.color_space.empty()) spec.attribute("oiio:ColorSpace", frame.color_space);
    auto output = OIIO::ImageOutput::create(output_path.string());
    if (!output || !output->open(output_path.string(), spec) ||
        !output->write_image(OIIO::TypeDesc::FLOAT, frame.rgba.data()) || !output->close()) {
        throw std::runtime_error("selected EXR AOV frame could not be written");
    }
}

ImageFrameCache::ImageFrameCache(std::size_t maximum_bytes) : maximum_bytes_(maximum_bytes) {
    if (maximum_bytes_ == 0) throw std::invalid_argument("image frame cache budget must be positive");
}

std::string ImageFrameCache::key_for(const ImageFrameRequest& request) {
    std::ostringstream key;
    const auto absolute = std::filesystem::absolute(request.path);
    key << absolute.string() << '|' << request.part;
    for (const auto& channel : request.channel_mapping) key << '|' << channel;
    std::error_code error;
    const auto size = std::filesystem::file_size(absolute, error);
    if (!error) key << "|s=" << size;
    const auto modified = std::filesystem::last_write_time(absolute, error);
    if (!error) key << "|t=" << modified.time_since_epoch().count();
    return key.str();
}

std::shared_ptr<const FloatImageFrame> ImageFrameCache::get(const ImageFrameRequest& request) {
    const auto key = key_for(request);
    {
        std::scoped_lock lock(mutex_);
        const auto found = entries_.find(key);
        if (found != entries_.end()) {
            recency_.splice(recency_.begin(), recency_, found->second.recency);
            return found->second.frame;
        }
    }
    auto loaded = std::make_shared<const FloatImageFrame>(read_float_image_frame(request));
    std::scoped_lock lock(mutex_);
    const auto existing = entries_.find(key);
    if (existing != entries_.end()) return existing->second.frame;
    recency_.push_front(key);
    bytes_ += loaded->byte_size();
    entries_.emplace(key, Entry{loaded, recency_.begin(), std::filesystem::absolute(request.path)});
    evict_to_budget();
    return loaded;
}

void ImageFrameCache::evict_to_budget() {
    while (bytes_ > maximum_bytes_ && entries_.size() > 1) {
        const auto key = recency_.back();
        const auto found = entries_.find(key);
        bytes_ -= found->second.frame->byte_size();
        entries_.erase(found);
        recency_.pop_back();
    }
}

void ImageFrameCache::invalidate(const std::filesystem::path& path) {
    const auto absolute = std::filesystem::absolute(path);
    std::scoped_lock lock(mutex_);
    for (auto it = entries_.begin(); it != entries_.end();) {
        if (it->second.source_path == absolute) {
            bytes_ -= it->second.frame->byte_size();
            recency_.erase(it->second.recency);
            it = entries_.erase(it);
        } else ++it;
    }
}

void ImageFrameCache::clear() {
    std::scoped_lock lock(mutex_);
    entries_.clear();
    recency_.clear();
    bytes_ = 0;
}

std::size_t ImageFrameCache::byte_size() const noexcept {
    std::scoped_lock lock(mutex_);
    return bytes_;
}

std::size_t ImageFrameCache::entry_count() const noexcept {
    std::scoped_lock lock(mutex_);
    return entries_.size();
}

}  // namespace ffgui
