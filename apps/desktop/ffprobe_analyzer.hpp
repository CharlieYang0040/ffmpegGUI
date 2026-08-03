#pragma once

#include "core/media_asset.hpp"

#include <QString>

namespace ffgui {

[[nodiscard]] QString locate_ffprobe();
[[nodiscard]] QString locate_ffmpeg();
[[nodiscard]] MediaAsset analyze_media(
    const QString& ffprobe_path,
    const QString& ffmpeg_path,
    const QString& media_path,
    std::string asset_id);

}  // namespace ffgui
