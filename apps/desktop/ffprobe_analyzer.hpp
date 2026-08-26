#pragma once

#include "core/media_asset.hpp"

#include <QString>
#include <QSize>

namespace ffgui {

struct AnalyzedMedia final {
    MediaAsset asset;
    QString thumbnail_atlas;
    QSize source_size;
};

[[nodiscard]] QString locate_ffprobe();
[[nodiscard]] QString locate_ffmpeg();
[[nodiscard]] QSize probe_media_dimensions(const QString& ffprobe_path, const QString& media_path);
[[nodiscard]] AnalyzedMedia analyze_media(
    const QString& ffprobe_path,
    const QString& ffmpeg_path,
    const QString& media_path,
    std::string asset_id);
[[nodiscard]] AnalyzedMedia analyze_media_source(
    const QString& ffprobe_path,
    const QString& ffmpeg_path,
    const QString& media_path,
    std::string asset_id,
    std::optional<ImageSequenceDescriptor> sequence = std::nullopt);

}  // namespace ffgui
