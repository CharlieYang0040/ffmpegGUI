#include "integration/ges/gst_color_lut_filter.hpp"

#include <gst/base/gstbasetransform.h>
#include <gst/video/video.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <utility>

namespace {

std::mutex registryMutex;
std::unordered_map<std::string, std::shared_ptr<const ffgui::ColorCube>> registry;

std::shared_ptr<const ffgui::ColorCube> find_cube(const char* id) {
    if (id == nullptr || *id == '\0') return {};
    std::scoped_lock lock(registryMutex);
    const auto found = registry.find(id);
    return found == registry.end() ? nullptr : found->second;
}

struct GstFfguiLut3d final {
    GstBaseTransform parent;
    gchar* lut_id{};
    GstVideoInfo info{};
    std::shared_ptr<const ffgui::ColorCube>* cube{};
};

struct GstFfguiLut3dClass final {
    GstBaseTransformClass parent_class;
};

G_DEFINE_TYPE(GstFfguiLut3d, gst_ffgui_lut3d, GST_TYPE_BASE_TRANSFORM)

enum { property_zero, property_lut_id };

void gst_ffgui_lut3d_set_property(
    GObject* object, guint property, const GValue* value, GParamSpec* specification) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(object);
    if (property == property_lut_id) {
        g_free(self->lut_id);
        self->lut_id = g_value_dup_string(value);
    } else {
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property, specification);
    }
}

void gst_ffgui_lut3d_get_property(
    GObject* object, guint property, GValue* value, GParamSpec* specification) {
    const auto* self = reinterpret_cast<const GstFfguiLut3d*>(object);
    if (property == property_lut_id) {
        g_value_set_string(value, self->lut_id);
    } else {
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property, specification);
    }
}

void gst_ffgui_lut3d_finalize(GObject* object) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(object);
    g_free(self->lut_id);
    self->lut_id = nullptr;
    delete self->cube;
    self->cube = nullptr;
    G_OBJECT_CLASS(gst_ffgui_lut3d_parent_class)->finalize(object);
}

gboolean gst_ffgui_lut3d_start(GstBaseTransform* transform) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    delete self->cube;
    self->cube = new std::shared_ptr<const ffgui::ColorCube>(find_cube(self->lut_id));
    const auto& cube = *self->cube;
    return cube != nullptr && cube->size >= 2 &&
        cube->rgb.size() == static_cast<std::size_t>(cube->size) * cube->size * cube->size * 3;
}

gboolean gst_ffgui_lut3d_stop(GstBaseTransform* transform) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    delete self->cube;
    self->cube = nullptr;
    return TRUE;
}

gboolean gst_ffgui_lut3d_set_caps(
    GstBaseTransform* transform, GstCaps* input, GstCaps*) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    return gst_video_info_from_caps(&self->info, input);
}

void sample_cube(const ffgui::ColorCube& cube, const float input[3], float output[3]) {
    const auto maximum = cube.size - 1;
    int lower[3]{};
    int upper[3]{};
    float fraction[3]{};
    for (int channel = 0; channel < 3; ++channel) {
        const auto coordinate = std::clamp(
            std::isfinite(input[channel]) ? input[channel] : 0.0F, 0.0F, 1.0F) * maximum;
        lower[channel] = static_cast<int>(std::floor(coordinate));
        upper[channel] = std::min(maximum, lower[channel] + 1);
        fraction[channel] = coordinate - lower[channel];
    }
    const auto value = [&](int red, int green, int blue, int channel) {
        const auto index = (static_cast<std::size_t>(blue) * cube.size * cube.size +
                            static_cast<std::size_t>(green) * cube.size + red) * 3 + channel;
        return cube.rgb[index];
    };
    for (int channel = 0; channel < 3; ++channel) {
        const auto c00 = std::lerp(value(lower[0], lower[1], lower[2], channel),
                                   value(upper[0], lower[1], lower[2], channel), fraction[0]);
        const auto c10 = std::lerp(value(lower[0], upper[1], lower[2], channel),
                                   value(upper[0], upper[1], lower[2], channel), fraction[0]);
        const auto c01 = std::lerp(value(lower[0], lower[1], upper[2], channel),
                                   value(upper[0], lower[1], upper[2], channel), fraction[0]);
        const auto c11 = std::lerp(value(lower[0], upper[1], upper[2], channel),
                                   value(upper[0], upper[1], upper[2], channel), fraction[0]);
        output[channel] = std::lerp(
            std::lerp(c00, c10, fraction[1]),
            std::lerp(c01, c11, fraction[1]), fraction[2]);
    }
}

GstFlowReturn gst_ffgui_lut3d_transform_ip(GstBaseTransform* transform, GstBuffer* buffer) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    if (self->cube == nullptr || !*self->cube) return GST_FLOW_NOT_NEGOTIATED;
    GstVideoFrame frame;
    if (!gst_video_frame_map(&frame, &self->info, buffer, GST_MAP_READWRITE)) {
        return GST_FLOW_ERROR;
    }
    const auto width = GST_VIDEO_FRAME_WIDTH(&frame);
    const auto height = GST_VIDEO_FRAME_HEIGHT(&frame);
    auto* base = static_cast<std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&frame, 0));
    const auto stride = GST_VIDEO_FRAME_PLANE_STRIDE(&frame, 0);
    for (gint row = 0; row < height; ++row) {
        auto* pixels = reinterpret_cast<std::uint16_t*>(base + static_cast<gssize>(row) * stride);
        for (gint column = 0; column < width; ++column) {
            auto* rgba = pixels + static_cast<std::size_t>(column) * 4;
            const float input[3]{
                static_cast<float>(rgba[0]) / 65535.0F,
                static_cast<float>(rgba[1]) / 65535.0F,
                static_cast<float>(rgba[2]) / 65535.0F};
            float output[3]{};
            sample_cube(**self->cube, input, output);
            for (int channel = 0; channel < 3; ++channel) {
                rgba[channel] = static_cast<std::uint16_t>(std::lround(
                    std::clamp(std::isfinite(output[channel]) ? output[channel] : 0.0F,
                               0.0F, 1.0F) * 65535.0F));
            }
        }
    }
    gst_video_frame_unmap(&frame);
    return GST_FLOW_OK;
}

void gst_ffgui_lut3d_class_init(GstFfguiLut3dClass* klass) {
    auto* objectClass = G_OBJECT_CLASS(klass);
    objectClass->set_property = gst_ffgui_lut3d_set_property;
    objectClass->get_property = gst_ffgui_lut3d_get_property;
    objectClass->finalize = gst_ffgui_lut3d_finalize;
    g_object_class_install_property(
        objectClass, property_lut_id,
        g_param_spec_string(
            "lut-id", "LUT identifier", "Published ffmpegGUI color cube identifier",
            nullptr, static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    auto* elementClass = GST_ELEMENT_CLASS(klass);
    gst_element_class_set_static_metadata(
        elementClass, "ffmpegGUI source color LUT", "Filter/Effect/Video",
        "Applies a published 3D color cube before timeline composition", "ffmpegGUI");
    auto* caps = gst_caps_from_string("video/x-raw,format=RGBA64_LE");
    gst_element_class_add_pad_template(
        elementClass, gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS, caps));
    gst_element_class_add_pad_template(
        elementClass, gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS, caps));
    gst_caps_unref(caps);

    auto* transformClass = GST_BASE_TRANSFORM_CLASS(klass);
    transformClass->start = gst_ffgui_lut3d_start;
    transformClass->stop = gst_ffgui_lut3d_stop;
    transformClass->set_caps = gst_ffgui_lut3d_set_caps;
    transformClass->transform_ip = gst_ffgui_lut3d_transform_ip;
}

void gst_ffgui_lut3d_init(GstFfguiLut3d* self) {
    gst_video_info_init(&self->info);
    gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
    gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}

}  // namespace

namespace ffgui {

bool register_gst_color_lut_filter() {
    static std::once_flag once;
    static bool registered = false;
    std::call_once(once, [] {
        registered = gst_element_register(
            nullptr, "ffguilut3d", GST_RANK_NONE, gst_ffgui_lut3d_get_type());
    });
    return registered;
}

void publish_gst_color_lut(std::string id, std::shared_ptr<const ColorCube> cube) {
    if (id.empty() || cube == nullptr) return;
    std::scoped_lock lock(registryMutex);
    registry.insert_or_assign(std::move(id), std::move(cube));
}

void remove_gst_color_lut(const std::string& id) noexcept {
    std::scoped_lock lock(registryMutex);
    registry.erase(id);
}

}  // namespace ffgui
