#include "ffprobe_analyzer.hpp"

#include "core/ffprobe_parser.hpp"
#include "media/oiio_frame_source.hpp"
#include "media/oiio_probe.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QProcessEnvironment>
#include <QCryptographicHash>
#include <QElapsedTimer>
#include <QDebug>
#include <QStandardPaths>
#include <QImage>
#include <QPainter>
#include <QSaveFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

#include <algorithm>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace ffgui {
namespace {

QByteArray run_tool(
    const QString& executable,
    const QStringList& arguments,
    const QString& stage,
    bool allow_failure = false,
    int timeout_ms = 180'000) {
    QElapsedTimer elapsed;
    elapsed.start();
    const auto inputIndex = arguments.indexOf("-i");
    const auto input = inputIndex >= 0 && inputIndex + 1 < arguments.size()
        ? arguments[inputIndex + 1]
        : arguments.value(arguments.size() - 1);
    qInfo().noquote() << "media analysis stage started"
                      << "stage=" << stage
                      << "input=" << input;
    QProcess process;
    process.setProgram(executable);
    process.setArguments(arguments);
    process.setProcessChannelMode(QProcess::SeparateChannels);
#ifdef Q_OS_WIN
    process.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments* arguments) {
        arguments->flags |= CREATE_NO_WINDOW;
    });
#endif
    process.start();
    if (!process.waitForStarted(10'000)) {
        throw std::runtime_error("media analysis tool could not be started");
    }
    if (!process.waitForFinished(timeout_ms)) {
        process.kill();
        process.waitForFinished();
        qWarning().noquote() << "media analysis stage timed out"
                             << "stage=" << stage
                             << "elapsed_ms=" << elapsed.elapsed();
        throw std::runtime_error((stage + " timed out").toStdString());
    }
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        if (allow_failure) {
            qWarning().noquote() << "optional media analysis stage failed"
                                 << "stage=" << stage
                                 << "elapsed_ms=" << elapsed.elapsed();
            return {};
        }
        const auto message = QString::fromUtf8(process.readAllStandardError()).trimmed();
        throw std::runtime_error(
            message.isEmpty() ? "media analysis failed" : message.toStdString());
    }
    auto output = process.readAllStandardOutput();
    qInfo().noquote() << "media analysis stage finished"
                      << "stage=" << stage
                      << "elapsed_ms=" << elapsed.elapsed()
                      << "output_bytes=" << output.size();
    return output;
}

QString locate_tool(const QString& name, const char* override_name) {
    const auto overridePath = qEnvironmentVariable(override_name);
    if (QFileInfo(overridePath).isFile()) {
        return QFileInfo(overridePath).absoluteFilePath();
    }
    const auto applicationDir = QCoreApplication::applicationDirPath();
    const QStringList candidates{
        QDir(applicationDir).filePath("tools/" + name + ".exe"),
        QDir(applicationDir).absoluteFilePath(
            "../../../../.tools/ffmpeg/bin/" + name + ".exe")};
    for (const auto& candidate : candidates) {
        if (QFileInfo(candidate).isFile()) {
            return QFileInfo(candidate).absoluteFilePath();
        }
    }
    throw std::runtime_error((name + " 8.1.2 executable was not found").toStdString());
}

std::vector<float> build_peaks(const QByteArray& pcm) {
    constexpr std::size_t targetCount = 2048;
    const auto sampleCount = static_cast<std::size_t>(pcm.size()) / sizeof(float);
    if (sampleCount == 0) {
        return {};
    }
    const auto peakCount = std::min(targetCount, sampleCount);
    std::vector<float> peaks(peakCount, 0.0F);
    for (std::size_t index = 0; index < sampleCount; ++index) {
        float sample = 0.0F;
        std::memcpy(&sample, pcm.constData() + index * sizeof(float), sizeof(float));
        if (!std::isfinite(sample)) {
            continue;
        }
        const auto bucket = std::min(peakCount - 1, index * peakCount / sampleCount);
        peaks[bucket] = std::max(peaks[bucket], std::min(1.0F, std::abs(sample)));
    }
    const auto maximum = *std::max_element(peaks.begin(), peaks.end());
    if (maximum > 0.0F) {
        for (auto& peak : peaks) {
            peak = std::sqrt(peak / maximum);
        }
    }
    return peaks;
}

QString build_thumbnail_atlas(const QString& ffmpeg, const QString& media, TimeNs duration) {
    const QFileInfo info(media);
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(info.canonicalFilePath().toUtf8());
    hash.addData(QByteArray::number(info.size()));
    hash.addData(QByteArray::number(info.lastModified().toMSecsSinceEpoch()));
    const auto cacheDir = QDir(QStandardPaths::writableLocation(QStandardPaths::CacheLocation))
        .filePath("thumbnails");
    QDir().mkpath(cacheDir);
    const auto target = QDir(cacheDir).filePath(QString::fromLatin1(hash.result().toHex()) + ".png");
    if (QFileInfo(target).isFile()) return target;
    const auto temporary = target + ".partial.png";
    const auto seconds = static_cast<double>(duration) / static_cast<double>(kNanosecondsPerSecond);
    const auto interval = std::max(0.04, seconds / 12.0);
    const auto filter = QString("fps=1/%1,scale=160:90:force_original_aspect_ratio=decrease,"
                                "pad=160:90:(ow-iw)/2:(oh-ih)/2,tile=12x1")
                            .arg(interval, 0, 'f', 6);
    try {
        run_tool(ffmpeg, {"-v", "error", "-y", "-i", media, "-vf", filter,
                          "-frames:v", "1", temporary}, "thumbnail", false, 120'000);
        QFile::remove(target);
        if (QFile::rename(temporary, target)) return target;
    } catch (...) {
    }
    QFile::remove(temporary);
    return {};
}

std::string to_utf8(const QString& value) {
    const auto bytes = value.toUtf8();
    return {bytes.constData(), static_cast<std::size_t>(bytes.size())};
}

QString escaped_concat_path(const std::filesystem::path& path) {
    auto value = QString::fromStdWString(std::filesystem::absolute(path).wstring());
    value.replace('\\', '/');
    value.replace(QLatin1Char('\''), QStringLiteral("'\\''"));
    return value;
}

QSize probe_dimensions(const QString& ffprobe, const QString& path) {
    const auto output = run_tool(
        ffprobe,
        {"-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", path},
        "image dimensions", true, 30'000);
    const auto parts = QString::fromUtf8(output).trimmed().split('x');
    if (parts.size() != 2) return {1280, 720};
    bool widthOk = false;
    bool heightOk = false;
    const auto width = parts[0].toInt(&widthOk);
    const auto height = parts[1].toInt(&heightOk);
    return widthOk && heightOk && width > 0 && height > 0 ? QSize(width, height) : QSize(1280, 720);
}

QSize proxy_dimensions(QSize source) {
    auto width = std::max(16, source.width() / 2);
    auto height = std::max(16, source.height() / 2);
    width -= width % 2;
    height -= height % 2;
    return {width, height};
}

SourceColorDescriptor probe_video_color(const QString& ffprobe, const QString& path) {
    SourceColorDescriptor result;
    const auto output = run_tool(
        ffprobe,
        {"-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_space,color_transfer,color_primaries,color_range", "-of", "json", path},
        "video color metadata", true, 30'000);
    const auto streams = QJsonDocument::fromJson(output).object().value("streams").toArray();
    if (!streams.isEmpty()) {
        const auto stream = streams.at(0).toObject();
        result.matrix = stream.value("color_space").toString().toStdString();
        result.transfer = stream.value("color_transfer").toString().toStdString();
        result.primaries = stream.value("color_primaries").toString().toStdString();
        result.range = stream.value("color_range").toString().toStdString();
    }
    result.unresolved = result.primaries.empty() || result.transfer.empty() || result.matrix.empty();
    if (!result.unresolved) {
        if (result.primaries == "bt709" && result.transfer == "bt709") {
            result.input_color_space = "Camera Rec.709";
        } else if (result.primaries == "bt2020" && result.transfer == "smpte2084") {
            result.input_color_space = "Rec.2100-PQ - Display";
        }
    }
    return result;
}

QString sequence_cache_key(const ImageSequenceDescriptor& sequence) {
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(QString::fromStdWString(sequence.directory.wstring()).toUtf8());
    hash.addData(QByteArray::fromStdString(sequence.prefix));
    hash.addData(QByteArray::fromStdString(sequence.suffix));
    hash.addData(QByteArray::number(sequence.first_frame));
    hash.addData(QByteArray::number(sequence.last_frame));
    hash.addData(QByteArray::number(sequence.frame_rate.numerator));
    hash.addData(QByteArray::number(sequence.frame_rate.denominator));
    hash.addData(QByteArray::fromStdString(sequence.exr_part));
    hash.addData(QByteArray::fromStdString(sequence.exr_view));
    hash.addData(QByteArray::fromStdString(sequence.exr_layer));
    for (const auto& channel : sequence.channel_mapping) {
        hash.addData(QByteArray::fromStdString(channel));
    }
    for (const auto frame : sequence.present_frames) {
        const QFileInfo info(QString::fromStdWString(sequence.frame_path(frame).wstring()));
        hash.addData(QByteArray::number(frame));
        hash.addData(QByteArray::number(info.size()));
        hash.addData(QByteArray::number(info.lastModified().toMSecsSinceEpoch()));
    }
    return QString::fromLatin1(hash.result().toHex());
}

QString prepare_selected_exr_frame(
    const ImageSequenceDescriptor& sequence,
    int frame_number) {
    const auto source = sequence.frame_path(frame_number);
    const QFileInfo sourceInfo(QString::fromStdWString(source.wstring()));
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(sourceInfo.absoluteFilePath().toUtf8());
    hash.addData(QByteArray::number(sourceInfo.size()));
    hash.addData(QByteArray::number(sourceInfo.lastModified().toMSecsSinceEpoch()));
    hash.addData(QByteArray::fromStdString(sequence.exr_part));
    hash.addData(QByteArray::fromStdString(sequence.exr_view));
    for (const auto& channel : sequence.channel_mapping) {
        hash.addData(QByteArray::fromStdString(channel));
    }
    const auto digest = QString::fromLatin1(hash.result().toHex());
    const auto directory = QDir(
        QStandardPaths::writableLocation(QStandardPaths::CacheLocation))
        .filePath(QStringLiteral("selected-exr-frames/%1").arg(digest.left(2)));
    QDir().mkpath(directory);
    const auto target = QDir(directory).filePath(digest + QStringLiteral(".exr"));
    if (QFileInfo(target).isFile()) return target;
    const auto partial = target + ".partial.exr";
    QFile::remove(partial);
    try {
        write_selected_exr_frame(
            {source, sequence.exr_part,
             sequence.channel_mapping, sequence.exr_view},
            std::filesystem::path(partial.toStdWString()));
    } catch (...) {
        QFile::remove(partial);
        throw;
    }
    if (!QFile::rename(partial, target)) {
        QFile::remove(partial);
        if (!QFileInfo(target).isFile()) {
            throw std::runtime_error("selected EXR AOV cache frame could not be committed");
        }
    }
    return target;
}

QString create_missing_frame(const QString& directory, int frame, QSize size) {
    const auto path = QDir(directory).filePath(QStringLiteral("missing-%1.png").arg(frame));
    if (QFileInfo(path).isFile()) return path;
    QImage image(size, QImage::Format_RGB32);
    constexpr int tile = 48;
    QPainter painter(&image);
    for (int y = 0; y < size.height(); y += tile) {
        for (int x = 0; x < size.width(); x += tile) {
            painter.fillRect(x, y, tile, tile,
                ((x / tile + y / tile) % 2) == 0 ? QColor("#c62f45") : QColor("#181b20"));
        }
    }
    painter.fillRect(QRect(0, size.height() / 2 - 62, size.width(), 124), QColor(0, 0, 0, 210));
    painter.setPen(Qt::white);
    QFont font = painter.font();
    font.setBold(true);
    font.setPixelSize(std::clamp(size.width() / 24, 24, 64));
    painter.setFont(font);
    painter.drawText(image.rect(), Qt::AlignCenter,
                     QStringLiteral("MISSING FRAME %1").arg(frame));
    painter.end();
    if (!image.save(path, "PNG")) throw std::runtime_error("missing-frame slate could not be written");
    return path;
}

std::vector<TimeNs> constant_frame_pts(std::size_t count, RationalFrameRate rate) {
    std::vector<TimeNs> result;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        result.push_back(static_cast<TimeNs>(std::llround(
            static_cast<long double>(index) * kNanosecondsPerSecond * rate.denominator /
            rate.numerator)));
    }
    return result;
}

AnalyzedMedia analyze_sequence(
    const QString& ffprobe,
    const QString& ffmpeg,
    const QString& representative,
    std::string assetId,
    ImageSequenceDescriptor sequence) {
    std::string detectedColorSpace;
    if (is_exr_extension(std::filesystem::path(representative.toStdWString()))) {
        const auto metadata = probe_image_metadata(std::filesystem::path(representative.toStdWString()));
        detectedColorSpace = metadata.color_space;
        const auto requestedPart = sequence.exr_part;
        const auto requestedView = sequence.exr_view;
        const auto requestedLayer = sequence.exr_layer;
        sequence.available_parts.clear();
        sequence.available_layers.clear();
        sequence.available_channels.clear();
        sequence.exr_parts.clear();
        sequence.deep = false;
        for (const auto& part : metadata.parts) {
            sequence.available_parts.push_back(part.name);
            sequence.deep = sequence.deep || part.deep;
            sequence.available_layers.insert(
                sequence.available_layers.end(), part.layers.begin(), part.layers.end());
            sequence.available_channels.insert(
                sequence.available_channels.end(), part.channels.begin(), part.channels.end());
            sequence.exr_parts.push_back(ExrPartDescriptor{
                part.name, part.view, part.layers, part.channels});
        }
        if (sequence.deep) throw std::runtime_error("deep EXR is not supported as timeline media");
        if (!metadata.parts.empty()) {
            auto selected = std::ranges::find_if(metadata.parts, [&](const auto& part) {
                return part.name == requestedPart &&
                    (requestedView.empty() || part.view == requestedView);
            });
            if (selected == metadata.parts.end() && !requestedPart.empty()) {
                selected = std::ranges::find(metadata.parts, requestedPart, &ImagePartMetadata::name);
            }
            if (selected == metadata.parts.end()) selected = metadata.parts.begin();
            sequence.exr_part = selected->name;
            sequence.exr_view = selected->view;
            const auto& layers = selected->layers;
            const auto beauty = std::ranges::find(layers, "beauty");
            const auto requested = std::ranges::find(layers, requestedLayer);
            if (requested != layers.end()) sequence.exr_layer = *requested;
            else if (beauty != layers.end()) sequence.exr_layer = *beauty;
            else if (!layers.empty()) sequence.exr_layer = layers.front();
            else sequence.exr_layer.clear();
            if (!sequence.exr_layer.empty()) {
                sequence.channel_mapping = {
                    sequence.exr_layer + ".R", sequence.exr_layer + ".G",
                    sequence.exr_layer + ".B", sequence.exr_layer + ".A"};
            } else {
                sequence.channel_mapping = {"R", "G", "B", "A"};
            }
        }
    }
    const auto key = sequence_cache_key(sequence);
    const auto cacheRoot = QDir(QStandardPaths::writableLocation(QStandardPaths::CacheLocation))
        .filePath("sequence-proxies/" + key);
    QDir().mkpath(cacheRoot);
    const auto proxy = QDir(cacheRoot).filePath("proxy-v4.mkv");
    const auto exportProxy = QDir(cacheRoot).filePath("export-nearest-v3.mov");
    auto sourceSize = probe_dimensions(ffprobe, representative);
    if (is_exr_extension(std::filesystem::path(representative.toStdWString()))) {
        const auto metadata = probe_image_metadata(
            std::filesystem::path(representative.toStdWString()));
        const auto selected = std::ranges::find_if(metadata.parts, [&](const auto& part) {
            return part.name == sequence.exr_part &&
                (sequence.exr_view.empty() || part.view == sequence.exr_view);
        });
        if (selected != metadata.parts.end()) {
            sourceSize = QSize(selected->width, selected->height);
        }
    }
    const auto targetSize = proxy_dimensions(sourceSize);
    const auto selectedPart = std::ranges::find_if(sequence.exr_parts, [&](const auto& part) {
        return part.name == sequence.exr_part &&
            (sequence.exr_view.empty() || part.view == sequence.exr_view);
    });
    const auto& alphaChannels = selectedPart == sequence.exr_parts.end()
        ? sequence.available_channels : selectedPart->channels;
    const auto hasAlpha = std::ranges::any_of(
        alphaChannels,
        [](const std::string& channel) { return channel == "A" || channel.ends_with(".A"); });
    const auto buildProxy = [&](const QString& target, const QString& manifestName, bool slateMissing) {
        if (QFileInfo(target).isFile()) return;
        const auto manifestPath = QDir(cacheRoot).filePath(manifestName);
        QSaveFile manifest(manifestPath);
        if (!manifest.open(QIODevice::WriteOnly | QIODevice::Text)) {
            throw std::runtime_error("image-sequence manifest could not be created");
        }
        QByteArray contents("ffconcat version 1.0\n");
        const auto seconds = static_cast<double>(sequence.frame_rate.denominator) /
            sequence.frame_rate.numerator;
        QString lastPath;
        for (int frame = sequence.first_frame; frame <= sequence.last_frame; ++frame) {
            const auto sourceFrame = sequence.has_frame(frame)
                ? frame : sequence.nearest_present_frame(frame);
            const auto selectedPath = is_exr_extension(sequence.frame_path(sourceFrame))
                ? prepare_selected_exr_frame(sequence, sourceFrame)
                : QString::fromStdWString(sequence.frame_path(sourceFrame).wstring());
            const auto framePath = sequence.has_frame(frame)
                ? selectedPath
                : slateMissing
                    ? create_missing_frame(cacheRoot, frame, targetSize)
                    : selectedPath;
            lastPath = framePath;
            contents += QStringLiteral("file '%1'\nduration %2\n")
                .arg(escaped_concat_path(std::filesystem::path(framePath.toStdWString())))
                .arg(seconds, 0, 'f', 12).toUtf8();
            if (frame == sequence.last_frame) break;
        }
        contents += QStringLiteral("file '%1'\n")
            .arg(escaped_concat_path(std::filesystem::path(lastPath.toStdWString()))).toUtf8();
        if (manifest.write(contents) != contents.size() || !manifest.commit()) {
            throw std::runtime_error("image-sequence manifest could not be committed");
        }
        const auto partial = target + (slateMissing ? ".partial.mkv" : ".partial.mov");
        QFile::remove(partial);
        const auto renderSize = slateMissing ? targetSize : sourceSize;
        const auto pixelFormat = slateMissing && !hasAlpha
            ? QStringLiteral("yuv420p")
            : hasAlpha ? QStringLiteral("yuva444p10le") : QStringLiteral("yuv444p10le");
        const auto profile = hasAlpha ? QStringLiteral("4") : QStringLiteral("3");
        QStringList arguments{
            "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", manifestPath,
            "-frames:v", QString::number(sequence.frame_count()),
            "-vf", QStringLiteral("scale=%1:%2:force_original_aspect_ratio=decrease:flags=lanczos,"
                                   "pad=%1:%2:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=%3")
                       .arg(renderSize.width()).arg(renderSize.height()).arg(pixelFormat),
            "-r", QString::number(sequence.frame_rate.value(), 'f', 8), "-an"};
        if (slateMissing && !hasAlpha) {
            arguments << "-c:v" << "libx264" << "-preset" << "veryfast"
                      << "-crf" << "18" << "-g" << "1";
        } else {
            arguments << "-c:v" << "prores_ks" << "-profile:v" << profile
                      << "-pix_fmt" << pixelFormat;
        }
        arguments << partial;
        run_tool(ffmpeg, arguments,
             slateMissing ? "image sequence preview proxy" : "image sequence export proxy",
             false, 900'000);
        QFile::remove(target);
        if (!QFile::rename(partial, target)) {
            throw std::runtime_error("image-sequence proxy could not be committed");
        }
    };
    buildProxy(proxy, QStringLiteral("sequence-preview.ffconcat"), true);
    buildProxy(exportProxy, QStringLiteral("sequence-export.ffconcat"), false);
    auto framePts = constant_frame_pts(sequence.frame_count(), sequence.frame_rate);
    const auto duration = static_cast<TimeNs>(std::llround(
        static_cast<long double>(sequence.frame_count()) * kNanosecondsPerSecond *
        sequence.frame_rate.denominator / sequence.frame_rate.numerator));
    SourceColorDescriptor color;
    color.input_color_space = !detectedColorSpace.empty() ? detectedColorSpace
        : is_exr_extension(std::filesystem::path(representative.toStdWString()))
            ? "ACEScg" : "sRGB - Texture";
    return AnalyzedMedia{
        MediaAsset{std::move(assetId), std::filesystem::path(representative.toStdWString()),
                   duration, std::move(framePts), {}, {}, MediaKind::image_sequence,
                   sequence, std::move(color), std::filesystem::path(proxy.toStdWString()),
                   std::filesystem::path(exportProxy.toStdWString())},
        build_thumbnail_atlas(ffmpeg, proxy, duration)};
}

AnalyzedMedia analyze_still(
    const QString& ffprobe,
    const QString& ffmpeg,
    const QString& path,
    std::string assetId) {
    constexpr auto duration = 5 * kNanosecondsPerSecond;
    const auto info = QFileInfo(path);
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(info.absoluteFilePath().toUtf8());
    hash.addData(QByteArray::number(info.size()));
    hash.addData(QByteArray::number(info.lastModified().toMSecsSinceEpoch()));
    const auto cacheRoot = QDir(QStandardPaths::writableLocation(QStandardPaths::CacheLocation))
        .filePath("still-proxies");
    QDir().mkpath(cacheRoot);
    const auto proxy = QDir(cacheRoot).filePath(QString::fromLatin1(hash.result().toHex()) + "-v2.mov");
    const auto target = proxy_dimensions(probe_dimensions(ffprobe, path));
    if (!QFileInfo(proxy).isFile()) {
        const auto partial = proxy + ".partial.mov";
        QFile::remove(partial);
        run_tool(ffmpeg,
            {"-v", "error", "-y", "-loop", "1", "-framerate", "24", "-i", path,
             "-t", "5", "-vf",
             QStringLiteral("scale=%1:%2:force_original_aspect_ratio=decrease:flags=lanczos,"
                            "pad=%1:%2:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv444p10le")
                .arg(target.width()).arg(target.height()),
             "-an", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv444p10le",
             partial}, "still image proxy", false, 180'000);
        QFile::remove(proxy);
        if (!QFile::rename(partial, proxy)) throw std::runtime_error("still proxy could not be committed");
    }
    auto framePts = constant_frame_pts(120, {24, 1});
    SourceColorDescriptor color;
    if (is_exr_extension(std::filesystem::path(path.toStdWString()))) {
        const auto metadata = probe_image_metadata(std::filesystem::path(path.toStdWString()));
        if (std::ranges::any_of(metadata.parts, &ImagePartMetadata::deep)) {
            throw std::runtime_error("deep EXR is not supported as timeline media");
        }
        color.input_color_space = metadata.color_space.empty() ? "ACEScg" : metadata.color_space;
    } else {
        color.input_color_space = "sRGB - Texture";
    }
    return AnalyzedMedia{
        MediaAsset{std::move(assetId), std::filesystem::path(path.toStdWString()), duration,
                   std::move(framePts), {}, {}, MediaKind::still_image, std::nullopt,
                   std::move(color), std::filesystem::path(proxy.toStdWString()),
                   std::filesystem::path(proxy.toStdWString())},
        build_thumbnail_atlas(ffmpeg, proxy, duration)};
}

}  // namespace

QString locate_ffprobe() {
    return locate_tool("ffprobe", "FFGUI_FFPROBE");
}

QString locate_ffmpeg() {
    return locate_tool("ffmpeg", "FFGUI_FFMPEG");
}

AnalyzedMedia analyze_media(
    const QString& ffprobe_path,
    const QString& ffmpeg_path,
    const QString& media_path,
    std::string asset_id) {
    const auto absolutePath = QFileInfo(media_path).absoluteFilePath();
    qInfo().noquote() << "media import started" << "path=" << absolutePath;
    const auto durationOutput = run_tool(
        ffprobe_path,
        {"-v", "error", "-show_entries", "format=duration:stream=duration",
         "-of", "default=nw=1:nk=1", absolutePath},
        "duration probe");
    TimeNs duration = 0;
    for (const auto& line : QString::fromUtf8(durationOutput).split('\n')) {
        const auto candidate = line.trimmed();
        if (candidate.isEmpty() || candidate.compare("N/A", Qt::CaseInsensitive) == 0) continue;
        try {
            duration = std::max(duration, parse_ffprobe_seconds(to_utf8(candidate)));
        } catch (const std::exception&) {
        }
    }

    const auto frameOutput = run_tool(
        ffprobe_path,
        {"-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=key_frame,best_effort_timestamp_time", "-of", "csv=p=0", absolutePath},
        "frame timeline", false, 300'000);
    auto frameTimeline = parse_ffprobe_frame_timeline(to_utf8(QString::fromUtf8(frameOutput)));
    const auto audioPcm = run_tool(
        ffmpeg_path,
        {"-v", "error", "-i", absolutePath, "-map", "0:a:0?", "-vn",
         "-ac", "1", "-ar", "200", "-f", "f32le", "pipe:1"},
        "audio waveform", true, 300'000);
    auto audioPeaks = build_peaks(audioPcm);
    duration = std::max(duration, estimated_media_end(frameTimeline.frame_pts));
    if (duration <= 0 || frameTimeline.frame_pts.empty()) {
        throw std::runtime_error("video duration or frame timeline could not be read");
    }
    auto atlas = build_thumbnail_atlas(ffmpeg_path, absolutePath, duration);
    qInfo().noquote() << "media import finished"
                      << "path=" << absolutePath
                      << "duration_ns=" << duration
                      << "frames=" << frameTimeline.frame_pts.size()
                      << "keyframes=" << frameTimeline.keyframe_pts.size()
                      << "waveform_samples=" << audioPeaks.size()
                      << "thumbnail=" << atlas;
    const auto animated = QFileInfo(absolutePath).suffix().compare("gif", Qt::CaseInsensitive) == 0;
    SourceColorDescriptor color;
    if (animated) color.input_color_space = "sRGB - Texture";
    else color = probe_video_color(ffprobe_path, absolutePath);
    return AnalyzedMedia{
        MediaAsset{std::move(asset_id), std::filesystem::path(absolutePath.toStdWString()),
                   duration, std::move(frameTimeline.frame_pts), std::move(audioPeaks),
                   std::move(frameTimeline.keyframe_pts),
                   animated ? MediaKind::animated_image : MediaKind::video,
                   std::nullopt, std::move(color)},
        std::move(atlas)};
}

AnalyzedMedia analyze_media_source(
    const QString& ffprobe_path,
    const QString& ffmpeg_path,
    const QString& media_path,
    std::string asset_id,
    std::optional<ImageSequenceDescriptor> sequence) {
    if (sequence.has_value()) {
        return analyze_sequence(ffprobe_path, ffmpeg_path, media_path,
                                std::move(asset_id), std::move(sequence.value()));
    }
    if (is_supported_still_extension(std::filesystem::path(media_path.toStdWString()))) {
        return analyze_still(ffprobe_path, ffmpeg_path, media_path, std::move(asset_id));
    }
    return analyze_media(ffprobe_path, ffmpeg_path, media_path, std::move(asset_id));
}

}  // namespace ffgui
