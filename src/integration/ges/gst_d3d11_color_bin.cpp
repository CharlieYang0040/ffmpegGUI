#include "integration/ges/gst_d3d11_color_bin.hpp"

#define GST_USE_UNSTABLE_API
#include <ges/ges-frame-composition-meta.h>
#include <gst/gst.h>

#include <mutex>
#include <unordered_map>

namespace {

struct CompositionValues final {
    double alpha{};
    double posx{};
    double posy{};
    double width{};
    double height{};
    guint zorder{};
    gint operation{};
};

using CompositionCache = std::unordered_map<GstClockTime, CompositionValues>;

struct GstFfguiD3DColorBin final {
    GstBin parent;
    gchar* lut_id{};
    gchar* shader_id{};
    gboolean direct_output{};
    CompositionCache* cache{};
};

struct GstFfguiD3DColorBinClass final {
    GstBinClass parent_class;
};

G_DEFINE_TYPE(GstFfguiD3DColorBin, gst_ffgui_d3d_color_bin, GST_TYPE_BIN)

enum { property_zero, property_lut_id, property_shader_id, property_direct_output };

GstClockTime buffer_key(const GstBuffer* buffer) {
    return GST_BUFFER_PTS_IS_VALID(buffer) ? GST_BUFFER_PTS(buffer) : GST_BUFFER_DTS(buffer);
}

GstPadProbeReturn capture_composition(
    GstPad*, GstPadProbeInfo* info, gpointer user_data) {
    auto* self = reinterpret_cast<GstFfguiD3DColorBin*>(user_data);
    auto* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr || self->cache == nullptr) return GST_PAD_PROBE_OK;
    auto* meta = reinterpret_cast<GESFrameCompositionMeta*>(
        gst_buffer_get_meta(buffer, GES_TYPE_META_FRAME_COMPOSITION));
    const auto key = buffer_key(buffer);
    if (meta == nullptr || !GST_CLOCK_TIME_IS_VALID(key)) return GST_PAD_PROBE_OK;
    self->cache->insert_or_assign(key, CompositionValues{
        meta->alpha, meta->posx, meta->posy, meta->width, meta->height,
        meta->zorder, meta->_operator});
    if (self->cache->size() > 64) self->cache->erase(self->cache->begin());
    return GST_PAD_PROBE_OK;
}

GstPadProbeReturn restore_composition(
    GstPad*, GstPadProbeInfo* info, gpointer user_data) {
    auto* self = reinterpret_cast<GstFfguiD3DColorBin*>(user_data);
    auto* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr || self->cache == nullptr) return GST_PAD_PROBE_OK;
    const auto found = self->cache->find(buffer_key(buffer));
    if (found == self->cache->end()) return GST_PAD_PROBE_OK;
    if (!gst_buffer_is_writable(buffer)) {
        buffer = gst_buffer_make_writable(buffer);
        GST_PAD_PROBE_INFO_DATA(info) = buffer;
    }
    auto* meta = reinterpret_cast<GESFrameCompositionMeta*>(
        gst_buffer_get_meta(buffer, GES_TYPE_META_FRAME_COMPOSITION));
    if (meta == nullptr) meta = ges_buffer_add_frame_composition_meta(buffer);
    if (meta != nullptr) {
        const auto values = found->second;
        meta->alpha = values.alpha;
        meta->posx = values.posx;
        meta->posy = values.posy;
        meta->width = values.width;
        meta->height = values.height;
        meta->zorder = values.zorder;
        meta->_operator = values.operation;
    }
    self->cache->erase(found);
    return GST_PAD_PROBE_OK;
}

void set_property(
    GObject* object, guint property, const GValue* value, GParamSpec* specification) {
    auto* self = reinterpret_cast<GstFfguiD3DColorBin*>(object);
    if (property == property_direct_output) {
        self->direct_output = g_value_get_boolean(value);
        return;
    }
    gchar** target = property == property_lut_id ? &self->lut_id
        : property == property_shader_id ? &self->shader_id : nullptr;
    if (target == nullptr) {
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property, specification);
        return;
    }
    g_free(*target);
    *target = g_value_dup_string(value);
}

void get_property(
    GObject* object, guint property, GValue* value, GParamSpec* specification) {
    const auto* self = reinterpret_cast<const GstFfguiD3DColorBin*>(object);
    if (property == property_direct_output) {
        g_value_set_boolean(value, self->direct_output);
        return;
    }
    const gchar* result = property == property_lut_id ? self->lut_id
        : property == property_shader_id ? self->shader_id : nullptr;
    if (property != property_lut_id && property != property_shader_id) {
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property, specification);
        return;
    }
    g_value_set_string(value, result);
}

void finalize(GObject* object) {
    auto* self = reinterpret_cast<GstFfguiD3DColorBin*>(object);
    g_clear_pointer(&self->lut_id, g_free);
    g_clear_pointer(&self->shader_id, g_free);
    delete self->cache;
    self->cache = nullptr;
    G_OBJECT_CLASS(gst_ffgui_d3d_color_bin_parent_class)->finalize(object);
}

void constructed(GObject* object) {
    G_OBJECT_CLASS(gst_ffgui_d3d_color_bin_parent_class)->constructed(object);
    auto* self = reinterpret_cast<GstFfguiD3DColorBin*>(object);
    auto* upload = gst_element_factory_make("d3d11upload", nullptr);
    auto* inputCaps = gst_element_factory_make("capsfilter", nullptr);
    auto* lut = gst_element_factory_make("ffguilut3d11", nullptr);
    auto* download = self->direct_output ? nullptr
        : gst_element_factory_make("d3d11download", nullptr);
    auto* outputCaps = self->direct_output ? nullptr
        : gst_element_factory_make("capsfilter", nullptr);
    auto* convert = self->direct_output ? nullptr
        : gst_element_factory_make("videoconvert", nullptr);
    if (upload == nullptr || inputCaps == nullptr || lut == nullptr ||
        (!self->direct_output &&
         (download == nullptr || outputCaps == nullptr || convert == nullptr))) {
        gst_clear_object(&upload);
        gst_clear_object(&inputCaps);
        gst_clear_object(&lut);
        gst_clear_object(&download);
        gst_clear_object(&outputCaps);
        gst_clear_object(&convert);
        return;
    }
    auto* gpuCaps = gst_caps_from_string(
        "video/x-raw(memory:D3D11Memory),format=RGBA64_LE");
    g_object_set(inputCaps, "caps", gpuCaps, nullptr);
    gst_caps_unref(gpuCaps);
    if (outputCaps != nullptr) {
        auto* cpuCaps = gst_caps_from_string("video/x-raw,format=RGBA64_LE");
        g_object_set(outputCaps, "caps", cpuCaps, nullptr);
        gst_caps_unref(cpuCaps);
    }
    g_object_set(lut, "lut-id", self->lut_id, "shader-id", self->shader_id, nullptr);
    if (self->direct_output) {
        gst_bin_add_many(GST_BIN(self), upload, inputCaps, lut, nullptr);
        if (!gst_element_link_many(upload, inputCaps, lut, nullptr)) return;
    } else {
        gst_bin_add_many(
            GST_BIN(self), upload, inputCaps, lut, download, outputCaps, convert, nullptr);
        if (!gst_element_link_many(
                upload, inputCaps, lut, download, outputCaps, convert, nullptr)) return;
    }

    auto* sinkTarget = gst_element_get_static_pad(upload, "sink");
    auto* sourceTarget = gst_element_get_static_pad(
        self->direct_output ? lut : convert, "src");
    auto* sink = gst_ghost_pad_new("sink", sinkTarget);
    auto* source = gst_ghost_pad_new("src", sourceTarget);
    gst_object_unref(sinkTarget);
    gst_object_unref(sourceTarget);
    if (sink == nullptr || source == nullptr) {
        if (sink != nullptr) gst_object_unref(sink);
        if (source != nullptr) gst_object_unref(source);
        return;
    }
    gst_pad_add_probe(sink, GST_PAD_PROBE_TYPE_BUFFER, capture_composition, self, nullptr);
    gst_pad_add_probe(source, GST_PAD_PROBE_TYPE_BUFFER, restore_composition, self, nullptr);
    gst_pad_set_active(sink, TRUE);
    gst_pad_set_active(source, TRUE);
    gst_element_add_pad(GST_ELEMENT(self), sink);
    gst_element_add_pad(GST_ELEMENT(self), source);
}

void gst_ffgui_d3d_color_bin_class_init(GstFfguiD3DColorBinClass* klass) {
    auto* objectClass = G_OBJECT_CLASS(klass);
    objectClass->set_property = set_property;
    objectClass->get_property = get_property;
    objectClass->constructed = constructed;
    objectClass->finalize = finalize;
    g_object_class_install_property(
        objectClass, property_lut_id,
        g_param_spec_string(
            "lut-id", "LUT identifier", "Published creative color cube identifier", nullptr,
            static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_CONSTRUCT |
                                     G_PARAM_STATIC_STRINGS)));
    g_object_class_install_property(
        objectClass, property_shader_id,
        g_param_spec_string(
            "shader-id", "Shader identifier", "Published managed OCIO shader identifier", nullptr,
            static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_CONSTRUCT |
                                     G_PARAM_STATIC_STRINGS)));
    g_object_class_install_property(
        objectClass, property_direct_output,
        g_param_spec_boolean(
            "direct-output", "Direct D3D output",
            "Keep processed frames in D3D11 memory for the native compositor", FALSE,
            static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_CONSTRUCT |
                                     G_PARAM_STATIC_STRINGS)));

    auto* elementClass = GST_ELEMENT_CLASS(klass);
    gst_element_class_set_static_metadata(
        elementClass, "ffmpegGUI D3D11 color bin", "Filter/Effect/Video",
        "Preserves GES composition metadata across D3D11 color processing", "ffmpegGUI");
    auto* caps = gst_caps_from_string("video/x-raw(ANY)");
    gst_element_class_add_pad_template(
        elementClass, gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS, caps));
    gst_element_class_add_pad_template(
        elementClass, gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS, caps));
    gst_caps_unref(caps);
}

void gst_ffgui_d3d_color_bin_init(GstFfguiD3DColorBin* self) {
    self->cache = new CompositionCache;
}

}  // namespace

namespace ffgui {

bool register_gst_d3d11_color_bin() {
    static std::once_flag once;
    static bool registered = false;
    std::call_once(once, [] {
        registered = gst_element_register(
            nullptr, "ffguid3dcolor", GST_RANK_NONE, gst_ffgui_d3d_color_bin_get_type());
    });
    return registered;
}

}  // namespace ffgui
