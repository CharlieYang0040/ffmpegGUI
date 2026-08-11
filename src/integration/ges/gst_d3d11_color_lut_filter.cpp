#include "integration/ges/gst_d3d11_color_lut_filter.hpp"

#include "integration/ges/gst_color_lut_filter.hpp"

#define GST_USE_UNSTABLE_API
#include <gst/base/gstbasetransform.h>
#include <gst/d3d11/gstd3d11.h>
#include <gst/video/video.h>

#include <d3dcompiler.h>

#include <cstdint>
#include <algorithm>
#include <memory>
#include <mutex>
#include <ranges>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

constexpr const char* vertexShaderSource = R"(
struct VertexOutput {
    float4 position : SV_Position;
    float2 uv : TEXCOORD0;
};
VertexOutput main(uint vertexId : SV_VertexID) {
    VertexOutput result;
    result.uv = float2((vertexId << 1) & 2, vertexId & 2);
    result.position = float4(result.uv.x * 2.0 - 1.0,
                             1.0 - result.uv.y * 2.0, 0.0, 1.0);
    return result;
})";

constexpr const char* pixelShaderSource = R"(
Texture2D<float4> sourceTexture : register(t0);
Texture3D<float4> colorCube : register(t1);
SamplerState linearSampler : register(s0);
float4 main(float4 position : SV_Position, float2 uv : TEXCOORD0) : SV_Target {
    float4 source = sourceTexture.Sample(linearSampler, uv);
    float3 transformed = colorCube.Sample(linearSampler, saturate(source.rgb)).rgb;
    return float4(transformed, source.a);
})";

std::mutex shaderRegistryMutex;
std::unordered_map<std::string, std::shared_ptr<const ffgui::OcioGpuShader>> shaderRegistry;

std::shared_ptr<const ffgui::OcioGpuShader> find_shader(const char* id) {
    if (id == nullptr || *id == '\0') return {};
    std::scoped_lock lock(shaderRegistryMutex);
    const auto found = shaderRegistry.find(id);
    return found == shaderRegistry.end() ? nullptr : found->second;
}

template <typename T>
void release_com(T*& value) noexcept {
    if (value != nullptr) value->Release();
    value = nullptr;
}

struct OcioResourceState final {
    std::mutex mutex;
    std::vector<ID3D11Resource*> textures;
    std::vector<ID3D11ShaderResourceView*> views;
    std::vector<ID3D11SamplerState*> samplers;
    std::vector<unsigned> texture_bindings;
    std::vector<unsigned> sampler_bindings;
};

struct GstFfguiD3D11Lut final {
    GstBaseTransform parent;
    gchar* lut_id{};
    gchar* shader_id{};
    GstVideoInfo info{};
    GstD3D11Device* device{};
    std::shared_ptr<const ffgui::ColorCube>* cube{};
    std::shared_ptr<const ffgui::OcioGpuShader>* ocio_shader{};
    ID3D11VertexShader* vertex_shader{};
    ID3D11PixelShader* pixel_shader{};
    ID3D11SamplerState* sampler{};
    ID3D11BlendState* blend_state{};
    ID3D11Texture3D* lut_texture{};
    ID3D11ShaderResourceView* lut_view{};
    OcioResourceState* ocio_resources{};
};

struct GstFfguiD3D11LutClass final { GstBaseTransformClass parent_class; };

G_DEFINE_TYPE(GstFfguiD3D11Lut, gst_ffgui_d3d11_lut, GST_TYPE_BASE_TRANSFORM)

enum { property_zero, property_lut_id, property_shader_id };

void release_gpu_resources(GstFfguiD3D11Lut* self) noexcept {
    if (self->ocio_resources != nullptr) {
        for (auto*& value : self->ocio_resources->samplers) release_com(value);
        for (auto*& value : self->ocio_resources->views) release_com(value);
        for (auto*& value : self->ocio_resources->textures) release_com(value);
        self->ocio_resources->samplers.clear();
        self->ocio_resources->views.clear();
        self->ocio_resources->textures.clear();
        self->ocio_resources->texture_bindings.clear();
        self->ocio_resources->sampler_bindings.clear();
    }
    release_com(self->lut_view);
    release_com(self->lut_texture);
    release_com(self->sampler);
    release_com(self->blend_state);
    release_com(self->pixel_shader);
    release_com(self->vertex_shader);
}

bool create_ocio_texture(
    ID3D11Device* device, const ffgui::OcioGpuTexture& texture,
    ID3D11Resource** resource, ID3D11ShaderResourceView** view) {
    if (device == nullptr || resource == nullptr || view == nullptr ||
        texture.width == 0 || texture.height == 0 || texture.depth == 0 ||
        (texture.channels != 1 && texture.channels != 3) ||
        texture.dimensions < 1 || texture.dimensions > 3 ||
        (texture.dimensions == 1 && (texture.height != 1 || texture.depth != 1)) ||
        (texture.dimensions == 2 && texture.depth != 1)) return false;
    const auto texelCount = static_cast<std::size_t>(texture.width) * texture.height *
        texture.depth;
    if (texture.values.size() != texelCount * texture.channels) return false;
    std::vector<float> expanded;
    const float* pixels = texture.values.data();
    auto bytesPerTexel = sizeof(float);
    auto format = DXGI_FORMAT_R32_FLOAT;
    if (texture.channels == 3) {
        expanded.resize(texelCount * 4);
        for (std::size_t input = 0, output = 0; input < texture.values.size(); input += 3) {
            expanded[output++] = texture.values[input];
            expanded[output++] = texture.values[input + 1];
            expanded[output++] = texture.values[input + 2];
            expanded[output++] = 1.0F;
        }
        pixels = expanded.data();
        bytesPerTexel = 4 * sizeof(float);
        format = DXGI_FORMAT_R32G32B32A32_FLOAT;
    }
    D3D11_SUBRESOURCE_DATA initial{};
    initial.pSysMem = pixels;
    initial.SysMemPitch = static_cast<UINT>(texture.width * bytesPerTexel);
    initial.SysMemSlicePitch = static_cast<UINT>(
        static_cast<std::size_t>(texture.width) * texture.height * bytesPerTexel);
    HRESULT hr = E_FAIL;
    if (texture.dimensions == 1) {
        D3D11_TEXTURE1D_DESC description{};
        description.Width = texture.width;
        description.MipLevels = 1;
        description.ArraySize = 1;
        description.Format = format;
        description.Usage = D3D11_USAGE_IMMUTABLE;
        description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture1D* value = nullptr;
        hr = device->CreateTexture1D(&description, &initial, &value);
        *resource = value;
    } else if (texture.dimensions == 2) {
        D3D11_TEXTURE2D_DESC description{};
        description.Width = texture.width;
        description.Height = texture.height;
        description.MipLevels = 1;
        description.ArraySize = 1;
        description.Format = format;
        description.SampleDesc.Count = 1;
        description.Usage = D3D11_USAGE_IMMUTABLE;
        description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture2D* value = nullptr;
        hr = device->CreateTexture2D(&description, &initial, &value);
        *resource = value;
    } else {
        D3D11_TEXTURE3D_DESC description{};
        description.Width = texture.width;
        description.Height = texture.height;
        description.Depth = texture.depth;
        description.MipLevels = 1;
        description.Format = format;
        description.Usage = D3D11_USAGE_IMMUTABLE;
        description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture3D* value = nullptr;
        hr = device->CreateTexture3D(&description, &initial, &value);
        *resource = value;
    }
    if (FAILED(hr) || *resource == nullptr) return false;
    hr = device->CreateShaderResourceView(*resource, nullptr, view);
    return SUCCEEDED(hr);
}

std::string ocio_pixel_shader_source(const ffgui::OcioGpuShader& shader) {
    std::ostringstream source;
    source << "Texture2D<float4> ffgui_source_texture;\n"
              "SamplerState ffgui_source_sampler;\n"
           << shader.source << '\n'
           << "float4 main(float4 position : SV_Position, float2 uv : TEXCOORD0) : SV_Target {\n"
              "  float4 source = ffgui_source_texture.Sample(ffgui_source_sampler, uv);\n"
              "  float4 transformed = " << shader.function_name
           << "(float4(source.rgb, 1.0));\n"
              "  return float4(transformed.rgb, source.a);\n"
              "}\n";
    return source.str();
}

bool create_gpu_resources(GstFfguiD3D11Lut* self) {
    if (self->ocio_resources == nullptr) return false;
    std::scoped_lock resourceLock(self->ocio_resources->mutex);
    release_gpu_resources(self);
    if (self->device == nullptr) return false;
    const auto hasOcio = self->ocio_shader != nullptr && *self->ocio_shader;
    const auto hasCube = self->cube != nullptr && *self->cube;
    if (!hasOcio && !hasCube) return false;
    if (hasOcio && hasCube) return false;
    const auto* cube = hasCube ? self->cube->get() : nullptr;
    if (cube != nullptr && (cube->size < 2 || cube->rgb.size() !=
            static_cast<std::size_t>(cube->size) * cube->size * cube->size * 3)) return false;

    auto* device = gst_d3d11_device_get_device_handle(self->device);
    ID3DBlob* vertexCode = nullptr;
    ID3DBlob* pixelCode = nullptr;
    ID3DBlob* errors = nullptr;
    auto hr = gst_d3d11_compile(
        vertexShaderSource, std::char_traits<char>::length(vertexShaderSource),
        "ffgui-lut-vs", nullptr, nullptr, "main", "vs_5_0", 0, 0,
        &vertexCode, &errors);
    release_com(errors);
    if (FAILED(hr)) return false;
    hr = device->CreateVertexShader(
        vertexCode->GetBufferPointer(), vertexCode->GetBufferSize(), nullptr,
        &self->vertex_shader);
    release_com(vertexCode);
    if (FAILED(hr)) return false;
    const auto dynamicPixelSource = hasOcio
        ? ocio_pixel_shader_source(**self->ocio_shader) : std::string{pixelShaderSource};
    hr = gst_d3d11_compile(
        dynamicPixelSource.c_str(), dynamicPixelSource.size(),
        "ffgui-lut-ps", nullptr, nullptr, "main", "ps_5_0", 0, 0,
        &pixelCode, &errors);
    release_com(errors);
    if (FAILED(hr)) return false;
    hr = device->CreatePixelShader(
        pixelCode->GetBufferPointer(), pixelCode->GetBufferSize(), nullptr,
        &self->pixel_shader);
    if (FAILED(hr)) {
        release_com(pixelCode);
        return false;
    }
    std::vector<std::pair<unsigned, unsigned>> reflectedBindings;
    if (hasOcio) {
        ID3D11ShaderReflection* reflection = nullptr;
        hr = D3DReflect(pixelCode->GetBufferPointer(), pixelCode->GetBufferSize(),
                        IID_ID3D11ShaderReflection,
                        reinterpret_cast<void**>(&reflection));
        if (FAILED(hr) || reflection == nullptr) {
            release_com(pixelCode);
            release_com(reflection);
            return false;
        }
        D3D11_SHADER_INPUT_BIND_DESC sourceTexture{};
        D3D11_SHADER_INPUT_BIND_DESC sourceSampler{};
        const auto sourceValid = SUCCEEDED(reflection->GetResourceBindingDescByName(
                "ffgui_source_texture", &sourceTexture)) && sourceTexture.BindPoint == 0 &&
            SUCCEEDED(reflection->GetResourceBindingDescByName(
                "ffgui_source_sampler", &sourceSampler)) && sourceSampler.BindPoint == 0;
        if (!sourceValid) {
            release_com(reflection);
            release_com(pixelCode);
            return false;
        }
        reflectedBindings.reserve((**self->ocio_shader).textures.size());
        for (const auto& texture : (**self->ocio_shader).textures) {
            D3D11_SHADER_INPUT_BIND_DESC textureBinding{};
            D3D11_SHADER_INPUT_BIND_DESC samplerBinding{};
            if (FAILED(reflection->GetResourceBindingDescByName(
                    texture.name.c_str(), &textureBinding)) ||
                FAILED(reflection->GetResourceBindingDescByName(
                    texture.sampler.c_str(), &samplerBinding)) ||
                textureBinding.BindPoint == 0 || samplerBinding.BindPoint == 0 ||
                textureBinding.BindPoint >= D3D11_COMMONSHADER_INPUT_RESOURCE_SLOT_COUNT ||
                samplerBinding.BindPoint >= D3D11_COMMONSHADER_SAMPLER_SLOT_COUNT) {
                release_com(reflection);
                release_com(pixelCode);
                return false;
            }
            reflectedBindings.emplace_back(
                textureBinding.BindPoint, samplerBinding.BindPoint);
        }
        release_com(reflection);
    }
    release_com(pixelCode);

    D3D11_SAMPLER_DESC samplerDescription{};
    samplerDescription.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    samplerDescription.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
    samplerDescription.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
    samplerDescription.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    samplerDescription.MaxLOD = D3D11_FLOAT32_MAX;
    hr = device->CreateSamplerState(&samplerDescription, &self->sampler);
    if (FAILED(hr)) return false;
    D3D11_BLEND_DESC blendDescription{};
    blendDescription.RenderTarget[0].BlendEnable = FALSE;
    blendDescription.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    hr = device->CreateBlendState(&blendDescription, &self->blend_state);
    if (FAILED(hr)) return false;

    if (hasOcio) {
        const auto& textures = (**self->ocio_shader).textures;
        for (std::size_t index = 0; index < textures.size(); ++index) {
            const auto& texture = textures[index];
            const auto [textureBinding, samplerBinding] = reflectedBindings[index];
            if (std::ranges::find(self->ocio_resources->texture_bindings, textureBinding) !=
                    self->ocio_resources->texture_bindings.end() ||
                std::ranges::find(self->ocio_resources->sampler_bindings, samplerBinding) !=
                    self->ocio_resources->sampler_bindings.end()) return false;
            ID3D11Resource* resource = nullptr;
            ID3D11ShaderResourceView* view = nullptr;
            if (!create_ocio_texture(device, texture, &resource, &view)) {
                release_com(resource);
                release_com(view);
                return false;
            }
            D3D11_SAMPLER_DESC ocioSamplerDescription = samplerDescription;
            ocioSamplerDescription.Filter = texture.nearest
                ? D3D11_FILTER_MIN_MAG_MIP_POINT : D3D11_FILTER_MIN_MAG_MIP_LINEAR;
            ID3D11SamplerState* ocioSampler = nullptr;
            if (FAILED(device->CreateSamplerState(&ocioSamplerDescription, &ocioSampler))) {
                release_com(view);
                release_com(resource);
                return false;
            }
            self->ocio_resources->textures.push_back(resource);
            self->ocio_resources->views.push_back(view);
            self->ocio_resources->samplers.push_back(ocioSampler);
            self->ocio_resources->texture_bindings.push_back(textureBinding);
            self->ocio_resources->sampler_bindings.push_back(samplerBinding);
        }
        return true;
    }

    std::vector<float> rgba;
    rgba.resize(static_cast<std::size_t>(cube->size) * cube->size * cube->size * 4);
    for (std::size_t index = 0, output = 0; index < cube->rgb.size(); index += 3) {
        rgba[output++] = cube->rgb[index];
        rgba[output++] = cube->rgb[index + 1];
        rgba[output++] = cube->rgb[index + 2];
        rgba[output++] = 1.0F;
    }
    D3D11_TEXTURE3D_DESC textureDescription{};
    textureDescription.Width = static_cast<UINT>(cube->size);
    textureDescription.Height = static_cast<UINT>(cube->size);
    textureDescription.Depth = static_cast<UINT>(cube->size);
    textureDescription.MipLevels = 1;
    textureDescription.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
    textureDescription.Usage = D3D11_USAGE_IMMUTABLE;
    textureDescription.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA textureData{};
    textureData.pSysMem = rgba.data();
    textureData.SysMemPitch = static_cast<UINT>(cube->size * 4 * sizeof(float));
    textureData.SysMemSlicePitch = static_cast<UINT>(cube->size * cube->size * 4 * sizeof(float));
    hr = device->CreateTexture3D(&textureDescription, &textureData, &self->lut_texture);
    if (FAILED(hr)) return false;
    hr = device->CreateShaderResourceView(self->lut_texture, nullptr, &self->lut_view);
    return SUCCEEDED(hr);
}

void gst_ffgui_d3d11_lut_set_property(
    GObject* object, guint property, const GValue* value, GParamSpec* specification) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(object);
    if (property == property_lut_id) {
        g_free(self->lut_id);
        self->lut_id = g_value_dup_string(value);
    } else if (property == property_shader_id) {
        g_free(self->shader_id);
        self->shader_id = g_value_dup_string(value);
    } else {
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property, specification);
    }
}

void gst_ffgui_d3d11_lut_get_property(
    GObject* object, guint property, GValue* value, GParamSpec* specification) {
    const auto* self = reinterpret_cast<const GstFfguiD3D11Lut*>(object);
    if (property == property_lut_id) {
        g_value_set_string(value, self->lut_id);
    } else if (property == property_shader_id) {
        g_value_set_string(value, self->shader_id);
    } else {
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property, specification);
    }
}

void gst_ffgui_d3d11_lut_set_context(GstElement* element, GstContext* context) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(element);
    gst_d3d11_handle_set_context(element, context, -1, &self->device);
    GST_ELEMENT_CLASS(gst_ffgui_d3d11_lut_parent_class)->set_context(element, context);
}

gboolean gst_ffgui_d3d11_lut_query(
    GstBaseTransform* transform, GstPadDirection direction, GstQuery* query) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(transform);
    if (GST_QUERY_TYPE(query) == GST_QUERY_CONTEXT &&
        gst_d3d11_handle_context_query(GST_ELEMENT(self), query, self->device)) return TRUE;
    return GST_BASE_TRANSFORM_CLASS(gst_ffgui_d3d11_lut_parent_class)
        ->query(transform, direction, query);
}

gboolean gst_ffgui_d3d11_lut_start(GstBaseTransform* transform) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(transform);
    delete self->cube;
    self->cube = new std::shared_ptr<const ffgui::ColorCube>(
        ffgui::find_published_gst_color_lut(self->lut_id == nullptr ? "" : self->lut_id));
    delete self->ocio_shader;
    self->ocio_shader = new std::shared_ptr<const ffgui::OcioGpuShader>(
        find_shader(self->shader_id));
    const auto sourceCount = static_cast<int>(static_cast<bool>(*self->cube)) +
        static_cast<int>(static_cast<bool>(*self->ocio_shader));
    return sourceCount == 1 && gst_d3d11_ensure_element_data(
        GST_ELEMENT(self), -1, &self->device);
}

gboolean gst_ffgui_d3d11_lut_stop(GstBaseTransform* transform) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(transform);
    if (self->ocio_resources != nullptr) {
        std::scoped_lock resourceLock(self->ocio_resources->mutex);
        release_gpu_resources(self);
    }
    delete self->cube;
    self->cube = nullptr;
    delete self->ocio_shader;
    self->ocio_shader = nullptr;
    gst_clear_object(&self->device);
    return TRUE;
}

gboolean gst_ffgui_d3d11_lut_set_caps(
    GstBaseTransform* transform, GstCaps* input, GstCaps* output) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(transform);
    GstVideoInfo outputInfo{};
    if (!gst_video_info_from_caps(&self->info, input) ||
        !gst_video_info_from_caps(&outputInfo, output) ||
        GST_VIDEO_INFO_FORMAT(&self->info) != GST_VIDEO_FORMAT_RGBA64_LE ||
        GST_VIDEO_INFO_FORMAT(&outputInfo) != GST_VIDEO_FORMAT_RGBA64_LE ||
        self->info.width != outputInfo.width || self->info.height != outputInfo.height) return FALSE;
    return create_gpu_resources(self);
}

gboolean gst_ffgui_d3d11_lut_get_unit_size(
    GstBaseTransform*, GstCaps* caps, gsize* size) {
    GstVideoInfo info{};
    if (!gst_video_info_from_caps(&info, caps)) return FALSE;
    *size = GST_VIDEO_INFO_SIZE(&info);
    return TRUE;
}

gboolean gst_ffgui_d3d11_lut_decide_allocation(
    GstBaseTransform* transform, GstQuery* query) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(transform);
    GstCaps* caps = nullptr;
    gst_query_parse_allocation(query, &caps, nullptr);
    GstVideoInfo info{};
    if (caps == nullptr || self->device == nullptr ||
        !gst_video_info_from_caps(&info, caps)) return FALSE;
    auto* pool = gst_d3d11_buffer_pool_new(self->device);
    auto* config = gst_buffer_pool_get_config(pool);
    gst_buffer_pool_config_add_option(config, GST_BUFFER_POOL_OPTION_VIDEO_META);
    auto* parameters = gst_d3d11_allocation_params_new(
        self->device, &info, GST_D3D11_ALLOCATION_FLAG_DEFAULT,
        D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE, 0);
    gst_buffer_pool_config_set_d3d11_allocation_params(config, parameters);
    gst_d3d11_allocation_params_free(parameters);
    gst_buffer_pool_config_set_params(config, caps, 0, 0, 0);
    if (!gst_buffer_pool_set_config(pool, config)) {
        gst_object_unref(pool);
        return FALSE;
    }
    config = gst_buffer_pool_get_config(pool);
    guint size = 0;
    gst_buffer_pool_config_get_params(config, nullptr, &size, nullptr, nullptr);
    gst_structure_free(config);
    if (gst_query_get_n_allocation_pools(query) > 0) {
        gst_query_set_nth_allocation_pool(query, 0, pool, size, 0, 0);
    } else {
        gst_query_add_allocation_pool(query, pool, size, 0, 0);
    }
    gst_query_add_allocation_meta(query, GST_VIDEO_META_API_TYPE, nullptr);
    gst_object_unref(pool);
    return GST_BASE_TRANSFORM_CLASS(gst_ffgui_d3d11_lut_parent_class)
        ->decide_allocation(transform, query);
}

GstFlowReturn gst_ffgui_d3d11_lut_transform(
    GstBaseTransform* transform, GstBuffer* input, GstBuffer* output) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(transform);
    if (self->ocio_resources == nullptr) return GST_FLOW_ERROR;
    std::scoped_lock resourceLock(self->ocio_resources->mutex);
    if (gst_buffer_n_memory(input) == 0 || gst_buffer_n_memory(output) == 0 ||
        self->device == nullptr ||
        (self->lut_view == nullptr && self->ocio_resources->views.empty() &&
         (self->ocio_shader == nullptr || !*self->ocio_shader))) return GST_FLOW_ERROR;
    auto* inputMemory = gst_buffer_peek_memory(input, 0);
    auto* outputMemory = gst_buffer_peek_memory(output, 0);
    if (!gst_is_d3d11_memory(inputMemory) || !gst_is_d3d11_memory(outputMemory)) {
        return GST_FLOW_NOT_NEGOTIATED;
    }
    auto* inputD3D = GST_D3D11_MEMORY_CAST(inputMemory);
    auto* outputD3D = GST_D3D11_MEMORY_CAST(outputMemory);
    if (inputD3D->device != self->device || outputD3D->device != self->device) {
        return GST_FLOW_NOT_NEGOTIATED;
    }
    GstMapInfo inputMap{};
    GstMapInfo outputMap{};
    if (!gst_memory_map(inputMemory, &inputMap,
            static_cast<GstMapFlags>(GST_MAP_D3D11 | GST_MAP_READ))) {
        return GST_FLOW_ERROR;
    }
    if (!gst_memory_map(outputMemory, &outputMap,
            static_cast<GstMapFlags>(GST_MAP_D3D11 | GST_MAP_WRITE))) {
        gst_memory_unmap(inputMemory, &inputMap);
        return GST_FLOW_ERROR;
    }
    auto* sourceView = gst_d3d11_memory_get_shader_resource_view(inputD3D, 0);
    auto* targetView = gst_d3d11_memory_get_render_target_view(outputD3D, 0);
    if (gst_d3d11_memory_get_resource_handle(inputD3D) ==
        gst_d3d11_memory_get_resource_handle(outputD3D)) {
        gst_memory_unmap(outputMemory, &outputMap);
        gst_memory_unmap(inputMemory, &inputMap);
        return GST_FLOW_ERROR;
    }
    if (sourceView == nullptr || targetView == nullptr) {
        gst_memory_unmap(outputMemory, &outputMap);
        gst_memory_unmap(inputMemory, &inputMap);
        return GST_FLOW_ERROR;
    }

    auto* context = gst_d3d11_device_get_device_context_handle(self->device);
    D3D11_VIEWPORT viewport{};
    viewport.Width = static_cast<float>(self->info.width);
    viewport.Height = static_cast<float>(self->info.height);
    viewport.MaxDepth = 1.0F;
    const auto ocio = self->ocio_shader != nullptr && *self->ocio_shader;
    std::vector<ID3D11ShaderResourceView*> resources;
    std::vector<ID3D11SamplerState*> samplers;
    if (ocio) {
        auto maximumTextureBinding = 0U;
        auto maximumSamplerBinding = 0U;
        for (const auto binding : self->ocio_resources->texture_bindings) {
            maximumTextureBinding = (std::max)(maximumTextureBinding, binding);
        }
        for (const auto binding : self->ocio_resources->sampler_bindings) {
            maximumSamplerBinding = (std::max)(maximumSamplerBinding, binding);
        }
        resources.assign(static_cast<std::size_t>(maximumTextureBinding) + 1, nullptr);
        samplers.assign(static_cast<std::size_t>(maximumSamplerBinding) + 1, nullptr);
        resources[0] = sourceView;
        samplers[0] = self->sampler;
        for (std::size_t index = 0; index < self->ocio_resources->views.size(); ++index) {
            resources[self->ocio_resources->texture_bindings[index]] =
                self->ocio_resources->views[index];
            samplers[self->ocio_resources->sampler_bindings[index]] =
                self->ocio_resources->samplers[index];
        }
    } else {
        resources = {sourceView, self->lut_view};
        samplers = {self->sampler};
    }
    gst_d3d11_device_lock(self->device);
    context->IASetInputLayout(nullptr);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(self->vertex_shader, nullptr, 0);
    context->PSSetShader(self->pixel_shader, nullptr, 0);
    context->PSSetShaderResources(0, static_cast<UINT>(resources.size()), resources.data());
    context->PSSetSamplers(0, static_cast<UINT>(samplers.size()), samplers.data());
    context->RSSetViewports(1, &viewport);
    context->OMSetBlendState(self->blend_state, nullptr, 0xffffffffU);
    context->OMSetRenderTargets(1, &targetView, nullptr);
    context->Draw(3, 0);
    std::ranges::fill(resources, nullptr);
    std::ranges::fill(samplers, nullptr);
    context->PSSetShaderResources(0, static_cast<UINT>(resources.size()), resources.data());
    context->PSSetSamplers(0, static_cast<UINT>(samplers.size()), samplers.data());
    context->PSSetShader(nullptr, nullptr, 0);
    context->VSSetShader(nullptr, nullptr, 0);
    context->OMSetBlendState(nullptr, nullptr, 0xffffffffU);
    ID3D11RenderTargetView* emptyTarget = nullptr;
    context->OMSetRenderTargets(1, &emptyTarget, nullptr);
    gst_d3d11_device_unlock(self->device);
    gst_memory_unmap(outputMemory, &outputMap);
    gst_memory_unmap(inputMemory, &inputMap);
    return GST_FLOW_OK;
}

void gst_ffgui_d3d11_lut_finalize(GObject* object) {
    auto* self = reinterpret_cast<GstFfguiD3D11Lut*>(object);
    if (self->ocio_resources != nullptr) {
        std::scoped_lock resourceLock(self->ocio_resources->mutex);
        release_gpu_resources(self);
    }
    delete self->cube;
    self->cube = nullptr;
    delete self->ocio_shader;
    self->ocio_shader = nullptr;
    gst_clear_object(&self->device);
    g_free(self->lut_id);
    self->lut_id = nullptr;
    g_free(self->shader_id);
    self->shader_id = nullptr;
    delete self->ocio_resources;
    self->ocio_resources = nullptr;
    G_OBJECT_CLASS(gst_ffgui_d3d11_lut_parent_class)->finalize(object);
}

void gst_ffgui_d3d11_lut_class_init(GstFfguiD3D11LutClass* klass) {
    auto* objectClass = G_OBJECT_CLASS(klass);
    objectClass->set_property = gst_ffgui_d3d11_lut_set_property;
    objectClass->get_property = gst_ffgui_d3d11_lut_get_property;
    objectClass->finalize = gst_ffgui_d3d11_lut_finalize;
    g_object_class_install_property(
        objectClass, property_lut_id,
        g_param_spec_string(
            "lut-id", "LUT identifier", "Published ffmpegGUI color cube identifier",
            nullptr, static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
    g_object_class_install_property(
        objectClass, property_shader_id,
        g_param_spec_string(
            "shader-id", "OCIO shader identifier",
            "Published exact OpenColorIO Direct3D 11 shader identifier",
            nullptr, static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
    auto* elementClass = GST_ELEMENT_CLASS(klass);
    elementClass->set_context = gst_ffgui_d3d11_lut_set_context;
    gst_element_class_set_static_metadata(
        elementClass, "ffmpegGUI D3D11 source color processor", "Filter/Effect/Video/Hardware",
        "Applies an exact OpenColorIO shader or a published 3D color cube on D3D11 textures",
        "ffmpegGUI");
    auto* caps = gst_caps_from_string(
        "video/x-raw(memory:D3D11Memory),format=RGBA64_LE");
    gst_element_class_add_pad_template(
        elementClass, gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS, caps));
    gst_element_class_add_pad_template(
        elementClass, gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS, caps));
    gst_caps_unref(caps);
    auto* transformClass = GST_BASE_TRANSFORM_CLASS(klass);
    transformClass->passthrough_on_same_caps = FALSE;
    transformClass->start = gst_ffgui_d3d11_lut_start;
    transformClass->stop = gst_ffgui_d3d11_lut_stop;
    transformClass->set_caps = gst_ffgui_d3d11_lut_set_caps;
    transformClass->get_unit_size = gst_ffgui_d3d11_lut_get_unit_size;
    transformClass->query = gst_ffgui_d3d11_lut_query;
    transformClass->decide_allocation = gst_ffgui_d3d11_lut_decide_allocation;
    transformClass->transform = gst_ffgui_d3d11_lut_transform;
}

void gst_ffgui_d3d11_lut_init(GstFfguiD3D11Lut* self) {
    self->ocio_resources = new OcioResourceState;
    gst_video_info_init(&self->info);
    gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), FALSE);
    gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}

}  // namespace

namespace ffgui {

bool register_gst_d3d11_color_lut_filter() {
    static std::once_flag once;
    static bool registered = false;
    std::call_once(once, [] {
        registered = gst_element_register(
            nullptr, "ffguilut3d11", GST_RANK_NONE, gst_ffgui_d3d11_lut_get_type());
    });
    return registered;
}

bool gst_d3d11_color_lut_available() {
    auto* upload = gst_element_factory_find("d3d11upload");
    auto* compositor = gst_element_factory_find("d3d11compositor");
    auto* device = gst_d3d11_device_new(0, 0);
    const auto available = upload != nullptr && compositor != nullptr && device != nullptr;
    if (upload != nullptr) gst_object_unref(upload);
    if (compositor != nullptr) gst_object_unref(compositor);
    if (device != nullptr) gst_object_unref(device);
    return available;
}

void publish_gst_d3d11_ocio_shader(
    std::string id, std::shared_ptr<const OcioGpuShader> shader) {
    if (id.empty() || shader == nullptr || shader->source.empty() ||
        shader->function_name.empty()) return;
    std::scoped_lock lock(shaderRegistryMutex);
    shaderRegistry.insert_or_assign(std::move(id), std::move(shader));
}

void remove_gst_d3d11_ocio_shader(const std::string& id) noexcept {
    std::scoped_lock lock(shaderRegistryMutex);
    shaderRegistry.erase(id);
}

}  // namespace ffgui
