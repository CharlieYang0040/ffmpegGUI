#include "color/ocio_engine.hpp"

#include <OpenColorIO/OpenColorIO.h>

#include <algorithm>
#include <cctype>
#include <ranges>
#include <iomanip>
#include <filesystem>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace OCIO = OCIO_NAMESPACE;

namespace ffgui {
namespace {

OCIO::ConstConfigRcPtr cached_config(const ColorPipelineSettings& settings) {
    static std::mutex cacheMutex;
    static std::unordered_map<std::string, OCIO::ConstConfigRcPtr> cache;
    std::string key = "aces-studio-v4-aces2-ocio25";
    if (settings.mode == ColorPipelineMode::custom_ocio) {
        std::error_code error;
        const auto modified = std::filesystem::last_write_time(
            settings.ocio_config_path, error).time_since_epoch().count();
        key = "custom:" + settings.ocio_config_path + ':' +
            (error ? std::string{"unknown"} : std::to_string(modified));
    }
    std::scoped_lock lock(cacheMutex);
    if (const auto found = cache.find(key); found != cache.end()) return found->second;
    auto config = settings.mode == ColorPipelineMode::aces_managed
        ? OCIO::Config::CreateFromBuiltinConfig(
            "studio-config-v4.0.0_aces-v2.0_ocio-v2.5")
        : OCIO::Config::CreateFromFile(settings.ocio_config_path.c_str());
    config->validate();
    cache.emplace(std::move(key), config);
    return config;
}

}  // namespace

struct OcioEngine::Impl final {
    ColorPipelineSettings settings;
    OCIO::ConstConfigRcPtr config;
};

OcioEngine::OcioEngine(const ColorPipelineSettings& settings)
    : impl_(std::make_unique<Impl>()) {
    settings.validate();
    impl_->settings = settings;
    if (settings.mode == ColorPipelineMode::legacy) return;
    try {
        impl_->config = cached_config(settings);
    } catch (const OCIO::Exception& error) {
        throw std::runtime_error(std::string("OpenColorIO configuration failed: ") + error.what());
    }
}

OcioEngine::~OcioEngine() = default;
OcioEngine::OcioEngine(OcioEngine&&) noexcept = default;
OcioEngine& OcioEngine::operator=(OcioEngine&&) noexcept = default;

bool OcioEngine::managed() const noexcept { return static_cast<bool>(impl_->config); }

std::string OcioEngine::config_name() const {
    return managed() ? impl_->config->getName() : "Legacy";
}

std::vector<std::string> OcioEngine::color_spaces() const {
    std::vector<std::string> result;
    if (!managed()) return result;
    const auto count = impl_->config->getNumColorSpaces();
    result.reserve(static_cast<std::size_t>(count));
    for (int index = 0; index < count; ++index) {
        result.emplace_back(impl_->config->getColorSpaceNameByIndex(index));
    }
    return result;
}

void OcioEngine::transform_rgba32f(float* pixels, std::size_t width, std::size_t height,
                                   const std::string& input_space,
                                   const std::string& output_space) const {
    if (!managed()) throw std::logic_error("Legacy color mode has no OCIO processor");
    if (pixels == nullptr || width == 0 || height == 0 || input_space.empty() || output_space.empty()) {
        throw std::invalid_argument("OCIO image transform request is invalid");
    }
    try {
        const auto processor = impl_->config->getProcessor(input_space.c_str(), output_space.c_str());
        const auto cpu = processor->getDefaultCPUProcessor();
        OCIO::PackedImageDesc image(pixels, static_cast<long>(width), static_cast<long>(height),
                                    4, OCIO::BIT_DEPTH_F32, sizeof(float),
                                    4 * sizeof(float),
                                    static_cast<std::ptrdiff_t>(width * 4 * sizeof(float)));
        cpu->apply(image);
    } catch (const OCIO::Exception& error) {
        throw std::runtime_error(std::string("OpenColorIO image transform failed: ") + error.what());
    }
}

std::string OcioEngine::bake_cube(const std::string& input_space,
                                  const std::string& output_space,
                                  int cube_size) const {
    if (!managed()) throw std::logic_error("Legacy color mode cannot bake an OCIO LUT");
    if (input_space.empty() || output_space.empty() || (cube_size != 33 && cube_size != 65)) {
        throw std::invalid_argument("OCIO LUT bake request is invalid");
    }
    try {
        const auto processor = impl_->config->getProcessor(input_space.c_str(), output_space.c_str());
        const auto cpu = processor->getDefaultCPUProcessor();
        std::ostringstream output;
        output << "TITLE \"ffmpegGUI Next · " << input_space << " to " << output_space << "\"\n";
        output << "LUT_3D_SIZE " << cube_size << "\n";
        output << "DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n";
        output << std::fixed << std::setprecision(9);
        const auto maximum = static_cast<float>(cube_size - 1);
        for (int blue = 0; blue < cube_size; ++blue) {
            for (int green = 0; green < cube_size; ++green) {
                for (int red = 0; red < cube_size; ++red) {
                    float pixel[]{red / maximum, green / maximum, blue / maximum, 1.0F};
                    cpu->applyRGBA(pixel);
                    output << pixel[0] << ' ' << pixel[1] << ' ' << pixel[2] << '\n';
                }
            }
        }
        return output.str();
    } catch (const OCIO::Exception& error) {
        throw std::runtime_error(std::string("OpenColorIO LUT bake failed: ") + error.what());
    }
}

OcioGpuShader OcioEngine::gpu_shader_hlsl(
    const std::string& input_space, const std::string& output_space) const {
    if (!managed()) throw std::logic_error("Legacy color mode has no OCIO GPU shader");
    if (input_space.empty() || output_space.empty()) {
        throw std::invalid_argument("OCIO GPU shader spaces are invalid");
    }
    try {
        const auto processor = impl_->config->getProcessor(input_space.c_str(), output_space.c_str());
        const auto gpu = processor->getDefaultGPUProcessor();
        auto description = OCIO::GpuShaderDesc::CreateShaderDesc();
        description->setLanguage(OCIO::GPU_LANGUAGE_HLSL_DX11);
        description->setFunctionName("ffgui_ocio_transform");
        description->setPixelName("pixel");
        description->setResourcePrefix("ffgui_ocio_");
        gpu->extractGpuShaderInfo(description);

        OcioGpuShader result;
        result.cache_id = description->getCacheID();
        result.source = description->getShaderText();
        result.function_name = "ffgui_ocio_transform";
        for (unsigned index = 0; index < description->getNumTextures(); ++index) {
            const char* name = nullptr;
            const char* sampler = nullptr;
            unsigned width = 0;
            unsigned height = 0;
            OCIO::GpuShaderCreator::TextureType channel{};
            OCIO::GpuShaderCreator::TextureDimensions dimensions{};
            OCIO::Interpolation interpolation{};
            description->getTexture(
                index, name, sampler, width, height, channel, dimensions, interpolation);
            const float* values = nullptr;
            description->getTextureValues(index, values);
            const auto channels = channel == OCIO::GpuShaderCreator::TEXTURE_RED_CHANNEL ? 1U : 3U;
            const auto count = static_cast<std::size_t>(width) * std::max(1U, height) * channels;
            OcioGpuTexture texture;
            texture.name = name == nullptr ? "" : name;
            texture.sampler = sampler == nullptr ? "" : sampler;
            texture.width = width;
            texture.height = std::max(1U, height);
            texture.depth = 1;
            texture.channels = channels;
            texture.binding = description->getTextureShaderBindingIndex(index);
            texture.values.assign(values, values + count);
            result.textures.push_back(std::move(texture));
        }
        for (unsigned index = 0; index < description->getNum3DTextures(); ++index) {
            const char* name = nullptr;
            const char* sampler = nullptr;
            unsigned edge = 0;
            OCIO::Interpolation interpolation{};
            description->get3DTexture(index, name, sampler, edge, interpolation);
            const float* values = nullptr;
            description->get3DTextureValues(index, values);
            const auto count = static_cast<std::size_t>(edge) * edge * edge * 3;
            OcioGpuTexture texture;
            texture.name = name == nullptr ? "" : name;
            texture.sampler = sampler == nullptr ? "" : sampler;
            texture.width = edge;
            texture.height = edge;
            texture.depth = edge;
            texture.channels = 3;
            texture.binding = description->get3DTextureShaderBindingIndex(index);
            texture.values.assign(values, values + count);
            result.textures.push_back(std::move(texture));
        }
        if (result.source.empty()) throw std::runtime_error("OpenColorIO produced an empty GPU shader");
        return result;
    } catch (const OCIO::Exception& error) {
        throw std::runtime_error(std::string("OpenColorIO GPU shader generation failed: ") + error.what());
    }
}

}  // namespace ffgui
