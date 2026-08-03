#include "ffprobe_analyzer.hpp"

#include "core/ffprobe_parser.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QProcessEnvironment>
#include <QCryptographicHash>
#include <QStandardPaths>

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
    bool allow_failure = false) {
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
    if (!process.waitForFinished(600'000)) {
        process.kill();
        process.waitForFinished();
        throw std::runtime_error("media analysis timed out");
    }
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        if (allow_failure) {
            return {};
        }
        const auto message = QString::fromUtf8(process.readAllStandardError()).trimmed();
        throw std::runtime_error(
            message.isEmpty() ? "media analysis failed" : message.toStdString());
    }
    return process.readAllStandardOutput();
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
                          "-frames:v", "1", temporary});
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
    const auto durationOutput = run_tool(
        ffprobe_path,
        {"-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", absolutePath});
    auto duration = parse_ffprobe_seconds(to_utf8(QString::fromUtf8(durationOutput).trimmed()));

    const auto frameOutput = run_tool(
        ffprobe_path,
        {"-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=key_frame,best_effort_timestamp_time", "-of", "csv=p=0", absolutePath});
    auto frameTimeline = parse_ffprobe_frame_timeline(to_utf8(QString::fromUtf8(frameOutput)));
    const auto audioPcm = run_tool(
        ffmpeg_path,
        {"-v", "error", "-i", absolutePath, "-map", "0:a:0?", "-vn",
         "-ac", "1", "-ar", "200", "-f", "f32le", "pipe:1"},
        true);
    auto audioPeaks = build_peaks(audioPcm);
    duration = std::max(duration, estimated_media_end(frameTimeline.frame_pts));
    auto atlas = build_thumbnail_atlas(ffmpeg_path, absolutePath, duration);
    return AnalyzedMedia{
        MediaAsset{std::move(asset_id), std::filesystem::path(absolutePath.toStdWString()),
                   duration, std::move(frameTimeline.frame_pts), std::move(audioPeaks),
                   std::move(frameTimeline.keyframe_pts)},
        std::move(atlas)};
}

}  // namespace ffgui
