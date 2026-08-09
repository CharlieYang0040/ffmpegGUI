#include "media/oiio_probe.hpp"

#include <OpenImageIO/imageio.h>

#include <set>
#include <stdexcept>

namespace ffgui {

ImageMetadata probe_image_metadata(const std::filesystem::path& path) {
    auto input = OIIO::ImageInput::open(path.string());
    if (!input) throw std::runtime_error("OpenImageIO could not open the image");
    ImageMetadata result;
    result.path = std::filesystem::absolute(path);
    result.format = input->format_name();
    for (int subimage = 0;; ++subimage) {
        OIIO::ImageSpec spec;
        if (!input->seek_subimage(subimage, 0, spec)) break;
        ImagePartMetadata part;
        part.subimage = subimage;
        part.name = spec.get_string_attribute("oiio:subimagename", "part" + std::to_string(subimage));
        part.width = spec.width;
        part.height = spec.height;
        part.deep = spec.deep;
        part.has_alpha = spec.alpha_channel >= 0;
        std::set<std::string> layers;
        for (const auto& channel : spec.channelnames) {
            part.channels.push_back(channel);
            const auto separator = channel.rfind('.');
            if (separator != std::string::npos) layers.insert(channel.substr(0, separator));
        }
        part.layers.assign(layers.begin(), layers.end());
        if (result.color_space.empty()) result.color_space = spec.get_string_attribute("oiio:ColorSpace");
        result.parts.push_back(std::move(part));
    }
    input->close();
    if (result.color_space == "lin_ap1_scene") result.color_space = "ACEScg";
    if (result.parts.empty()) throw std::runtime_error("OpenImageIO found no image parts");
    return result;
}

}  // namespace ffgui
