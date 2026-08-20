#include "integration/ges/gst_color_lut_filter.hpp"

#include "color/grade_processor.hpp"

#include <gst/base/gstbasetransform.h>
#include <gst/video/video.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

std::mutex registryMutex;
std::unordered_map<std::string, std::shared_ptr<const ffgui::ColorCube>> registry;
std::unordered_map<std::string, std::shared_ptr<const ffgui::ColorLutRecipe>> recipeRegistry;

std::shared_ptr<const ffgui::ColorCube> find_cube(const char* id) {
    if (id == nullptr || *id == '\0') return {};
    std::scoped_lock lock(registryMutex);
    const auto found = registry.find(id);
    return found == registry.end() ? nullptr : found->second;
}

std::shared_ptr<const ffgui::ColorLutRecipe> find_recipe(const char* id) {
    if (id == nullptr || *id == '\0') return {};
    std::scoped_lock lock(registryMutex);
    const auto found = recipeRegistry.find(id);
    return found == recipeRegistry.end() ? nullptr : found->second;
}

struct GstFfguiLut3d final {
    GstBaseTransform parent;
    gchar* lut_id{};
    GstVideoInfo info{};
    std::shared_ptr<const ffgui::ColorCube>* cube{};
    std::shared_ptr<const ffgui::ColorLutRecipe>* recipe{};
    ffgui::AnimatedCubeCache* cache{};
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
    delete self->recipe;
    self->recipe = nullptr;
    delete self->cache;
    self->cache = nullptr;
    G_OBJECT_CLASS(gst_ffgui_lut3d_parent_class)->finalize(object);
}

gboolean gst_ffgui_lut3d_start(GstBaseTransform* transform) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    delete self->cube;
    self->cube = new std::shared_ptr<const ffgui::ColorCube>(find_cube(self->lut_id));
    delete self->recipe;
    self->recipe = new std::shared_ptr<const ffgui::ColorLutRecipe>(find_recipe(self->lut_id));
    const auto& cube = *self->cube;
    const auto& recipe = *self->recipe;
    if (recipe != nullptr && recipe->animated) return TRUE;
    return cube != nullptr && cube->size >= 2 &&
        cube->rgb.size() == static_cast<std::size_t>(cube->size) * cube->size * cube->size * 3;
}

gboolean gst_ffgui_lut3d_stop(GstBaseTransform* transform) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    delete self->cube;
    self->cube = nullptr;
    delete self->recipe;
    self->recipe = nullptr;
    return TRUE;
}

gboolean gst_ffgui_lut3d_set_caps(
    GstBaseTransform* transform, GstCaps* input, GstCaps*) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    return gst_video_info_from_caps(&self->info, input);
}

std::shared_ptr<const ffgui::ColorCube> cube_for_buffer(
    GstFfguiLut3d* self, GstBuffer* buffer) {
    auto recipe = find_recipe(self->lut_id);
    if (self->recipe != nullptr) *self->recipe = recipe;
    if (recipe != nullptr && recipe->animated) {
        if (self->cache == nullptr) self->cache = new ffgui::AnimatedCubeCache;
        const auto pts = GST_BUFFER_PTS_IS_VALID(buffer)
            ? static_cast<ffgui::TimeNs>(GST_BUFFER_PTS(buffer)) : ffgui::TimeNs{0};
        return self->cache->cube_for_pts(recipe, pts);
    }
    return find_cube(self->lut_id);
}

GstFlowReturn gst_ffgui_lut3d_transform_ip(GstBaseTransform* transform, GstBuffer* buffer) {
    auto* self = reinterpret_cast<GstFfguiLut3d*>(transform);
    const auto cube = cube_for_buffer(self, buffer);
    if (cube == nullptr || cube->size < 2 ||
        cube->rgb.size() != static_cast<std::size_t>(cube->size) * cube->size * cube->size * 3) {
        return GST_FLOW_NOT_NEGOTIATED;
    }
    GstVideoFrame frame;
    if (!gst_video_frame_map(&frame, &self->info, buffer, GST_MAP_READWRITE)) {
        return GST_FLOW_ERROR;
    }
    const auto width = GST_VIDEO_FRAME_WIDTH(&frame);
    const auto height = GST_VIDEO_FRAME_HEIGHT(&frame);
    auto* base = static_cast<std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&frame, 0));
    const auto stride = GST_VIDEO_FRAME_PLANE_STRIDE(&frame, 0);
    auto recipe = self->recipe != nullptr ? *self->recipe : std::shared_ptr<const ffgui::ColorLutRecipe>{};
    if (recipe == nullptr) recipe = find_recipe(self->lut_id);
    const auto spatial = recipe != nullptr && recipe->grade.has_spatial_nodes();
    std::vector<float> spatialPixels;
    if (spatial) {
        spatialPixels.resize(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4);
    }
    for (gint row = 0; row < height; ++row) {
        auto* pixels = reinterpret_cast<std::uint16_t*>(base + static_cast<gssize>(row) * stride);
        for (gint column = 0; column < width; ++column) {
            auto* rgba = pixels + static_cast<std::size_t>(column) * 4;
            const float input[3]{
                static_cast<float>(rgba[0]) / 65535.0F,
                static_cast<float>(rgba[1]) / 65535.0F,
                static_cast<float>(rgba[2]) / 65535.0F};
            float output[3]{};
            ffgui::sample_color_cube(*cube, input, output);
            if (spatial) {
                const auto index = (static_cast<std::size_t>(row) *
                    static_cast<std::size_t>(width) + static_cast<std::size_t>(column)) * 4;
                spatialPixels[index] = output[0];
                spatialPixels[index + 1] = output[1];
                spatialPixels[index + 2] = output[2];
                spatialPixels[index + 3] = static_cast<float>(rgba[3]) / 65535.0F;
            } else {
                for (int channel = 0; channel < 3; ++channel) {
                    rgba[channel] = static_cast<std::uint16_t>(std::lround(
                        std::clamp(std::isfinite(output[channel]) ? output[channel] : 0.0F,
                                   0.0F, 1.0F) * 65535.0F));
                }
            }
        }
    }
    if (spatial) {
        const auto pts = GST_BUFFER_PTS_IS_VALID(buffer)
            ? static_cast<ffgui::TimeNs>(GST_BUFFER_PTS(buffer)) : ffgui::TimeNs{0};
        const auto sourceTime = ffgui::source_time_for_recipe(*recipe, pts);
        ffgui::apply_grade_graph_rgba32f(
            spatialPixels.data(),
            static_cast<std::size_t>(width) * static_cast<std::size_t>(height),
            recipe->grade, sourceTime,
            static_cast<std::size_t>(width), static_cast<std::size_t>(height),
            ffgui::GradeSpatialMode::only);
        for (gint row = 0; row < height; ++row) {
            auto* pixels = reinterpret_cast<std::uint16_t*>(base + static_cast<gssize>(row) * stride);
            for (gint column = 0; column < width; ++column) {
                auto* rgba = pixels + static_cast<std::size_t>(column) * 4;
                const auto index = (static_cast<std::size_t>(row) *
                    static_cast<std::size_t>(width) + static_cast<std::size_t>(column)) * 4;
                for (int channel = 0; channel < 3; ++channel) {
                    const auto value = spatialPixels[index + static_cast<std::size_t>(channel)];
                    rgba[channel] = static_cast<std::uint16_t>(std::lround(
                        std::clamp(std::isfinite(value) ? value : 0.0F, 0.0F, 1.0F) * 65535.0F));
                }
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
    self->cache = new ffgui::AnimatedCubeCache;
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

void publish_gst_color_recipe(std::string id, std::shared_ptr<const ColorLutRecipe> recipe) {
    if (id.empty() || recipe == nullptr) return;
    std::scoped_lock lock(registryMutex);
    recipeRegistry.insert_or_assign(std::move(id), std::move(recipe));
}

std::shared_ptr<const ColorCube> find_published_gst_color_lut(const std::string& id) {
    return find_cube(id.c_str());
}

std::shared_ptr<const ColorLutRecipe> find_published_gst_color_recipe(const std::string& id) {
    return find_recipe(id.c_str());
}

void remove_gst_color_lut(const std::string& id) noexcept {
    std::scoped_lock lock(registryMutex);
    registry.erase(id);
    recipeRegistry.erase(id);
}

void remove_gst_color_recipe(const std::string& id) noexcept {
    std::scoped_lock lock(registryMutex);
    recipeRegistry.erase(id);
}

}  // namespace ffgui
