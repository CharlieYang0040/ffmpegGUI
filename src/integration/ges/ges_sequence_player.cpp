#include "integration/ges/ges_sequence_player.hpp"
#include "integration/ges/gst_color_lut_filter.hpp"
#include "integration/ges/gst_d3d11_color_bin.hpp"
#include "integration/ges/gst_d3d11_color_lut_filter.hpp"

#include "color/color_frame_processor.hpp"
#include "color/grade_processor.hpp"
#include "render/timeline_frame_server.hpp"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#define GST_USE_UNSTABLE_API

#include <ges/ges.h>
#include <ges/ges-frame-composition-meta.h>
#include <gst/gst.h>
#include <gst/video/videooverlay.h>
#include <gst/video/video.h>
#include <gst/d3d11/gstd3d11.h>
#include <gst/controller/gstinterpolationcontrolsource.h>
#include <gst/controller/gsttimedvaluecontrolsource.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <cstring>

namespace ffgui {
namespace {

typedef struct _FfguiD3DMixer FfguiD3DMixer;
typedef struct _FfguiD3DMixerClass FfguiD3DMixerClass;

struct _FfguiD3DMixer {
    GstBin parent_instance;
    GstElement* compositor{};
    gint composition_frames{};
    gint composition_meta_frames{};
    gint blended_frames{};
};

struct _FfguiD3DMixerClass {
    GstBinClass parent_class;
};

G_DEFINE_TYPE(FfguiD3DMixer, ffgui_d3d_mixer, GST_TYPE_BIN)

GstStaticPadTemplate ffgui_d3d_mixer_src_template = GST_STATIC_PAD_TEMPLATE(
    "src", GST_PAD_SRC, GST_PAD_ALWAYS, GST_STATIC_CAPS("video/x-raw(ANY)"));
GstStaticPadTemplate ffgui_d3d_mixer_sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink_%u", GST_PAD_SINK, GST_PAD_REQUEST, GST_STATIC_CAPS("video/x-raw(ANY)"));

void apply_frame_composition_meta(
    FfguiD3DMixer* mixer, GstPad* pad, GstBuffer* buffer) {
    g_atomic_int_inc(&mixer->composition_frames);
    auto* meta = buffer != nullptr
        ? reinterpret_cast<GESFrameCompositionMeta*>(
            gst_buffer_get_meta(buffer, GES_TYPE_META_FRAME_COMPOSITION))
        : nullptr;
    if (meta != nullptr) {
        g_atomic_int_inc(&mixer->composition_meta_frames);
        if (meta->alpha > 0.001 && meta->alpha < 0.999) {
            g_atomic_int_inc(&mixer->blended_frames);
        }
        g_object_set(
            pad,
            "alpha", std::clamp(meta->alpha, 0.0, 1.0),
            "zorder", meta->zorder,
            "xpos", static_cast<int>(std::lround(meta->posx)),
            "ypos", static_cast<int>(std::lround(meta->posy)),
            "operator", meta->_operator,
            nullptr);
        if (meta->width >= 0.0) {
            g_object_set(pad, "width", static_cast<int>(std::lround(meta->width)), nullptr);
        }
        if (meta->height >= 0.0) {
            g_object_set(pad, "height", static_cast<int>(std::lround(meta->height)), nullptr);
        }
    }
}

GstPadProbeReturn ffgui_d3d_mixer_buffer_probe(
    GstPad* pad, GstPadProbeInfo* info, gpointer user_data) {
    if ((GST_PAD_PROBE_INFO_TYPE(info) & GST_PAD_PROBE_TYPE_BUFFER) != 0) {
        apply_frame_composition_meta(
            reinterpret_cast<FfguiD3DMixer*>(user_data), pad,
            GST_PAD_PROBE_INFO_BUFFER(info));
    }
    return GST_PAD_PROBE_OK;
}

void release_d3d_mixer_probe(gpointer user_data) {
    gst_object_unref(user_data);
}

GstPad* ffgui_d3d_mixer_request_pad(
    GstElement* element, GstPadTemplate*, const gchar* name, const GstCaps*) {
    auto* self = reinterpret_cast<FfguiD3DMixer*>(element);
    auto* mixerPad = gst_element_request_pad_simple(self->compositor, "sink_%u");
    if (mixerPad == nullptr) return nullptr;
    gst_pad_add_probe(
        mixerPad, GST_PAD_PROBE_TYPE_BUFFER, ffgui_d3d_mixer_buffer_probe,
        gst_object_ref(self), release_d3d_mixer_probe);
    auto* ghost = gst_ghost_pad_new(name, mixerPad);
    if (ghost == nullptr) {
        gst_element_release_request_pad(self->compositor, mixerPad);
        gst_object_unref(mixerPad);
        return nullptr;
    }
    gst_pad_set_active(ghost, TRUE);
    if (!gst_element_add_pad(element, ghost)) {
        gst_pad_set_active(ghost, FALSE);
        gst_object_unref(ghost);
        gst_element_release_request_pad(self->compositor, mixerPad);
        gst_object_unref(mixerPad);
        return nullptr;
    }
    gst_object_unref(mixerPad);
    return ghost;
}

void ffgui_d3d_mixer_release_pad(GstElement* element, GstPad* pad) {
    auto* self = reinterpret_cast<FfguiD3DMixer*>(element);
    auto* target = GST_IS_GHOST_PAD(pad)
        ? gst_ghost_pad_get_target(GST_GHOST_PAD(pad)) : nullptr;
    gst_pad_set_active(pad, FALSE);
    gst_element_remove_pad(element, pad);
    if (target != nullptr) {
        gst_element_release_request_pad(self->compositor, target);
        gst_object_unref(target);
    }
}

void ffgui_d3d_mixer_constructed(GObject* object) {
    G_OBJECT_CLASS(ffgui_d3d_mixer_parent_class)->constructed(object);
    auto* self = reinterpret_cast<FfguiD3DMixer*>(object);
    self->compositor = gst_element_factory_make("d3d11compositor", nullptr);
    if (self->compositor == nullptr) return;
    g_object_set(
        self->compositor,
        "background", 1,
        "ignore-inactive-pads", TRUE,
        nullptr);
    gst_bin_add(GST_BIN(self), self->compositor);
    auto* source = gst_element_get_static_pad(self->compositor, "src");
    auto* ghost = source != nullptr ? gst_ghost_pad_new("src", source) : nullptr;
    if (source != nullptr) gst_object_unref(source);
    if (ghost != nullptr) {
        gst_pad_set_active(ghost, TRUE);
        gst_element_add_pad(GST_ELEMENT(self), ghost);
    }
}

void ffgui_d3d_mixer_class_init(FfguiD3DMixerClass* klass) {
    auto* objectClass = G_OBJECT_CLASS(klass);
    auto* elementClass = GST_ELEMENT_CLASS(klass);
    objectClass->constructed = ffgui_d3d_mixer_constructed;
    elementClass->request_new_pad = ffgui_d3d_mixer_request_pad;
    elementClass->release_pad = ffgui_d3d_mixer_release_pad;
    gst_element_class_add_static_pad_template(elementClass, &ffgui_d3d_mixer_src_template);
    gst_element_class_add_static_pad_template(elementClass, &ffgui_d3d_mixer_sink_template);
    gst_element_class_set_static_metadata(
        elementClass, "ffmpegGUI D3D11 GES mixer", "Filter/Editor/Video",
        "Applies GES frame composition metadata to a D3D11 compositor",
        "ffmpegGUI contributors");
}

void ffgui_d3d_mixer_init(FfguiD3DMixer*) {}

std::runtime_error glib_error(const std::string& prefix, GError* error);

typedef struct _FfguiDirectD3DEffect FfguiDirectD3DEffect;
typedef struct _FfguiDirectD3DEffectClass FfguiDirectD3DEffectClass;

struct _FfguiDirectD3DEffect {
    GESEffect parent_instance;
};

struct _FfguiDirectD3DEffectClass {
    GESEffectClass parent_class;
};

G_DEFINE_TYPE(FfguiDirectD3DEffect, ffgui_direct_d3d_effect, GES_TYPE_EFFECT)

GstElement* ffgui_direct_d3d_effect_create_element(GESTrackElement* element) {
    gchar* description = nullptr;
    g_object_get(element, "bin-description", &description, nullptr);
    if (description == nullptr) return nullptr;
    GError* error = nullptr;
    auto* result = gst_parse_bin_from_description_full(
        description, TRUE, nullptr,
        static_cast<GstParseFlags>(GST_PARSE_FLAG_PLACE_IN_BIN | GST_PARSE_FLAG_FATAL_ERRORS),
        &error);
    g_free(description);
    if (error != nullptr) {
        GST_ERROR_OBJECT(element, "Could not create native D3D effect: %s", error->message);
        g_error_free(error);
        if (result != nullptr) gst_object_unref(result);
        return nullptr;
    }
    return result;
}

void ffgui_direct_d3d_effect_class_init(FfguiDirectD3DEffectClass* klass) {
    GES_TRACK_ELEMENT_CLASS(klass)->create_element =
        ffgui_direct_d3d_effect_create_element;
}

void ffgui_direct_d3d_effect_init(FfguiDirectD3DEffect*) {}

GESBaseEffect* create_direct_d3d_effect(const std::string& description) {
    const auto assetId = "video " + description;
    GError* error = nullptr;
    auto* asset = ges_asset_request(
        ffgui_direct_d3d_effect_get_type(), assetId.c_str(), &error);
    if (asset == nullptr || error != nullptr) {
        if (asset != nullptr) gst_object_unref(asset);
        throw glib_error("failed to request native D3D effect asset", error);
    }
    auto* effect = GES_BASE_EFFECT(ges_asset_extract(asset, &error));
    gst_object_unref(asset);
    if (effect == nullptr || error != nullptr) {
        if (effect != nullptr) gst_object_unref(effect);
        throw glib_error("failed to extract native D3D effect", error);
    }
    return effect;
}

typedef struct _FfguiD3DVideoTrack FfguiD3DVideoTrack;
typedef struct _FfguiD3DVideoTrackClass FfguiD3DVideoTrackClass;

struct _FfguiD3DVideoTrack {
    GESVideoTrack parent_instance;
};

struct _FfguiD3DVideoTrackClass {
    GESVideoTrackClass parent_class;
};

G_DEFINE_TYPE(FfguiD3DVideoTrack, ffgui_d3d_video_track, GES_TYPE_VIDEO_TRACK)

GstElement* ffgui_d3d_video_track_create_mixer(GESTrack*) {
    return GST_ELEMENT(g_object_new(ffgui_d3d_mixer_get_type(), nullptr));
}

void ffgui_d3d_video_track_class_init(FfguiD3DVideoTrackClass* klass) {
    GES_TRACK_CLASS(klass)->get_mixing_element = ffgui_d3d_video_track_create_mixer;
}

void ffgui_d3d_video_track_init(FfguiD3DVideoTrack*) {}

GstElement* create_d3d_video_gap(GESTrack*) {
    auto* bin = gst_bin_new(nullptr);
    auto* source = gst_element_factory_make("videotestsrc", nullptr);
    auto* rate = gst_element_factory_make("videorate", nullptr);
    auto* upload = gst_element_factory_make("d3d11upload", nullptr);
    auto* capsFilter = gst_element_factory_make("capsfilter", nullptr);
    if (bin == nullptr || source == nullptr || rate == nullptr ||
        upload == nullptr || capsFilter == nullptr) {
        if (source != nullptr) gst_object_unref(source);
        if (rate != nullptr) gst_object_unref(rate);
        if (upload != nullptr) gst_object_unref(upload);
        if (capsFilter != nullptr) gst_object_unref(capsFilter);
        if (bin != nullptr) gst_object_unref(bin);
        return nullptr;
    }
    g_object_set(source, "pattern", 2, nullptr);
    auto* caps = gst_caps_from_string("video/x-raw(memory:D3D11Memory)");
    g_object_set(capsFilter, "caps", caps, nullptr);
    gst_caps_unref(caps);
    gst_bin_add_many(GST_BIN(bin), source, rate, upload, capsFilter, nullptr);
    if (!gst_element_link_many(source, rate, upload, capsFilter, nullptr)) {
        gst_object_unref(bin);
        return nullptr;
    }
    auto* sourcePad = gst_element_get_static_pad(capsFilter, "src");
    auto* ghost = gst_ghost_pad_new("src", sourcePad);
    gst_object_unref(sourcePad);
    if (ghost == nullptr || !gst_element_add_pad(bin, ghost)) {
        if (ghost != nullptr) gst_object_unref(ghost);
        gst_object_unref(bin);
        return nullptr;
    }
    return bin;
}

GESTrackElement* find_core_track_element(GESClip* clip, GESTrackType type) {
    auto* elements = ges_clip_find_track_elements(clip, nullptr, type, G_TYPE_NONE);
    GESTrackElement* result = nullptr;
    for (auto* item = elements; item != nullptr; item = item->next) {
        auto* element = GES_TRACK_ELEMENT(item->data);
        if (ges_track_element_is_core(element)) {
            result = element;
            break;
        }
    }
    g_list_free(elements);
    return result;
}

TimeNs source_control_time(const TimelineSpan& span, TimeNs timeline_local) {
    return checked_add(
        span.clip.source_in, span.clip.source_offset_for_timeline(timeline_local));
}

void bind_linear_control(
    GESTrackElement* element,
    const char* property,
    const std::vector<std::pair<TimeNs, double>>& points) {
    if (element == nullptr || points.empty()) {
        throw std::runtime_error("GES source control has no track element or points");
    }
    auto* source = gst_interpolation_control_source_new();
    if (source == nullptr) throw std::runtime_error("failed to create GES source controller");
    g_object_set(source, "mode", GST_INTERPOLATION_MODE_LINEAR, nullptr);
    auto* timed = GST_TIMED_VALUE_CONTROL_SOURCE(source);
    bool valid = true;
    for (const auto& [time, value] : points) {
        valid = valid && gst_timed_value_control_source_set(
            timed, static_cast<GstClockTime>(time), value);
    }
    const auto bound = valid && ges_track_element_set_control_source(
        element, GST_CONTROL_SOURCE(source), property, "direct-absolute");
    gst_object_unref(source);
    if (!bound) throw std::runtime_error(std::string{"failed to bind GES source property: "} + property);
}

std::vector<std::pair<TimeNs, double>> audio_envelope(
    const TimelineSpan& span, TimeNs outgoing_transition) {
    const auto duration = span.timeline_out - span.timeline_in;
    const auto gain = span.clip.audio.muted ? 0.0 : span.clip.audio.gain;
    const auto fadeIn = std::min(span.clip.audio.fade_in, duration);
    const auto fadeOut = std::min(span.clip.audio.fade_out, duration);
    const auto transitionIn = std::min(span.clip.transition_in, duration);
    const auto transitionOut = std::min(outgoing_transition, duration);
    std::vector<TimeNs> times{
        0, fadeIn, transitionIn, duration - fadeOut, duration - transitionOut, duration};
    std::ranges::sort(times);
    times.erase(std::unique(times.begin(), times.end()), times.end());
    std::vector<std::pair<TimeNs, double>> result;
    result.reserve(times.size());
    for (const auto time : times) {
        auto factor = 1.0;
        if (fadeIn > 0) factor *= std::min(1.0, static_cast<double>(time) / fadeIn);
        if (transitionIn > 0) factor *= std::min(1.0, static_cast<double>(time) / transitionIn);
        if (fadeOut > 0 && time > duration - fadeOut) {
            factor *= static_cast<double>(duration - time) / fadeOut;
        }
        if (transitionOut > 0 && time > duration - transitionOut) {
            factor *= static_cast<double>(duration - time) / transitionOut;
        }
        result.emplace_back(
            source_control_time(span, time), gain * std::clamp(factor, 0.0, 1.0));
    }
    return result;
}

void add_speed_effect(
    GESUriClip* uri_clip, double playback_rate, bool has_audio,
    bool direct_d3d_compositor) {
    if (std::abs(playback_rate - 1.0) < 0.0000005) return;
    const auto attach = [uri_clip](const std::string& description, const char* failure) {
        auto* effect = ges_effect_new(description.c_str());
        if (effect == nullptr ||
            !ges_container_add(GES_CONTAINER(uri_clip), GES_TIMELINE_ELEMENT(effect))) {
            if (effect != nullptr) gst_object_unref(effect);
            throw std::runtime_error(failure);
        }
    };
    std::ostringstream rate;
    rate << std::fixed << std::setprecision(6) << playback_rate;
    if (direct_d3d_compositor) {
        auto* effect = create_direct_d3d_effect("videorate rate=" + rate.str());
        if (effect == nullptr ||
            !ges_container_add(GES_CONTAINER(uri_clip), GES_TIMELINE_ELEMENT(effect))) {
            if (effect != nullptr) gst_object_unref(effect);
            throw std::runtime_error("failed to attach native video playback-rate effect");
        }
    } else {
        attach("videorate rate=" + rate.str(), "failed to attach video playback-rate effect");
    }
    if (has_audio) {
        attach("pitch tempo=" + rate.str(), "failed to attach audio playback-rate effect");
    }
}

void add_legacy_color_effect(GESUriClip* uri_clip, const ClipColor& color) {
    if (color == ClipColor{}) return;
    std::ostringstream description;
    description << std::fixed << std::setprecision(6)
                << "videobalance brightness=" << color.brightness
                << " contrast=" << color.contrast
                << " saturation=" << color.saturation;
    auto* effect = ges_effect_new(description.str().c_str());
    GError* error = nullptr;
    if (effect == nullptr || !ges_clip_add_top_effect(
            GES_CLIP(uri_clip), GES_BASE_EFFECT(effect), -1, &error)) {
        if (effect != nullptr) gst_object_unref(effect);
        throw glib_error("failed to attach clip color effect", error);
    }
}

void add_color_lut_effect(
    GESUriClip* uri_clip, const std::string& lut_id, bool use_d3d11,
    bool direct_d3d_compositor) {
    const auto description = use_d3d11
        ? "ffguid3dcolor lut-id=" + lut_id +
            (direct_d3d_compositor ? " direct-output=true" : "")
        : "videoconvert ! video/x-raw,format=RGBA64_LE ! ffguilut3d lut-id=" + lut_id +
          " ! videoconvert";
    auto* effect = direct_d3d_compositor
        ? create_direct_d3d_effect(description)
        : GES_BASE_EFFECT(ges_effect_new(description.c_str()));
    GError* error = nullptr;
    if (effect == nullptr || !ges_clip_add_top_effect(
            GES_CLIP(uri_clip), effect, -1, &error)) {
        if (effect != nullptr) gst_object_unref(effect);
        throw glib_error("failed to attach clip color LUT effect", error);
    }
}

void add_ocio_shader_effect(
    GESUriClip* uri_clip, const std::string& shader_id, bool direct_d3d_compositor) {
    const auto description = "ffguid3dcolor shader-id=" + shader_id +
        (direct_d3d_compositor ? " direct-output=true" : "");
    auto* effect = direct_d3d_compositor
        ? create_direct_d3d_effect(description)
        : GES_BASE_EFFECT(ges_effect_new(description.c_str()));
    GError* error = nullptr;
    if (effect == nullptr || !ges_clip_add_top_effect(
            GES_CLIP(uri_clip), effect, -1, &error)) {
        if (effect != nullptr) gst_object_unref(effect);
        throw glib_error("failed to attach exact OCIO source shader", error);
    }
}

std::string path_to_utf8(const std::filesystem::path& path) {
    const auto value = path.u8string();
    return {reinterpret_cast<const char*>(value.data()), value.size()};
}

std::runtime_error glib_error(const std::string& prefix, GError* error) {
    std::string message = prefix;
    if (error != nullptr && error->message != nullptr) {
        message += ": ";
        message += error->message;
        g_error_free(error);
    }
    return std::runtime_error(message);
}

void require_ges(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

std::string take_bus_error(GstElement* element) {
    auto* bus = gst_element_get_bus(element);
    if (bus == nullptr) return {};
    auto* message = gst_bus_pop_filtered(bus, GST_MESSAGE_ERROR);
    gst_object_unref(bus);
    if (message == nullptr) return {};
    GError* error = nullptr;
    gchar* debug = nullptr;
    gst_message_parse_error(message, &error, &debug);
    std::string detail;
    if (error != nullptr && error->message != nullptr) detail = error->message;
    if (debug != nullptr && *debug != '\0') {
        if (!detail.empty()) detail += " | ";
        detail += debug;
    }
    if (error != nullptr) g_error_free(error);
    g_free(debug);
    gst_message_unref(message);
    return detail;
}

struct PreviewGraphStats final {
    std::uint64_t d3d_compositors{};
    std::uint64_t d3d_downloads{};
    std::uint64_t system_compositors{};
    std::uint64_t composition_frames{};
    std::uint64_t composition_meta_frames{};
    std::uint64_t blended_frames{};
};

PreviewGraphStats inspect_preview_graph(GstElement* root) {
    PreviewGraphStats stats;
    if (root == nullptr || !GST_IS_BIN(root)) return stats;
    auto* iterator = gst_bin_iterate_recurse(GST_BIN(root));
    GValue value = G_VALUE_INIT;
    while (true) {
        const auto result = gst_iterator_next(iterator, &value);
        if (result == GST_ITERATOR_OK) {
            auto* element = GST_ELEMENT(g_value_get_object(&value));
            auto* factory = element != nullptr ? gst_element_get_factory(element) : nullptr;
            const auto* name = factory != nullptr
                ? gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory)) : nullptr;
            if (g_strcmp0(name, "d3d11compositor") == 0) ++stats.d3d_compositors;
            else if (g_strcmp0(name, "d3d11download") == 0) ++stats.d3d_downloads;
            else if (g_strcmp0(name, "compositor") == 0) ++stats.system_compositors;
            if (G_TYPE_CHECK_INSTANCE_TYPE(element, ffgui_d3d_mixer_get_type())) {
                auto* mixer = reinterpret_cast<FfguiD3DMixer*>(element);
                stats.composition_frames += static_cast<std::uint64_t>(
                    std::max(0, g_atomic_int_get(&mixer->composition_frames)));
                stats.composition_meta_frames += static_cast<std::uint64_t>(
                    std::max(0, g_atomic_int_get(&mixer->composition_meta_frames)));
                stats.blended_frames += static_cast<std::uint64_t>(
                    std::max(0, g_atomic_int_get(&mixer->blended_frames)));
            }
            g_value_reset(&value);
            continue;
        }
        if (result == GST_ITERATOR_RESYNC) {
            gst_iterator_resync(iterator);
            continue;
        }
        break;
    }
    if (G_VALUE_TYPE(&value) != 0) g_value_unset(&value);
    gst_iterator_free(iterator);
    return stats;
}

GESTimeline* create_preview_timeline(bool direct_d3d_compositor) {
    if (!direct_d3d_compositor) return ges_timeline_new_audio_video();

    auto* timeline = ges_timeline_new();
    auto* audioTrack = ges_audio_track_new();
    auto* trackCaps = gst_caps_from_string("video/x-raw(ANY)");
    auto* videoTrack = trackCaps != nullptr
        ? GES_TRACK(g_object_new(
            ffgui_d3d_video_track_get_type(),
            "track-type", GES_TRACK_TYPE_VIDEO,
            "caps", trackCaps,
            nullptr))
        : nullptr;
    if (trackCaps != nullptr) gst_caps_unref(trackCaps);
    if (videoTrack != nullptr) {
        ges_track_set_create_element_for_gap_func(videoTrack, create_d3d_video_gap);
    }
    if (timeline == nullptr || audioTrack == nullptr || videoTrack == nullptr) {
        if (videoTrack != nullptr) gst_object_unref(videoTrack);
        if (audioTrack != nullptr) gst_object_unref(audioTrack);
        if (timeline != nullptr) gst_object_unref(timeline);
        return nullptr;
    }

    auto* caps = gst_caps_from_string(
        "video/x-raw(memory:D3D11Memory),format=RGBA64_LE");
    if (caps != nullptr) ges_track_set_restriction_caps(videoTrack, caps);
    const bool audioAdded = caps != nullptr &&
        ges_timeline_add_track(timeline, GES_TRACK(audioTrack));
    const bool videoAdded = audioAdded && ges_timeline_add_track(timeline, videoTrack);
    if (caps != nullptr) gst_caps_unref(caps);
    if (!videoAdded) {
        if (!audioAdded) gst_object_unref(audioTrack);
        gst_object_unref(videoTrack);
        gst_object_unref(timeline);
        return nullptr;
    }
    return timeline;
}

[[nodiscard]] std::string source_color_lut_id(const std::string& clip_id) {
    return "clip-lut-" + clip_id;
}

[[nodiscard]] std::string source_color_shader_id(const std::string& clip_id) {
    return "clip-ocio-" + clip_id;
}

[[nodiscard]] bool preview_structure_matches(
    const TimelineSpan& left, const TimelineSpan& right) {
    return left.clip.id == right.clip.id &&
        left.clip.asset_id == right.clip.asset_id &&
        left.clip.source_in == right.clip.source_in &&
        left.clip.duration == right.clip.duration &&
        left.clip.playback_rate == right.clip.playback_rate &&
        left.clip.audio == right.clip.audio &&
        left.clip.transition_in == right.clip.transition_in &&
        left.source_path == right.source_path &&
        left.timeline_in == right.timeline_in &&
        left.timeline_out == right.timeline_out &&
        left.has_audio == right.has_audio;
}

[[nodiscard]] bool needs_source_color(
    const TimelineSpan& span,
    const ColorPipelineSettings& pipeline,
    bool legacy_source_color,
    bool direct_d3d) {
    const auto managed = pipeline.mode != ColorPipelineMode::legacy;
    const auto directLegacyColor = direct_d3d && legacy_source_color &&
        span.clip.color != ClipColor{};
    return managed || !span.clip.grade.nodes().empty() || directLegacyColor;
}

struct PreparedSourceColor final {
    std::string clip_id;
    std::string lut_id;
    std::string shader_id;
    std::shared_ptr<const ColorCube> cube;
    std::shared_ptr<const OcioGpuShader> shader;
    std::shared_ptr<const ColorLutRecipe> recipe;
};

[[nodiscard]] std::optional<PreparedSourceColor> prepare_source_color(
    const TimelineSpan& span,
    const ColorPipelineSettings& pipeline,
    const std::string& output_space,
    bool legacy_source_color,
    bool direct_d3d,
    bool d3d11_lut_available) {
    if (!needs_source_color(span, pipeline, legacy_source_color, direct_d3d)) {
        return std::nullopt;
    }
    const auto managed = pipeline.mode != ColorPipelineMode::legacy;
    const auto grade = (managed || direct_d3d)
        ? compose_clip_grade(span.clip) : span.clip.grade;
    const auto outputSpace = managed ? output_space : std::string{};
    PreparedSourceColor prepared;
    prepared.clip_id = span.clip.id;
    prepared.lut_id = source_color_lut_id(span.clip.id);
    const auto animated = grade.has_keyframes();
    if (managed && d3d11_lut_available) {
        prepared.shader_id = source_color_shader_id(span.clip.id);
        prepared.shader = std::make_shared<const OcioGpuShader>(
            build_managed_gpu_shader(
                span.source_color, pipeline, grade, outputSpace, 33, 0));
    } else {
        prepared.cube = std::make_shared<const ColorCube>(build_color_cube(
            span.source_color, pipeline, grade, outputSpace, 33, 0));
    }
    if (animated) {
        ColorLutRecipe recipe;
        recipe.source_color = span.source_color;
        recipe.settings = pipeline;
        recipe.grade = grade;
        recipe.output_space = outputSpace;
        recipe.cube_size = 33;
        recipe.source_in = span.clip.source_in;
        recipe.timeline_in = span.timeline_in;
        recipe.playback_rate = span.clip.playback_rate;
        recipe.animated = true;
        recipe.working_space_grade_only = prepared.shader != nullptr;
        prepared.recipe = std::make_shared<const ColorLutRecipe>(std::move(recipe));
    }
    return prepared;
}

[[nodiscard]] std::vector<std::optional<PreparedSourceColor>> prepare_source_colors(
    const std::vector<TimelineSpan>& spans,
    const ColorPipelineSettings& pipeline,
    const std::string& output_space,
    bool legacy_source_color,
    bool direct_d3d,
    bool d3d11_lut_available) {
    std::vector<std::optional<PreparedSourceColor>> prepared;
    prepared.reserve(spans.size());
    for (const auto& span : spans) {
        prepared.push_back(prepare_source_color(
            span, pipeline, output_space, legacy_source_color, direct_d3d,
            d3d11_lut_available));
    }
    return prepared;
}

void publish_prepared_source_color(const PreparedSourceColor& prepared) {
    if (prepared.shader != nullptr) {
        publish_gst_d3d11_ocio_shader(prepared.shader_id, prepared.shader);
    }
    if (prepared.cube != nullptr) {
        publish_gst_color_lut(prepared.lut_id, prepared.cube);
    }
    if (prepared.recipe != nullptr) {
        if (!prepared.lut_id.empty()) {
            publish_gst_color_recipe(prepared.lut_id, prepared.recipe);
        }
        if (!prepared.shader_id.empty()) {
            publish_gst_color_recipe(prepared.shader_id, prepared.recipe);
        }
    }
}

}  // namespace

GesSequencePlayer::GesSequencePlayer(
    std::string video_sink_factory,
    std::string audio_sink_factory)
    : video_sink_factory_(std::move(video_sink_factory)),
      audio_sink_factory_(std::move(audio_sink_factory)) {
    gst_init(nullptr, nullptr);
    if (!register_gst_color_lut_filter()) {
        throw std::runtime_error("failed to register ffmpegGUI color LUT filter");
    }
    if (!register_gst_d3d11_color_lut_filter()) {
        throw std::runtime_error("failed to register ffmpegGUI D3D11 color LUT filter");
    }
    if (!register_gst_d3d11_color_bin()) {
        throw std::runtime_error("failed to register ffmpegGUI D3D11 color bin");
    }
    d3d11_color_lut_available_ = g_getenv("FFGUI_FORCE_CPU_COLOR") == nullptr &&
        gst_d3d11_color_lut_available();
    direct_d3d_compositor_enabled_ = d3d11_color_lut_available_ &&
        video_sink_factory_ == "d3d11-appsink" &&
        g_getenv("FFGUI_FORCE_SYSTEM_COMPOSITOR") == nullptr;
    if (direct_d3d_compositor_enabled_) {
        auto* compositor = gst_element_factory_find("d3d11compositor");
        if (compositor == nullptr) direct_d3d_compositor_enabled_ = false;
        else gst_object_unref(compositor);
    }
    if (!ges_init()) {
        throw std::runtime_error("failed to initialize GStreamer Editing Services");
    }
    monitor_thread_ = std::jthread([this](std::stop_token token) { monitor(token); });
}

GesSequencePlayer::~GesSequencePlayer() {
    monitor_thread_.request_stop();
    if (monitor_thread_.joinable()) {
        monitor_thread_.join();
    }
    std::scoped_lock lock(mutex_);
    destroy_pipeline_locked();
    source_automation_bindings_.store(0);
    source_color_lut_bindings_.store(0);
    source_gpu_color_lut_bindings_.store(0);
    source_gpu_ocio_shader_bindings_.store(0);
    d3d_compositor_instances_.store(0);
    d3d_download_instances_.store(0);
    system_compositor_instances_.store(0);
    d3d_composition_frames_.store(0);
    d3d_composition_meta_frames_.store(0);
    d3d_blended_frames_.store(0);
}

std::uint64_t GesSequencePlayer::d3d_composition_frames() const noexcept {
    std::scoped_lock lock(mutex_);
    if (pipeline_ == nullptr) return d3d_composition_frames_.load();
    return inspect_preview_graph(GST_ELEMENT(pipeline_)).composition_frames;
}

std::uint64_t GesSequencePlayer::d3d_composition_meta_frames() const noexcept {
    std::scoped_lock lock(mutex_);
    if (pipeline_ == nullptr) return d3d_composition_meta_frames_.load();
    return inspect_preview_graph(GST_ELEMENT(pipeline_)).composition_meta_frames;
}

std::uint64_t GesSequencePlayer::d3d_blended_frames() const noexcept {
    std::scoped_lock lock(mutex_);
    if (pipeline_ == nullptr) return d3d_blended_frames_.load();
    return inspect_preview_graph(GST_ELEMENT(pipeline_)).blended_frames;
}

void GesSequencePlayer::set_timeline(std::vector<TimelineSpan> timeline) {
    set_timeline(std::move(timeline), {});
}

void GesSequencePlayer::set_timeline(
    std::vector<TimelineSpan> timeline,
    std::vector<CaptionCue> captions) {
    ColorPipelineSettings colorPipeline;
    std::string colorOutputSpace;
    {
        std::scoped_lock colorLock(color_settings_mutex_);
        colorPipeline = color_pipeline_;
        colorOutputSpace = color_output_space_;
    }
    auto prepared = std::make_shared<const std::vector<std::optional<PreparedSourceColor>>>(
        prepare_source_colors(
            timeline, colorPipeline, colorOutputSpace,
            legacy_source_color_enabled_.load(std::memory_order_acquire),
            direct_d3d_compositor_enabled_, d3d11_color_lut_available_));
    {
        std::scoped_lock lock(mutex_);
        source_color_bake_ = prepared;
        try {
            rebuild_pipeline_locked(timeline, captions);
        } catch (...) {
            source_color_bake_.reset();
            throw;
        }
        source_color_bake_.reset();
        preview_spans_ = std::move(timeline);
    }
    position_ns_.store(0);
    state_.store(PlaybackState::stopped);
    notify_state(PlaybackState::stopped);
}

void GesSequencePlayer::seek(TimeNs timeline_position) {
    std::unique_lock lock(mutex_);
    const auto target = std::max<TimeNs>(0, std::min(timeline_position, duration_ns_.load()));
    if (pipeline_ == nullptr) {
        return;
    }
    auto* pipeline = GST_ELEMENT(pipeline_);
    bool notifyPaused = false;
    if (state_.load() == PlaybackState::stopped) {
        auto prepareResult = gst_element_set_state(pipeline, GST_STATE_PAUSED);
        GstState current = GST_STATE_VOID_PENDING;
        GstState pending = GST_STATE_VOID_PENDING;
        if (prepareResult == GST_STATE_CHANGE_ASYNC) {
            prepareResult = gst_element_get_state(
                pipeline, &current, &pending, 5 * GST_SECOND);
        } else if (prepareResult != GST_STATE_CHANGE_FAILURE) {
            gst_element_get_state(pipeline, &current, &pending, 0);
        }
        const bool pausePending = pending == GST_STATE_PAUSED;
        if (prepareResult == GST_STATE_CHANGE_FAILURE ||
            (current != GST_STATE_PAUSED && !pausePending)) {
            GST_DEBUG_BIN_TO_DOT_FILE_WITH_TS(
                GST_BIN(pipeline), GST_DEBUG_GRAPH_SHOW_ALL, "ffgui-preview-prepare-failed");
            std::ostringstream detail;
            detail << "GES preview could not enter paused state before seek"
                   << " (current=" << gst_element_state_get_name(current)
                   << ", pending=" << gst_element_state_get_name(pending)
                   << ", result=" << static_cast<int>(prepareResult) << ')';
            const auto busError = take_bus_error(pipeline);
            if (!busError.empty()) detail << " | " << busError;
            throw std::runtime_error(detail.str());
        }
        state_.store(PlaybackState::paused);
        notifyPaused = true;
    }
    auto* bus = gst_element_get_bus(pipeline);
    while (auto* stale = gst_bus_pop_filtered(bus, GST_MESSAGE_ASYNC_DONE)) {
        gst_message_unref(stale);
    }
    const auto waitForPreroll = state_.load() == PlaybackState::paused;
    const auto flags = static_cast<GstSeekFlags>(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_ACCURATE);
    if (!gst_element_seek_simple(pipeline, GST_FORMAT_TIME, flags, target)) {
        gst_object_unref(bus);
        throw std::runtime_error("GES timeline seek failed");
    }
    if (waitForPreroll) {
        auto* message = gst_bus_timed_pop_filtered(
            bus,
            5 * GST_SECOND,
            static_cast<GstMessageType>(GST_MESSAGE_ASYNC_DONE | GST_MESSAGE_ERROR));
        if (message == nullptr) {
            gst_object_unref(bus);
            throw std::runtime_error("GES timeline seek preroll timed out");
        }
        if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
            GError* error = nullptr;
            gchar* debug = nullptr;
            gst_message_parse_error(message, &error, &debug);
            const auto failure = glib_error("GES timeline seek preroll failed", error);
            g_free(debug);
            gst_message_unref(message);
            gst_object_unref(bus);
            throw failure;
        }
        gst_message_unref(message);
    }
    const auto graph = inspect_preview_graph(pipeline);
    d3d_compositor_instances_.store(graph.d3d_compositors);
    d3d_download_instances_.store(graph.d3d_downloads);
    system_compositor_instances_.store(graph.system_compositors);
    d3d_composition_frames_.store(graph.composition_frames);
    d3d_composition_meta_frames_.store(graph.composition_meta_frames);
    d3d_blended_frames_.store(graph.blended_frames);
    gst_object_unref(bus);
    lock.unlock();
    position_ns_.store(target);
    if (notifyPaused) notify_state(PlaybackState::paused);
}

void GesSequencePlayer::play() {
    {
        std::scoped_lock lock(mutex_);
        if (pipeline_ == nullptr) {
            return;
        }
        const auto result = gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_PLAYING);
        if (result == GST_STATE_CHANGE_FAILURE) {
            throw std::runtime_error("GES pipeline failed to start playback");
        }
    }
    state_.store(PlaybackState::playing);
    notify_state(PlaybackState::playing);
}

void GesSequencePlayer::pause() {
    std::unique_lock lock(mutex_);
    if (pipeline_ == nullptr) {
        return;
    }
    auto* pipeline = GST_ELEMENT(pipeline_);
    auto result = gst_element_set_state(pipeline, GST_STATE_PAUSED);
    GstState current = GST_STATE_VOID_PENDING;
    GstState pending = GST_STATE_VOID_PENDING;
    if (result == GST_STATE_CHANGE_ASYNC) {
        result = gst_element_get_state(pipeline, &current, &pending, 5 * GST_SECOND);
    } else if (result != GST_STATE_CHANGE_FAILURE) {
        gst_element_get_state(pipeline, &current, &pending, 0);
    }
    if (result == GST_STATE_CHANGE_FAILURE || current != GST_STATE_PAUSED) {
        throw std::runtime_error("GES pipeline failed to preroll into paused state");
    }
    state_.store(PlaybackState::paused);
    lock.unlock();
    notify_state(PlaybackState::paused);
}

void GesSequencePlayer::stop() {
    {
        std::scoped_lock lock(mutex_);
        if (pipeline_ == nullptr) {
            return;
        }
        gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_READY);
    }
    position_ns_.store(0);
    state_.store(PlaybackState::stopped);
    notify_state(PlaybackState::stopped);
}

void GesSequencePlayer::set_position_callback(PositionCallback callback) {
    std::scoped_lock lock(callback_mutex_);
    position_callback_ = std::move(callback);
}

void GesSequencePlayer::set_state_callback(StateCallback callback) {
    std::scoped_lock lock(callback_mutex_);
    state_callback_ = std::move(callback);
}

void GesSequencePlayer::set_error_callback(ErrorCallback callback) {
    std::scoped_lock lock(callback_mutex_);
    error_callback_ = std::move(callback);
}

void GesSequencePlayer::set_video_window_handle(std::uintptr_t window_handle) {
    std::scoped_lock lock(mutex_);
    video_window_handle_ = window_handle;
    if (video_sink_ != nullptr && GST_IS_VIDEO_OVERLAY(video_sink_)) {
        gst_video_overlay_set_window_handle(
            GST_VIDEO_OVERLAY(video_sink_),
            static_cast<guintptr>(video_window_handle_));
    }
}

void GesSequencePlayer::set_d3d11_device(void* device) {
    d3d11_device_handle_.store(device, std::memory_order_release);
}

void GesSequencePlayer::set_video_sink_factory(std::string factory) {
    if (factory.empty()) factory = "fakesink";
    std::scoped_lock lock(mutex_);
    video_sink_factory_ = std::move(factory);
}

void GesSequencePlayer::set_video_frame_callback(
    std::function<void(PreviewVideoFrame)> callback) {
    std::scoped_lock lock(callback_mutex_);
    video_frame_callback_ = std::move(callback);
}

void GesSequencePlayer::set_scope_frame_callback(
    std::function<void(PreviewVideoFrame)> callback) {
    std::scoped_lock lock(callback_mutex_);
    scope_frame_callback_ = std::move(callback);
}

void GesSequencePlayer::set_float_output_enabled(bool enabled) {
    float_output_enabled_.store(enabled, std::memory_order_release);
}

void GesSequencePlayer::set_legacy_source_color_enabled(bool enabled) {
    legacy_source_color_enabled_.store(enabled, std::memory_order_release);
}

void GesSequencePlayer::set_color_pipeline(
    ColorPipelineSettings settings, std::string output_space) {
    settings.validate();
    std::scoped_lock lock(color_settings_mutex_);
    color_pipeline_ = std::move(settings);
    color_output_space_ = std::move(output_space);
}

bool GesSequencePlayer::can_live_update_source_color_locked(
    const std::vector<TimelineSpan>& timeline) const {
    if (pipeline_ == nullptr || preview_spans_.size() != timeline.size()) return false;
    ColorPipelineSettings pipeline;
    {
        std::scoped_lock colorLock(color_settings_mutex_);
        pipeline = color_pipeline_;
    }
    const auto legacy = legacy_source_color_enabled_.load(std::memory_order_acquire);
    for (std::size_t index = 0; index < timeline.size(); ++index) {
        if (!preview_structure_matches(preview_spans_[index], timeline[index])) return false;
        if (needs_source_color(
                preview_spans_[index], pipeline, legacy, direct_d3d_compositor_enabled_) !=
            needs_source_color(
                timeline[index], pipeline, legacy, direct_d3d_compositor_enabled_)) {
            return false;
        }
    }
    return true;
}

bool GesSequencePlayer::update_source_color(const std::vector<TimelineSpan>& timeline) {
    ColorPipelineSettings colorPipeline;
    std::string colorOutputSpace;
    {
        std::scoped_lock colorLock(color_settings_mutex_);
        colorPipeline = color_pipeline_;
        colorOutputSpace = color_output_space_;
    }
    auto prepared = prepare_source_colors(
        timeline, colorPipeline, colorOutputSpace,
        legacy_source_color_enabled_.load(std::memory_order_acquire),
        direct_d3d_compositor_enabled_, d3d11_color_lut_available_);
    std::scoped_lock lock(mutex_);
    if (!can_live_update_source_color_locked(timeline)) return false;
    for (const auto& color : prepared) {
        if (color.has_value()) publish_prepared_source_color(*color);
    }
    preview_spans_ = timeline;
    return true;
}

TimeNs GesSequencePlayer::duration() const noexcept {
    return duration_ns_.load();
}

TimeNs GesSequencePlayer::position() const noexcept {
    return position_ns_.load();
}

PlaybackState GesSequencePlayer::state() const noexcept {
    return state_.load();
}

void GesSequencePlayer::reset_audio_continuity_metrics() noexcept {
    audio_buffer_count_.store(0);
    audio_last_end_ns_.store(-1);
    audio_maximum_gap_ns_.store(0);
}

AudioContinuityMetrics GesSequencePlayer::audio_continuity_metrics() const noexcept {
    return AudioContinuityMetrics{audio_buffer_count_.load(), audio_maximum_gap_ns_.load()};
}

void GesSequencePlayer::audio_handoff(GstElement*, GstBuffer* buffer, GstPad*, void* user_data) {
    auto* player = static_cast<GesSequencePlayer*>(user_data);
    if (player == nullptr || buffer == nullptr || !GST_BUFFER_PTS_IS_VALID(buffer)) return;
    const auto pts = static_cast<TimeNs>(GST_BUFFER_PTS(buffer));
    const auto duration = GST_BUFFER_DURATION_IS_VALID(buffer)
        ? static_cast<TimeNs>(GST_BUFFER_DURATION(buffer))
        : 0;
    const auto end = duration <= std::numeric_limits<TimeNs>::max() - pts
        ? pts + duration
        : std::numeric_limits<TimeNs>::max();
    const auto previousEnd = player->audio_last_end_ns_.exchange(end);
    player->audio_buffer_count_.fetch_add(1);
    if (previousEnd < 0 || pts <= previousEnd) return;
    const auto gap = pts - previousEnd;
    auto maximum = player->audio_maximum_gap_ns_.load();
    while (gap > maximum &&
           !player->audio_maximum_gap_ns_.compare_exchange_weak(maximum, gap)) {
    }
}

GstFlowReturn GesSequencePlayer::new_video_sample(GstAppSink* sink, void* user_data) {
    auto* player = static_cast<GesSequencePlayer*>(user_data);
    if (player == nullptr) return GST_FLOW_ERROR;
    auto* sample = gst_app_sink_pull_sample(sink);
    if (sample == nullptr) return GST_FLOW_EOS;
    auto holder = std::shared_ptr<void>(sample, [](void* value) {
        gst_sample_unref(static_cast<GstSample*>(value));
    });
    auto* buffer = gst_sample_get_buffer(sample);
    auto* memory = buffer != nullptr && gst_buffer_n_memory(buffer) > 0
        ? gst_buffer_peek_memory(buffer, 0)
        : nullptr;
    std::function<void(PreviewVideoFrame)> callback;
    std::function<void(PreviewVideoFrame)> scopeCallback;
    {
        std::scoped_lock lock(player->callback_mutex_);
        callback = player->video_frame_callback_;
        scopeCallback = player->scope_frame_callback_;
    }
    if (!callback || buffer == nullptr || memory == nullptr) return GST_FLOW_OK;

    PreviewVideoFrame frame;
    frame.sample = std::move(holder);
    frame.pts = GST_BUFFER_PTS_IS_VALID(buffer)
        ? static_cast<TimeNs>(GST_BUFFER_PTS(buffer))
        : 0;
    if (player->state_.load(std::memory_order_acquire) == PlaybackState::playing) {
        std::scoped_lock cutLock(player->cut_points_mutex_);
        // One output frame can be timestamped just before or after the logical cut.
        constexpr TimeNs cutGuard = 20'000'000;
        const auto atHardCut = std::ranges::any_of(
            player->hard_cut_points_,
            [pts = frame.pts](TimeNs cut) { return std::abs(pts - cut) <= cutGuard; });
        if (atHardCut) {
            // GES can briefly emit its compositor background exactly at a zero-length cut.
            // Keep the previous presented frame until the next clip's first real frame.
            return GST_FLOW_OK;
        }
    }
    if (gst_is_d3d11_memory(memory)) {
        auto* d3dMemory = GST_D3D11_MEMORY_CAST(memory);
        D3D11_TEXTURE2D_DESC description{};
        if (!gst_d3d11_memory_get_texture_desc(d3dMemory, &description)) return GST_FLOW_OK;
        auto* resource = gst_d3d11_memory_get_resource_handle(d3dMemory);
        if (resource == nullptr) return GST_FLOW_OK;
        ID3D11Texture2D* texture = nullptr;
        if (FAILED(resource->QueryInterface(__uuidof(ID3D11Texture2D),
                                            reinterpret_cast<void**>(&texture))) ||
            texture == nullptr) {
            return GST_FLOW_OK;
        }
        frame.texture_owner = std::shared_ptr<void>(texture, [](void* value) {
            static_cast<ID3D11Texture2D*>(value)->Release();
        });
        frame.texture = texture;
        frame.width = description.Width;
        frame.height = description.Height;
        frame.texture_subresource = gst_d3d11_memory_get_subresource_index(d3dMemory);
        frame.device = gst_d3d11_device_get_device_handle(d3dMemory->device);
    } else {
        GstVideoInfo videoInfo{};
        auto* caps = gst_sample_get_caps(sample);
        if (caps == nullptr || !gst_video_info_from_caps(&videoInfo, caps)) {
            return GST_FLOW_OK;
        }
        const auto format = GST_VIDEO_INFO_FORMAT(&videoInfo);
        const auto rgba16 = format == GST_VIDEO_FORMAT_RGBA64_LE;
        if (!rgba16 && format != GST_VIDEO_FORMAT_BGRA) return GST_FLOW_OK;
        GstMapInfo map{};
        if (!gst_buffer_map(buffer, &map, GST_MAP_READ)) return GST_FLOW_OK;
        frame.width = GST_VIDEO_INFO_WIDTH(&videoInfo);
        frame.height = GST_VIDEO_INFO_HEIGHT(&videoInfo);
        frame.cpu_stride = frame.width * (rgba16 ? 8U : 4U);
        frame.cpu_format = rgba16 ? PreviewCpuFormat::rgba16le : PreviewCpuFormat::bgra8;
        const auto sourceStride = GST_VIDEO_INFO_PLANE_STRIDE(&videoInfo, 0);
        const auto rowBytes = static_cast<std::size_t>(frame.cpu_stride);
        if (sourceStride < 0 || static_cast<std::size_t>(sourceStride) < rowBytes ||
            map.size < static_cast<std::size_t>(sourceStride) * frame.height) {
            gst_buffer_unmap(buffer, &map);
            return GST_FLOW_OK;
        }
        frame.cpu_pixels = std::make_shared<std::vector<std::uint8_t>>(
            rowBytes * frame.height);
        for (std::uint32_t row = 0; row < frame.height; ++row) {
            std::memcpy(
                frame.cpu_pixels->data() + static_cast<std::size_t>(row) * rowBytes,
                map.data + static_cast<std::size_t>(row) * sourceStride,
                rowBytes);
        }
        gst_buffer_unmap(buffer, &map);
        // CPU pixels are now independent; release the decoder sample immediately instead of
        // pinning a GStreamer buffer until Qt replaces the displayed frame.
        frame.sample.reset();
    }
    frame.serial = player->video_frame_serial_.fetch_add(1) + 1;
    bool deliverScope = false;
    if (player->scope_capture_enabled_.load(std::memory_order_acquire) && scopeCallback) {
        const auto pts = static_cast<std::uint64_t>(std::max<TimeNs>(0, frame.pts));
        const auto previous = player->scope_last_pts_.load(std::memory_order_relaxed);
        constexpr auto interval = static_cast<std::uint64_t>(GST_SECOND / 10);
        if (previous == GST_CLOCK_TIME_NONE || pts < previous || pts - previous >= interval) {
            player->scope_last_pts_.store(pts, std::memory_order_relaxed);
            deliverScope = true;
        }
    }
    auto scopeFrame = deliverScope ? frame : PreviewVideoFrame{};
    callback(std::move(frame));
    if (deliverScope) scopeCallback(std::move(scopeFrame));
    return GST_FLOW_OK;
}

void GesSequencePlayer::rebuild_pipeline_locked(
    const std::vector<TimelineSpan>& spans,
    const std::vector<CaptionCue>& captions) {
    destroy_pipeline_locked();
    source_automation_bindings_.store(0);
    source_color_lut_bindings_.store(0);
    source_gpu_color_lut_bindings_.store(0);
    source_gpu_ocio_shader_bindings_.store(0);
    d3d_compositor_instances_.store(0);
    d3d_download_instances_.store(0);
    system_compositor_instances_.store(0);
    d3d_composition_frames_.store(0);
    d3d_composition_meta_frames_.store(0);
    d3d_blended_frames_.store(0);
    const auto* pending_source_colors =
        static_cast<const std::vector<std::optional<PreparedSourceColor>>*>(
            source_color_bake_.get());
    if (pending_source_colors != nullptr) {
        for (const auto& color : *pending_source_colors) {
            if (!color.has_value()) continue;
            publish_prepared_source_color(*color);
            if (!color->lut_id.empty()) registered_lut_ids_.push_back(color->lut_id);
            if (!color->shader_id.empty()) registered_ocio_shader_ids_.push_back(color->shader_id);
        }
    }
    if (spans.empty()) {
        duration_ns_.store(0);
        std::scoped_lock cutLock(cut_points_mutex_);
        hard_cut_points_.clear();
        return;
    }
    ColorPipelineSettings colorPipeline;
    std::string colorOutputSpace;
    {
        std::scoped_lock colorLock(color_settings_mutex_);
        colorPipeline = color_pipeline_;
        colorOutputSpace = color_output_space_;
    }

    {
        std::scoped_lock cutLock(cut_points_mutex_);
        hard_cut_points_.clear();
        for (std::size_t index = 1; index < spans.size(); ++index) {
            if (spans[index].clip.transition_in == 0) {
                hard_cut_points_.push_back(spans[index].timeline_in);
            }
        }
    }

    auto* new_timeline = create_preview_timeline(direct_d3d_compositor_enabled_);
    auto* layer = ges_layer_new();
    if (new_timeline == nullptr || layer == nullptr) {
        if (new_timeline != nullptr) {
            gst_object_unref(new_timeline);
        }
        if (layer != nullptr) {
            gst_object_unref(layer);
        }
        throw std::runtime_error("failed to create GES timeline");
    }
    gst_object_ref_sink(new_timeline);
    if (!ges_timeline_add_layer(new_timeline, layer)) {
        gst_object_unref(layer);
        gst_object_unref(new_timeline);
        throw std::runtime_error("failed to add GES layer");
    }
    // GES 1.28 transition creation can dereference an unresolved native element while a
    // rapidly edited overlap is rebuilt. A frame-server compositor will replace it; until
    // then a hard preview cut is safer than a process-wide native crash.
    g_object_set(layer, "auto-transition", FALSE, nullptr);
    GESLayer* captionLayer = nullptr;
    if (!captions.empty()) {
        captionLayer = ges_layer_new();
        if (captionLayer == nullptr || !ges_timeline_add_layer(new_timeline, captionLayer)) {
            if (captionLayer != nullptr) gst_object_unref(captionLayer);
            gst_object_unref(new_timeline);
            throw std::runtime_error("failed to add GES caption layer");
        }
    }

    try {
        std::vector<GESUriClip*> uriClips;
        uriClips.reserve(spans.size());
        for (const auto& span : spans) {
            GError* error = nullptr;
            const auto path = path_to_utf8(span.source_path);
            gchar* uri = gst_filename_to_uri(path.c_str(), &error);
            if (uri == nullptr) {
                throw glib_error("failed to convert media path to URI", error);
            }
            auto* uri_clip = ges_uri_clip_new(uri);
            g_free(uri);
            if (uri_clip == nullptr) {
                throw std::runtime_error("failed to create GES URI clip");
            }

            auto* element = GES_TIMELINE_ELEMENT(uri_clip);
            const auto timelineDuration = span.timeline_out - span.timeline_in;
            const bool configured =
                ges_timeline_element_set_start(element, span.timeline_in) &&
                ges_timeline_element_set_inpoint(element, span.clip.source_in) &&
                ges_timeline_element_set_duration(element, timelineDuration);
            if (!configured) {
                gst_object_unref(uri_clip);
                throw std::runtime_error("failed to configure GES clip");
            }
            // GESEffect only receives its concrete child GstElement once its parent clip is
            // in a timeline with tracks. Setting child properties or control bindings before
            // this point produces null native objects on current GStreamer releases.
            if (!ges_layer_add_clip(layer, GES_CLIP(uri_clip))) {
                gst_object_unref(uri_clip);
                throw std::runtime_error("failed to add GES clip to its layer");
            }
            uriClips.push_back(uri_clip);
            add_speed_effect(
                uri_clip, span.clip.playback_rate, span.has_audio,
                direct_d3d_compositor_enabled_);
            const auto legacySourceColor =
                legacy_source_color_enabled_.load(std::memory_order_acquire);
            if (legacySourceColor && !direct_d3d_compositor_enabled_) {
                add_legacy_color_effect(uri_clip, span.clip.color);
            }
            const auto preparedIndex = uriClips.size() - 1;
            const auto prepared = pending_source_colors != nullptr &&
                    preparedIndex < pending_source_colors->size()
                ? (*pending_source_colors)[preparedIndex]
                : prepare_source_color(
                    span, colorPipeline, colorOutputSpace, legacySourceColor,
                    direct_d3d_compositor_enabled_, d3d11_color_lut_available_);
            if (prepared.has_value()) {
                if (pending_source_colors == nullptr) {
                    publish_prepared_source_color(*prepared);
                    if (!prepared->lut_id.empty()) {
                        registered_lut_ids_.push_back(prepared->lut_id);
                    }
                    if (!prepared->shader_id.empty()) {
                        registered_ocio_shader_ids_.push_back(prepared->shader_id);
                    }
                }
                if (prepared->shader != nullptr) {
                    add_ocio_shader_effect(
                        uri_clip, prepared->shader_id, direct_d3d_compositor_enabled_);
                    source_gpu_ocio_shader_bindings_.fetch_add(1);
                } else {
                    add_color_lut_effect(
                        uri_clip, prepared->lut_id, d3d11_color_lut_available_,
                        direct_d3d_compositor_enabled_);
                }
                source_color_lut_bindings_.fetch_add(1);
                if (d3d11_color_lut_available_) {
                    source_gpu_color_lut_bindings_.fetch_add(1);
                }
            }
        }

        // Drive the core URI source properties directly. This keeps transitions and audio
        // automation out of GES effect/transition objects, whose dynamic native children are
        // unstable during rapid timeline rebuilds on GStreamer 1.28.
        for (std::size_t index = 0; index < spans.size(); ++index) {
            const auto& span = spans[index];
            if (span.clip.transition_in > 0) {
                bind_linear_control(
                    find_core_track_element(GES_CLIP(uriClips[index]), GES_TRACK_TYPE_VIDEO),
                    "alpha",
                    {{source_control_time(span, 0), 0.0},
                     {source_control_time(span, span.clip.transition_in), 1.0},
                     {source_control_time(span, span.timeline_out - span.timeline_in), 1.0}});
                source_automation_bindings_.fetch_add(1);
            }
            const auto outgoingTransition = index + 1 < spans.size()
                ? spans[index + 1].clip.transition_in : 0;
            if (span.has_audio && (span.clip.audio != ClipAudio{} ||
                                  span.clip.transition_in > 0 || outgoingTransition > 0)) {
                bind_linear_control(
                    find_core_track_element(GES_CLIP(uriClips[index]), GES_TRACK_TYPE_AUDIO),
                    "volume", audio_envelope(span, outgoingTransition));
                source_automation_bindings_.fetch_add(1);
            }
        }

        for (const auto& caption : captions) {
            auto* overlay = ges_text_overlay_clip_new();
            if (overlay == nullptr) {
                throw std::runtime_error("failed to create GES caption overlay");
            }
            ges_text_overlay_clip_set_text(overlay, caption.text.c_str());
            ges_text_overlay_clip_set_font_desc(overlay, "Malgun Gothic Bold 30");
            ges_text_overlay_clip_set_halign(overlay, GES_TEXT_HALIGN_CENTER);
            ges_text_overlay_clip_set_valign(overlay, GES_TEXT_VALIGN_BOTTOM);
            ges_text_overlay_clip_set_color(overlay, 0xffffffffU);
            auto* element = GES_TIMELINE_ELEMENT(overlay);
            const bool configured =
                ges_timeline_element_set_start(element, caption.timeline_in) &&
                ges_timeline_element_set_duration(element, caption.duration);
            if (!configured || !ges_layer_add_clip(captionLayer, GES_CLIP(overlay))) {
                gst_object_unref(overlay);
                throw std::runtime_error("failed to configure GES caption overlay");
            }
        }

        auto* new_pipeline = ges_pipeline_new();
        if (new_pipeline == nullptr) {
            throw std::runtime_error("failed to create GES pipeline");
        }
        gst_object_ref_sink(new_pipeline);
        const auto d3d11DeviceHandle = d3d11_device_handle_.load(std::memory_order_acquire);
        auto* rawPreviewDevice = d3d11DeviceHandle != nullptr
            ? gst_d3d11_device_new_wrapped(static_cast<ID3D11Device*>(d3d11DeviceHandle))
            : (direct_d3d_compositor_enabled_ ? gst_d3d11_device_new(0, 0) : nullptr);
        auto previewDevice = std::shared_ptr<GstD3D11Device>(
            rawPreviewDevice, [](GstD3D11Device* value) {
                if (value != nullptr) gst_object_unref(value);
            });
        if (previewDevice != nullptr) {
            auto* context = gst_d3d11_context_new(previewDevice.get());
            gst_element_set_context(GST_ELEMENT(new_pipeline), context);
            gst_context_unref(context);
        }
        if (!ges_pipeline_set_timeline(new_pipeline, new_timeline) ||
            !ges_pipeline_set_mode(new_pipeline, GES_PIPELINE_MODE_PREVIEW)) {
            gst_object_unref(new_pipeline);
            throw std::runtime_error("failed to attach timeline to GES pipeline");
        }

        if (!video_sink_factory_.empty()) {
            GstElement* sink = nullptr;
            GstElement* appSink = nullptr;
            const bool cpuAppSink = video_sink_factory_ == "cpu-appsink";
            const bool floatAppSink = float_output_enabled_.load(std::memory_order_acquire);
            const bool d3d11AppSink = video_sink_factory_ == "d3d11-appsink" ||
                video_sink_factory_ == "appsink";
            if (floatAppSink) {
                GError* parseError = nullptr;
                sink = gst_parse_bin_from_description(
                    "videoconvert ! videoscale ! "
                    "video/x-raw,format=RGBA64_LE,width=640,height=360,pixel-aspect-ratio=1/1 ! "
                    "appsink name=qtappsink max-buffers=2 drop=true sync=true "
                    "enable-last-sample=false",
                    TRUE, &parseError);
                if (sink == nullptr) {
                    throw glib_error("failed to create float CPU appsink bin", parseError);
                }
                appSink = gst_bin_get_by_name(GST_BIN(sink), "qtappsink");
            } else if (cpuAppSink) {
                GError* parseError = nullptr;
                sink = gst_parse_bin_from_description(
                    "videoconvert ! videoscale add-borders=true ! "
                    "video/x-raw,format=BGRA,width=1280,height=720,pixel-aspect-ratio=1/1 ! "
                    "appsink name=qtappsink max-buffers=2 drop=true sync=true "
                    "enable-last-sample=false",
                    TRUE,
                    &parseError);
                if (sink == nullptr) {
                    throw glib_error("failed to create CPU appsink bin", parseError);
                }
                appSink = gst_bin_get_by_name(GST_BIN(sink), "qtappsink");
            } else if (d3d11AppSink) {
                GError* parseError = nullptr;
                sink = gst_parse_bin_from_description(
                    "d3d11upload ! d3d11convert ! "
                    "video/x-raw(memory:D3D11Memory),format=RGBA ! "
                    "appsink name=qtappsink max-buffers=2 drop=true sync=true "
                    "enable-last-sample=false",
                    TRUE,
                    &parseError);
                if (sink == nullptr) {
                    throw glib_error("failed to create D3D11 appsink bin", parseError);
                }
                appSink = gst_bin_get_by_name(GST_BIN(sink), "qtappsink");
            } else {
                sink = gst_element_factory_make(video_sink_factory_.c_str(), nullptr);
            }
            if (sink == nullptr) {
                gst_object_unref(new_pipeline);
                throw std::runtime_error("missing video sink: " + video_sink_factory_);
            }
            gst_object_ref_sink(sink);
            if (previewDevice != nullptr) {
                auto* context = gst_d3d11_context_new(previewDevice.get());
                gst_element_set_context(sink, context);
                gst_context_unref(context);
            }
            if (floatAppSink || cpuAppSink || d3d11AppSink) {
                if (appSink == nullptr) {
                    gst_object_unref(sink);
                    gst_object_unref(new_pipeline);
                    throw std::runtime_error("appsink bin has no qtappsink element");
                }
                GstAppSinkCallbacks callbacks{};
                callbacks.new_sample = GesSequencePlayer::new_video_sample;
                gst_app_sink_set_callbacks(GST_APP_SINK(appSink), &callbacks, this, nullptr);
                gst_object_unref(appSink);
            }
            if (video_sink_factory_ == "fakesink") {
                g_object_set(sink, "sync", TRUE, nullptr);
            }
            if (video_window_handle_ != 0 && GST_IS_VIDEO_OVERLAY(sink)) {
                gst_video_overlay_set_window_handle(
                    GST_VIDEO_OVERLAY(sink),
                    static_cast<guintptr>(video_window_handle_));
            }
            ges_pipeline_preview_set_video_sink(new_pipeline, sink);
            video_sink_ = GST_ELEMENT(gst_object_ref(sink));
            gst_object_unref(sink);
        }
        if (!audio_sink_factory_.empty()) {
            auto* sink = gst_element_factory_make(audio_sink_factory_.c_str(), nullptr);
            if (sink == nullptr) {
                gst_object_unref(new_pipeline);
                throw std::runtime_error("missing audio sink: " + audio_sink_factory_);
            }
            gst_object_ref_sink(sink);
            if (audio_sink_factory_ == "fakesink") {
                g_object_set(sink, "sync", TRUE, "signal-handoffs", TRUE, nullptr);
                g_signal_connect(sink, "handoff", G_CALLBACK(GesSequencePlayer::audio_handoff), this);
            }
            ges_pipeline_preview_set_audio_sink(new_pipeline, sink);
            gst_object_unref(sink);
        }

        timeline_ = new_timeline;
        pipeline_ = new_pipeline;
        duration_ns_.store(spans.back().timeline_out);
    } catch (...) {
        gst_object_unref(new_timeline);
        throw;
    }
}

void GesSequencePlayer::destroy_pipeline_locked() noexcept {
    if (pipeline_ != nullptr) {
        gst_element_set_state(GST_ELEMENT(pipeline_), GST_STATE_NULL);
        gst_object_unref(pipeline_);
        pipeline_ = nullptr;
    }
    if (timeline_ != nullptr) {
        gst_object_unref(timeline_);
        timeline_ = nullptr;
    }
    if (video_sink_ != nullptr) {
        gst_object_unref(video_sink_);
        video_sink_ = nullptr;
    }
    for (const auto& id : registered_lut_ids_) remove_gst_color_lut(id);
    registered_lut_ids_.clear();
    for (const auto& id : registered_ocio_shader_ids_) remove_gst_d3d11_ocio_shader(id);
    registered_ocio_shader_ids_.clear();
    preview_spans_.clear();
    duration_ns_.store(0);
    position_ns_.store(0);
}

void GesSequencePlayer::notify_state(PlaybackState state_value) {
    StateCallback callback;
    {
        std::scoped_lock lock(callback_mutex_);
        callback = state_callback_;
    }
    if (callback) {
        callback(state_value);
    }
}

void GesSequencePlayer::monitor(std::stop_token stop_token) {
    using namespace std::chrono_literals;
    while (!stop_token.stop_requested()) {
        PositionCallback callback;
        StateCallback state_callback;
        ErrorCallback error_callback;
        std::string error_message;
        bool state_changed = false;
        bool position_available = false;
        TimeNs current_position = position_ns_.load();
        {
            std::scoped_lock lock(mutex_);
            if (pipeline_ != nullptr) {
                auto* bus = gst_element_get_bus(GST_ELEMENT(pipeline_));
                while (auto* message = gst_bus_pop(bus)) {
                    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_EOS) {
                        current_position = duration_ns_.load();
                        position_ns_.store(current_position);
                        state_.store(PlaybackState::stopped);
                        position_available = true;
                        state_changed = true;
                    } else if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
                        GError* error = nullptr;
                        gchar* debug = nullptr;
                        gst_message_parse_error(message, &error, &debug);
                        error_message = error && error->message
                            ? error->message
                            : "GStreamer playback failed";
                        if (debug != nullptr && *debug != '\0') {
                            error_message += " | ";
                            error_message += debug;
                        }
                        if (error != nullptr) {
                            g_error_free(error);
                        }
                        g_free(debug);
                        state_.store(PlaybackState::stopped);
                        state_changed = true;
                    }
                    gst_message_unref(message);
                }
                gst_object_unref(bus);

                if (state_.load() == PlaybackState::playing) {
                    gint64 queried = 0;
                    if (gst_element_query_position(
                            GST_ELEMENT(pipeline_), GST_FORMAT_TIME, &queried)) {
                        current_position = queried;
                        position_ns_.store(current_position);
                    }
                    position_available = true;
                }
            }
        }
        {
            std::scoped_lock lock(callback_mutex_);
            if (position_available) callback = position_callback_;
            if (state_changed) state_callback = state_callback_;
            if (!error_message.empty()) error_callback = error_callback_;
        }
        if (callback) {
            callback(current_position);
        }
        if (state_callback) {
            state_callback(PlaybackState::stopped);
        }
        if (error_callback) {
            error_callback(std::move(error_message));
        }
        std::this_thread::sleep_for(15ms);
    }
}

}  // namespace ffgui
