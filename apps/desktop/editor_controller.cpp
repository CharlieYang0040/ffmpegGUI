#include "editor_controller.hpp"
#include "ffprobe_analyzer.hpp"
#include "d3d11_video_item.hpp"
#include "core/subtitle_srt.hpp"

#include <QFile>
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaObject>
#include <QJSEngine>
#include <QSaveFile>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QDateTime>
#include <QDebug>
#include <QDesktopServices>
#include <QQuickWindow>
#include <QtConcurrentRun>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace {

QString timeString(ffgui::TimeNs value) {
    return QString::number(static_cast<qint64>(value));
}

ffgui::TimeNs parseTime(const QJsonValue& value, const char* field) {
    bool valid = false;
    const auto parsed = value.toString().toLongLong(&valid);
    if (!valid) {
        throw std::runtime_error(std::string("invalid project time field: ") + field);
    }
    return static_cast<ffgui::TimeNs>(parsed);
}

}  // namespace

EditorController* EditorController::singleton_instance_ = nullptr;

EditorController* EditorController::create(QQmlEngine*, QJSEngine*) {
    if (singleton_instance_ == nullptr) {
        throw std::logic_error("EditorController singleton was not initialized");
    }
    QJSEngine::setObjectOwnership(singleton_instance_, QJSEngine::CppOwnership);
    return singleton_instance_;
}

void EditorController::setSingletonInstance(EditorController* instance) {
    singleton_instance_ = instance;
}

EditorController::EditorController(QObject* parent) : QObject(parent) {
    connect(
        &import_watcher_,
        &QFutureWatcher<std::vector<PendingImport>>::finished,
        this,
        [this] {
            bool success = false;
            try {
                auto imported = import_watcher_.result();
                for (auto& item : imported) {
                    const auto assetId = item.asset.id();
                    const auto assetKey = QString::fromStdString(assetId);
                    waveform_cache_.remove(assetKey);
                    thumbnail_images_.remove(assetKey);
                    const auto duration = item.asset.duration();
                    if (!item.thumbnail_atlas.isEmpty()) {
                        thumbnail_atlases_.insert(assetKey, std::move(item.thumbnail_atlas));
                    }
                    timeline_.add_asset(std::move(item.asset));
                    timeline_.append_clip(ffgui::Clip{
                        std::move(item.clip_id), assetId, 0, duration});
                    if (selected_clip_id_.isEmpty()) {
                        setSingleSelection(
                            QString::fromStdString(timeline_.clips().back().id));
                    }
                }
                timeline_.clear_history();
                publishTimeline(true);
                success = true;
            } catch (const std::exception& error) {
                qWarning().noquote() << "media import failed" << error.what();
                setStatus(QString::fromUtf8(error.what()));
            }
            importing_ = false;
            emit importingChanged();
            emit mediaImportFinished(success);
        });
    export_process_.setProcessChannelMode(QProcess::SeparateChannels);
    export_validation_process_.setProcessChannelMode(QProcess::SeparateChannels);
#ifdef Q_OS_WIN
    export_process_.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments* args) {
        args->flags |= CREATE_NO_WINDOW;
    });
    export_validation_process_.setCreateProcessArgumentsModifier(
        [](QProcess::CreateProcessArguments* args) { args->flags |= CREATE_NO_WINDOW; });
#endif
    connect(&export_process_, &QProcess::readyReadStandardError, this, [this] {
        const auto chunk = export_process_.readAllStandardError();
        if (export_log_file_ && export_log_file_->isOpen()) {
            export_log_file_->write(chunk);
            export_log_file_->flush();
        }
        export_stderr_.append(chunk);
        if (export_stderr_.size() > 65'536) {
            export_stderr_ = export_stderr_.right(65'536);
        }
        static const QRegularExpression progressExpression(
            QStringLiteral("(?:^|\\n)out_time_us=(\\d+)"));
        auto matches = progressExpression.globalMatch(QString::fromUtf8(export_stderr_));
        qint64 latestMicroseconds = -1;
        while (matches.hasNext()) {
            latestMicroseconds = matches.next().captured(1).toLongLong();
        }
        if (latestMicroseconds >= 0 && export_request_.has_value()) {
            const auto duration = std::max<ffgui::TimeNs>(1, export_duration_ns_);
            const auto next = std::clamp(
                static_cast<qreal>(latestMicroseconds * 1'000.0 / duration), 0.0, 0.99);
            if (!qFuzzyCompare(export_progress_, next)) {
                export_progress_ = next;
                emit exportProgressChanged();
            }
        }
    });
    connect(
        &export_process_,
        qOverload<int, QProcess::ExitStatus>(&QProcess::finished),
        this,
        [this](int exitCode, QProcess::ExitStatus status) {
            if (!exporting_) return;
            if (!export_cancelled_ && status == QProcess::NormalExit && exitCode == 0) {
                startExportValidation();
                return;
            }
            if (!export_cancelled_ && export_stream_copy_active_) {
                export_request_->prefer_stream_copy = false;
                QFile::remove(QString::fromStdWString(export_request_->output_path.wstring()));
                QFile::remove(export_concat_path_);
                setStatus("무손실 복사를 적용할 수 없어 NVENC로 다시 시도합니다");
                startExportProcess(export_codec_ == 1
                    ? ffgui::ExportVideoEncoder::hevc_nvenc
                    : ffgui::ExportVideoEncoder::h264_nvenc);
                return;
            }
            if (!export_cancelled_ && !export_cpu_fallback_) {
                export_cpu_fallback_ = true;
                QFile::remove(QString::fromStdWString(export_request_->output_path.wstring()));
                setStatus("NVENC를 사용할 수 없어 CPU 인코딩으로 다시 시도합니다");
                startExportProcess(export_codec_ == 1
                    ? ffgui::ExportVideoEncoder::libx265
                    : ffgui::ExportVideoEncoder::libx264);
                return;
            }
            finishExport(false);
        });
    connect(&export_process_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (exporting_ && error == QProcess::FailedToStart) {
            finishExport(false);
        }
    });
    connect(
        &export_validation_process_,
        qOverload<int, QProcess::ExitStatus>(&QProcess::finished),
        this,
        [this](int exitCode, QProcess::ExitStatus status) {
            const auto output = export_validation_process_.readAllStandardOutput();
            const auto error = export_validation_process_.readAllStandardError();
            if (export_log_file_ && export_log_file_->isOpen()) {
                export_log_file_->write("\n--- ffprobe validation ---\n");
                export_log_file_->write(output);
                export_log_file_->write(error);
                export_log_file_->flush();
            }
            bool valid = status == QProcess::NormalExit && exitCode == 0;
            const auto document = QJsonDocument::fromJson(output);
            const auto streams = document.object().value("streams").toArray();
            bool hasVideo = false;
            for (const auto& stream : streams) {
                if (stream.toObject().value("codec_type").toString() == "video") {
                    hasVideo = true;
                    break;
                }
            }
            const auto durationSeconds = document.object().value("format").toObject()
                .value("duration").toString().toDouble();
            const auto actualDuration = static_cast<ffgui::TimeNs>(
                std::llround(durationSeconds * ffgui::kNanosecondsPerSecond));
            const auto tolerance = std::max<ffgui::TimeNs>(
                500'000'000, export_duration_ns_ / 50);
            valid = valid && hasVideo && actualDuration > 0 &&
                std::abs(actualDuration - export_duration_ns_) <= tolerance;
            qInfo().noquote() << "export validation finished"
                              << "valid=" << valid
                              << "expected_ns=" << export_duration_ns_
                              << "actual_ns=" << actualDuration
                              << "video=" << hasVideo
                              << "log=" << export_log_path_;
            if (!valid && !error.trimmed().isEmpty()) export_stderr_.append(error);
            finishExport(valid);
        });
    connect(
        &export_validation_process_,
        &QProcess::errorOccurred,
        this,
        [this](QProcess::ProcessError error) {
            if (exporting_ && error == QProcess::FailedToStart) {
                export_stderr_.append("ffprobe validation process could not be started");
                finishExport(false);
            }
        });
#ifdef FFGUI_HAS_GES
    use_d3d_scene_graph_ = qEnvironmentVariableIntValue("FFGUI_FORCE_CPU_PREVIEW") != 1;
    in_process_preview_ = true;
    player_ = std::make_unique<ffgui::GesSequencePlayer>(
        use_d3d_scene_graph_ ? "d3d11-appsink" : "cpu-appsink",
        "wasapi2sink");
    player_->set_video_frame_callback([this](ffgui::PreviewVideoFrame frame) {
        bool scheduleDelivery = false;
        {
            std::scoped_lock lock(pending_video_frame_mutex_);
            pending_video_frame_ = std::move(frame);
            if (!video_frame_delivery_queued_) {
                video_frame_delivery_queued_ = true;
                scheduleDelivery = true;
            }
        }
        if (!scheduleDelivery) return;
        QMetaObject::invokeMethod(this, [this] {
            std::optional<ffgui::PreviewVideoFrame> frame;
            {
                std::scoped_lock lock(pending_video_frame_mutex_);
                frame = std::move(pending_video_frame_);
                pending_video_frame_.reset();
                video_frame_delivery_queued_ = false;
            }
            if (!frame.has_value()) return;
            if (auto* item = qobject_cast<VideoPreviewItem*>(video_item_)) {
                ++video_frames_delivered_;
                if (video_frames_delivered_ == 1) {
                    qInfo().noquote() << "first preview frame delivered to Qt item"
                                      << "cpu=" << (frame->cpu_pixels != nullptr)
                                      << "size=" << frame->width << "x" << frame->height;
                }
                item->submitFrame(std::move(frame.value()));
            }
        }, Qt::QueuedConnection);
    });
    player_->set_position_callback([this](ffgui::TimeNs position) {
        QMetaObject::invokeMethod(
            this,
            [this, position] {
                if (playhead_ns_ != position) {
                    playhead_ns_ = position;
                    emit playheadChanged();
                }
            },
            Qt::QueuedConnection);
    });
    player_->set_state_callback([this](ffgui::PlaybackState state) {
        QMetaObject::invokeMethod(
            this,
            [this, state] {
                const bool nowPlaying = state == ffgui::PlaybackState::playing;
                if (playing_ != nowPlaying) {
                    playing_ = nowPlaying;
                    emit playingChanged();
                }
            },
            Qt::QueuedConnection);
    });
    player_->set_error_callback([this](std::string message) {
        QMetaObject::invokeMethod(
            this,
            [this, message = std::move(message)] {
                qWarning().noquote() << "GStreamer playback error:"
                                     << QString::fromUtf8(message);
                setStatus(QString::fromUtf8(message));
            },
            Qt::QueuedConnection);
    });
#endif
    preview_update_timer_.setSingleShot(true);
    preview_update_timer_.setInterval(50);
    connect(&preview_update_timer_, &QTimer::timeout, this, [this] {
        queuePreviewOperation(true);
    });
#ifdef FFGUI_HAS_GES
    connect(
        &preview_watcher_,
        &QFutureWatcher<PreviewOperationResult>::finished,
        this,
        [this] {
            const auto result = preview_watcher_.result();
            if (result.success) {
                if (preview_failed_) {
                    preview_failed_ = false;
                    emit previewFailedChanged();
                }
                if (result.rebuilt) {
                    preview_applied_generation_ = result.generation;
                    ++preview_rebuild_count_;
                }
            } else {
                preview_should_play_ = false;
                qWarning().noquote() << "preview operation failed:" << result.error;
                if (!preview_failed_) {
                    preview_failed_ = true;
                    emit previewFailedChanged();
                }
                setStatus(result.error.isEmpty()
                    ? QStringLiteral("미리보기를 준비하지 못했습니다")
                    : result.error);
            }

            const bool generationAdvanced = result.generation != preview_generation_;
            if (preview_operation_pending_ || generationAdvanced) {
                startPreviewOperation();
                return;
            }
            if (preview_busy_) {
                preview_busy_ = false;
                emit previewBusyChanged();
            }
            if (result.success) {
                setStatus(timeline_.clips().empty()
                    ? QStringLiteral("미디어를 추가하세요")
                    : (preview_should_play_
                        ? QStringLiteral("재생 중")
                        : QStringLiteral("미리보기 준비 완료")));
            }
        });
#endif
}

void EditorController::setVideoWindow(QWindow* window) {
    video_window_ = window;
}

void EditorController::refreshVideoWindowHandle() {
    if (video_window_ == nullptr || in_process_preview_) return;
    video_window_->create();
#ifdef FFGUI_HAS_GES
    const auto handle = static_cast<std::uintptr_t>(video_window_->winId());
    player_->set_video_window_handle(handle);
    qInfo().noquote() << "native preview window attached handle=" << handle;
#endif
}

void EditorController::openLogFolder() {
    const auto directory = QDir(
        QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation))
        .filePath("logs");
    QDir().mkpath(directory);
    QDesktopServices::openUrl(QUrl::fromLocalFile(directory));
}

EditorController::~EditorController() {
#ifdef FFGUI_HAS_GES
    if (preview_watcher_.isRunning()) preview_watcher_.waitForFinished();
#endif
    if (export_process_.state() != QProcess::NotRunning) {
        export_process_.kill();
        export_process_.waitForFinished(3'000);
    }
    if (export_validation_process_.state() != QProcess::NotRunning) {
        export_validation_process_.kill();
        export_validation_process_.waitForFinished(3'000);
    }
    if (!export_concat_path_.isEmpty()) QFile::remove(export_concat_path_);
    if (!export_subtitle_path_.isEmpty()) QFile::remove(export_subtitle_path_);
}

std::uint64_t EditorController::videoFramesReceived() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->video_frames_received() : 0;
#else
    return 0;
#endif
}

bool EditorController::videoSurfaceExposed() const noexcept {
    const auto* item = qobject_cast<const VideoPreviewItem*>(video_item_);
    return item != nullptr && item->window() != nullptr && item->window()->isExposed();
}

QVariantList EditorController::clips() const {
    if (clips_cache_.has_value()) return clips_cache_.value();
    QElapsedTimer elapsed;
    elapsed.start();
    QVariantList result;
    const auto spans = timeline_.snapshot();
    for (std::size_t index = 0; index < spans.size(); ++index) {
        const auto& span = spans[index];
        QVariantMap value;
        value.insert("id", QString::fromStdString(span.clip.id));
        value.insert("name", QString::fromStdWString(span.source_path.stem().wstring()));
        value.insert("timelineInNs", static_cast<qint64>(span.timeline_in));
        value.insert("sourceInNs", static_cast<qint64>(span.clip.source_in));
        value.insert("durationNs", static_cast<qint64>(span.timeline_out - span.timeline_in));
        value.insert("sourceDurationNs", static_cast<qint64>(span.clip.duration));
        value.insert("playbackRate", span.clip.playback_rate);
        value.insert("audioGain", span.clip.audio.gain);
        value.insert("audioMuted", span.clip.audio.muted);
        value.insert("audioFadeInNs", static_cast<qint64>(span.clip.audio.fade_in));
        value.insert("audioFadeOutNs", static_cast<qint64>(span.clip.audio.fade_out));
        value.insert("brightness", span.clip.color.brightness);
        value.insert("contrast", span.clip.color.contrast);
        value.insert("saturation", span.clip.color.saturation);
        value.insert("transitionInNs", static_cast<qint64>(span.clip.transition_in));
        const auto* asset = timeline_.asset(span.clip.asset_id);
        value.insert("assetDurationNs", static_cast<qint64>(asset ? asset->duration() : 0));
        value.insert(
            "thumbnailAtlas",
            thumbnail_atlases_.value(QString::fromStdString(span.clip.asset_id)));
        QVariantList waveform;
        if (asset != nullptr) {
            const auto assetKey = QString::fromStdString(asset->id());
            const auto cached = waveform_cache_.constFind(assetKey);
            if (cached != waveform_cache_.cend()) {
                waveform = cached.value();
            } else {
                waveform.reserve(static_cast<qsizetype>(asset->audio_peaks().size()));
                for (const auto peak : asset->audio_peaks()) waveform.push_back(peak);
                waveform_cache_.insert(assetKey, waveform);
            }
        }
        value.insert("waveform", waveform);
        result.push_back(value);
    }
    clips_cache_ = std::move(result);
    if (elapsed.elapsed() >= 50) {
        qWarning().noquote() << "clip view-model rebuild was slow"
                             << "elapsed_ms=" << elapsed.elapsed()
                             << "clips=" << clips_cache_->size();
    }
    return clips_cache_.value();
}

QVariantList EditorController::mediaAssets() const {
    if (media_assets_cache_.has_value()) return media_assets_cache_.value();
    QElapsedTimer elapsed;
    elapsed.start();
    std::vector<const ffgui::MediaAsset*> assets;
    assets.reserve(timeline_.assets().size());
    for (const auto& [id, asset] : timeline_.assets()) {
        static_cast<void>(id);
        assets.push_back(&asset);
    }
    std::sort(assets.begin(), assets.end(), [](const auto* left, const auto* right) {
        return left->path().wstring() < right->path().wstring();
    });

    QVariantList result;
    result.reserve(static_cast<qsizetype>(assets.size()));
    for (const auto* asset : assets) {
        const auto id = QString::fromStdString(asset->id());
        const QFileInfo file(QString::fromStdWString(asset->path().wstring()));
        int useCount = 0;
        for (const auto& clip : timeline_.clips()) {
            if (clip.asset_id == asset->id()) ++useCount;
        }
        result.push_back(QVariantMap{
            {"id", id},
            {"name", file.completeBaseName()},
            {"path", file.absoluteFilePath()},
            {"durationNs", static_cast<qint64>(asset->duration())},
            {"thumbnailAtlas", thumbnail_atlases_.value(id)},
            {"useCount", useCount}});
    }
    media_assets_cache_ = std::move(result);
    if (elapsed.elapsed() >= 50) {
        qWarning().noquote() << "media view-model rebuild was slow"
                             << "elapsed_ms=" << elapsed.elapsed()
                             << "assets=" << media_assets_cache_->size();
    }
    return media_assets_cache_.value();
}

QVariantList EditorController::captions() const {
    if (captions_cache_.has_value()) return captions_cache_.value();
    QVariantList result;
    result.reserve(static_cast<qsizetype>(timeline_.captions().size()));
    for (const auto& caption : timeline_.captions()) {
        result.push_back(QVariantMap{
            {"id", QString::fromStdString(caption.id)},
            {"text", QString::fromUtf8(caption.text)},
            {"timelineInNs", static_cast<qint64>(caption.timeline_in)},
            {"durationNs", static_cast<qint64>(caption.duration)},
            {"positionX", caption.position_x},
            {"positionY", caption.position_y},
            {"fontSize", caption.font_size},
            {"backgroundOpacity", caption.background_opacity}});
    }
    captions_cache_ = std::move(result);
    return captions_cache_.value();
}

qint64 EditorController::durationNs() const noexcept {
    return static_cast<qint64>(timeline_.duration());
}

int EditorController::selectedClipVolumePercent() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(std::lround(clip.audio.gain * 100.0));
        }
    }
    return 100;
}

bool EditorController::selectedClipMuted() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) return clip.audio.muted;
    }
    return false;
}

int EditorController::selectedClipFadeInMs() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(clip.audio.fade_in / 1'000'000);
        }
    }
    return 0;
}

int EditorController::selectedClipFadeOutMs() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(clip.audio.fade_out / 1'000'000);
        }
    }
    return 0;
}

int EditorController::selectedClipSpeedPercent() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(std::lround(clip.playback_rate * 100.0));
        }
    }
    return 100;
}

int EditorController::selectedClipBrightness() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(std::lround(clip.color.brightness * 100.0));
        }
    }
    return 0;
}

int EditorController::selectedClipContrast() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(std::lround(clip.color.contrast * 100.0));
        }
    }
    return 100;
}

int EditorController::selectedClipSaturation() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(std::lround(clip.color.saturation * 100.0));
        }
    }
    return 100;
}

int EditorController::selectedClipDissolveMs() const noexcept {
    for (const auto& clip : timeline_.clips()) {
        if (clip.id == selected_clip_id_.toStdString()) {
            return static_cast<int>(clip.transition_in / 1'000'000);
        }
    }
    return 0;
}

QString EditorController::selectedCaptionText() const {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    return found == timeline_.captions().end() ? QString{} : QString::fromUtf8(found->text);
}

int EditorController::selectedCaptionDurationMs() const noexcept {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    return found == timeline_.captions().end()
        ? 0
        : static_cast<int>(found->duration / 1'000'000);
}

int EditorController::selectedCaptionFontSize() const noexcept {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    return found == timeline_.captions().end() ? 44 : found->font_size;
}

int EditorController::selectedCaptionBackgroundOpacity() const noexcept {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    return found == timeline_.captions().end() ? 0 : found->background_opacity;
}

void EditorController::attachVideoItem(QObject* item) {
    auto* videoItem = qobject_cast<VideoPreviewItem*>(item);
    if (videoItem == nullptr) {
        setStatus("인프로세스 미리보기 화면을 연결할 수 없습니다");
        return;
    }
    video_item_ = videoItem;
    connect(videoItem, &VideoPreviewItem::framePresented, this, [this](quint64) {
        ++video_frames_presented_;
    });
#ifdef FFGUI_HAS_GES
    if (use_d3d_scene_graph_) {
        connect(videoItem, &VideoPreviewItem::d3d11DeviceReady, this, [this](quintptr device) {
            player_->set_d3d11_device(reinterpret_cast<void*>(device));
            preview_applied_generation_.reset();
            if (!preview_snapshot_.empty()) queuePreviewOperation(true);
        });
        if (videoItem->devicePointer() != 0) {
            player_->set_d3d11_device(reinterpret_cast<void*>(videoItem->devicePointer()));
        }
    }
#endif
}

void EditorController::loadFiles(const QStringList& paths) {
    if (importing_) {
        setStatus("미디어 분석이 끝난 후 다시 추가하세요");
        return;
    }
    try {
        struct Request final {
            QString path;
            std::string asset_id;
            std::string clip_id;
        };
        std::vector<Request> requests;
        for (const auto& path : paths) {
            const QFileInfo info(path);
            if (!info.isFile()) {
                continue;
            }
            std::string assetId;
            do {
                assetId = "asset-" + std::to_string(++generated_asset_id_);
            } while (timeline_.asset(assetId) != nullptr);
            requests.push_back(Request{
                info.absoluteFilePath(), std::move(assetId), makeUniqueClipId("clip")});
        }
        if (requests.empty()) {
            return;
        }
        const auto ffprobe = ffgui::locate_ffprobe();
        const auto ffmpeg = ffgui::locate_ffmpeg();
        importing_ = true;
        emit importingChanged();
        setStatus(QString("프레임 분석 중 · %1개 파일").arg(requests.size()));
        import_watcher_.setFuture(QtConcurrent::run(
            [ffprobe, ffmpeg, requests = std::move(requests)]() mutable {
                std::vector<PendingImport> result;
                result.reserve(requests.size());
                for (auto& request : requests) {
                    const auto clipId = std::move(request.clip_id);
                    auto analyzed = ffgui::analyze_media(
                        ffprobe, ffmpeg, request.path, std::move(request.asset_id));
                    result.push_back(PendingImport{
                        std::move(analyzed.asset),
                        clipId,
                        std::move(analyzed.thumbnail_atlas)});
                }
                return result;
            }));
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::loadUrls(const QList<QUrl>& urls) {
    QStringList paths;
    paths.reserve(urls.size());
    for (const auto& url : urls) {
        if (url.isLocalFile()) {
            paths.push_back(url.toLocalFile());
        }
    }
    loadFiles(paths);
}

void EditorController::seek(qint64 timelinePosition) {
    playhead_ns_ = std::clamp<qint64>(timelinePosition, 0, durationNs());
    emit playheadChanged();
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
    pending_preview_seek_ = playhead_ns_;
    queuePreviewOperation(false);
#endif
}

void EditorController::scrub(qint64 timelinePosition, bool finalPosition) {
    playhead_ns_ = std::clamp<qint64>(timelinePosition, 0, durationNs());
    emit playheadChanged();
    submitCachedScrubFrame(playhead_ns_);
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
    if (!finalPosition) return;
    pending_preview_seek_ = playhead_ns_;
    queuePreviewOperation(false);
#else
    static_cast<void>(finalPosition);
#endif
}

void EditorController::submitCachedScrubFrame(qint64 timelinePosition) {
#ifdef FFGUI_HAS_GES
    auto* item = qobject_cast<VideoPreviewItem*>(video_item_);
    const auto mapped = timeline_.locate(timelinePosition);
    if (item == nullptr || !mapped.has_value()) return;
    const auto assetId = QString::fromStdString(mapped->asset_id);
    const auto atlasPath = thumbnail_atlases_.value(assetId);
    const auto* asset = timeline_.asset(mapped->asset_id);
    if (atlasPath.isEmpty() || asset == nullptr || asset->duration() <= 0) return;
    auto found = thumbnail_images_.find(assetId);
    if (found == thumbnail_images_.end()) {
        QImage loaded(atlasPath);
        if (loaded.isNull()) return;
        found = thumbnail_images_.insert(assetId, loaded.convertToFormat(QImage::Format_ARGB32));
    }
    const auto& atlas = found.value();
    constexpr int tileWidth = 160;
    constexpr int tileHeight = 90;
    const auto tileCount = std::max(1, atlas.width() / tileWidth);
    const auto ratio = std::clamp(
        static_cast<double>(mapped->source_time) / static_cast<double>(asset->duration()),
        0.0,
        0.999999);
    const auto tileIndex = std::clamp(
        static_cast<int>(ratio * tileCount), 0, tileCount - 1);
    const auto tile = atlas.copy(tileIndex * tileWidth, 0, tileWidth, tileHeight);
    if (tile.isNull()) return;
    ffgui::PreviewVideoFrame frame;
    frame.width = tile.width();
    frame.height = tile.height();
    frame.cpu_stride = tile.bytesPerLine();
    frame.cpu_pixels = std::make_shared<std::vector<std::uint8_t>>(
        static_cast<std::size_t>(frame.cpu_stride) * frame.height);
    std::memcpy(frame.cpu_pixels->data(), tile.constBits(), frame.cpu_pixels->size());
    frame.pts = timelinePosition;
    frame.serial = ++scrub_frame_serial_;
    ++scrub_frames_submitted_;
    item->submitFrame(std::move(frame));
#else
    static_cast<void>(timelinePosition);
#endif
}

void EditorController::togglePlayback() {
#ifdef FFGUI_HAS_GES
    preview_should_play_ = !(preview_should_play_ || playing_);
    if (preview_should_play_ && playhead_ns_ >= durationNs()) {
        playhead_ns_ = 0;
        emit playheadChanged();
    }
    if (preview_should_play_) pending_preview_seek_ = playhead_ns_;
    queuePreviewOperation(false);
#endif
}

void EditorController::stepFrame(int direction) {
    if (direction == 0 || timeline_.clips().empty()) return;
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
#endif
    const auto target = direction > 0
        ? timeline_.next_frame_time(playhead_ns_)
        : timeline_.previous_frame_time(playhead_ns_);
    if (target.has_value()) seek(target.value());
}

void EditorController::jumpEditPoint(int direction) {
    if (direction == 0 || timeline_.clips().empty()) return;
    const auto spans = timeline_.snapshot();
    if (direction > 0) {
        for (const auto& span : spans) {
            if (span.timeline_out > playhead_ns_) {
                seek(span.timeline_out);
                return;
            }
        }
        return;
    }
    for (auto span = spans.rbegin(); span != spans.rend(); ++span) {
        if (span->timeline_in < playhead_ns_) {
            seek(span->timeline_in);
            return;
        }
    }
}

void EditorController::setInPoint() {
    if (timeline_.clips().empty() || playhead_ns_ >= durationNs()) return;
    const auto snapped = timeline_.nearest_frame_time(playhead_ns_).value_or(playhead_ns_);
    if (out_point_ns_ >= 0 && snapped >= out_point_ns_) {
        setStatus("시작점은 끝점보다 앞에 있어야 합니다");
        return;
    }
    in_point_ns_ = snapped;
    emit rangeChanged();
    setStatus("구간 시작점을 표시했습니다");
}

void EditorController::setOutPoint() {
    if (timeline_.clips().empty() || playhead_ns_ <= 0) return;
    const auto snapped = timeline_.nearest_frame_time(playhead_ns_).value_or(playhead_ns_);
    if (in_point_ns_ >= 0 && snapped <= in_point_ns_) {
        setStatus("끝점은 시작점보다 뒤에 있어야 합니다");
        return;
    }
    out_point_ns_ = snapped;
    emit rangeChanged();
    setStatus("구간 끝점을 표시했습니다");
}

void EditorController::clearRange() {
    if (in_point_ns_ < 0 && out_point_ns_ < 0) return;
    in_point_ns_ = -1;
    out_point_ns_ = -1;
    emit rangeChanged();
}

void EditorController::extractMarkedRange() {
    if (in_point_ns_ < 0 || out_point_ns_ <= in_point_ns_) {
        setStatus("먼저 시작점과 끝점을 표시하세요");
        return;
    }
    try {
        const auto removalStart = in_point_ns_;
        timeline_.erase_range(
            removalStart,
            out_point_ns_,
            makeUniqueClipId("clip-range-right"));
        playhead_ns_ = std::min<qint64>(removalStart, durationNs());
        clearRange();
        const auto mapped = timeline_.locate(playhead_ns_);
        if (mapped.has_value()) {
            setSingleSelection(QString::fromStdString(mapped->clip_id));
        } else {
            setSingleSelection(timeline_.clips().empty()
                ? QString{}
                : QString::fromStdString(timeline_.clips().back().id));
        }
        publishTimeline();
        setStatus("표시한 구간을 삭제하고 빈자리를 닫았습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::stop() {
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
    preview_stop_requested_ = true;
    pending_preview_seek_ = 0;
    queuePreviewOperation(false);
#endif
    playhead_ns_ = 0;
    emit playheadChanged();
}

void EditorController::setSingleSelection(QString clipId) {
    selected_clip_id_ = std::move(clipId);
    selected_clip_ids_.clear();
    if (!selected_clip_id_.isEmpty()) selected_clip_ids_.push_back(selected_clip_id_);
    selection_anchor_id_ = selected_clip_id_;
}

void EditorController::selectClip(const QString& clipId, int mode) {
    const auto& clips = timeline_.clips();
    const auto target = std::find_if(clips.begin(), clips.end(), [&clipId](const auto& clip) {
        return QString::fromStdString(clip.id) == clipId;
    });
    if (target == clips.end()) return;

    if (mode == 1) {
        const auto index = selected_clip_ids_.indexOf(clipId);
        if (index >= 0) {
            selected_clip_ids_.removeAt(index);
            selected_clip_id_ = selected_clip_ids_.isEmpty() ? QString{} : selected_clip_ids_.back();
        } else {
            selected_clip_ids_.push_back(clipId);
            selected_clip_id_ = clipId;
        }
        selection_anchor_id_ = clipId;
    } else if (mode == 2 && !selection_anchor_id_.isEmpty()) {
        const auto anchor = std::find_if(
            clips.begin(), clips.end(), [this](const auto& clip) {
                return QString::fromStdString(clip.id) == selection_anchor_id_;
            });
        if (anchor == clips.end()) {
            setSingleSelection(clipId);
        } else {
            auto first = std::distance(clips.begin(), anchor);
            auto last = std::distance(clips.begin(), target);
            if (first > last) std::swap(first, last);
            selected_clip_ids_.clear();
            for (auto index = first; index <= last; ++index) {
                selected_clip_ids_.push_back(
                    QString::fromStdString(clips[static_cast<std::size_t>(index)].id));
            }
            selected_clip_id_ = clipId;
        }
    } else {
        setSingleSelection(clipId);
    }
    emit selectedClipChanged();
}

void EditorController::trimClip(const QString& clipId, qint64 sourceIn, qint64 duration) {
    try {
        timeline_.trim_clip_to_frame_boundaries(clipId.toStdString(), sourceIn, duration);
        setSingleSelection(clipId);
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::moveClip(const QString& clipId, int insertionIndex) {
    moveClips(QStringList{clipId}, insertionIndex);
}

void EditorController::moveClips(const QStringList& clipIds, int insertionIndex) {
    try {
        std::vector<std::string> ids;
        ids.reserve(static_cast<std::size_t>(clipIds.size()));
        for (const auto& id : clipIds) ids.push_back(id.toStdString());
        timeline_.move_clips(ids, static_cast<std::size_t>(std::max(0, insertionIndex)));
        selected_clip_ids_ = clipIds;
        selected_clip_id_ = selected_clip_ids_.isEmpty() ? QString{} : selected_clip_ids_.back();
        selection_anchor_id_ = selected_clip_ids_.isEmpty() ? QString{} : selected_clip_ids_.front();
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

std::string EditorController::makeUniqueClipId(const std::string& prefix) {
    for (;;) {
        const auto candidate = prefix + "-" + std::to_string(++generated_clip_id_);
        const auto exists = std::any_of(
            timeline_.clips().begin(), timeline_.clips().end(), [&candidate](const auto& clip) {
                return clip.id == candidate;
            });
        if (!exists) return candidate;
    }
}

void EditorController::insertAssetAtTime(const QString& assetId, qint64 timelinePosition) {
    try {
        const auto id = assetId.toStdString();
        const auto* asset = timeline_.asset(id);
        if (asset == nullptr) throw std::invalid_argument("unknown media asset");
        const auto clamped = std::clamp<qint64>(timelinePosition, 0, durationNs());
        const auto insertionTime = timeline_.nearest_frame_time(clamped).value_or(clamped);
        const auto insertedId = makeUniqueClipId("clip");
        const auto leftId = makeUniqueClipId("clip-left");
        const auto rightId = makeUniqueClipId("clip-right");
        timeline_.insert_clip_at(
            insertionTime,
            ffgui::Clip{insertedId, id, 0, asset->duration()},
            leftId,
            rightId);
        setSingleSelection(QString::fromStdString(insertedId));
        playhead_ns_ = insertionTime;
        publishTimeline();
        setStatus("미디어를 타임라인에 삽입했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::splitAtPlayhead() {
    const auto mapped = timeline_.locate(playhead_ns_);
    if (!mapped.has_value()) {
        return;
    }
    try {
        const auto left = makeUniqueClipId(mapped->clip_id + "-left");
        const auto right = makeUniqueClipId(mapped->clip_id + "-right");
        const auto splitPosition = timeline_.nearest_frame_time(playhead_ns_).value_or(playhead_ns_);
        timeline_.split_at(splitPosition, left, right);
        playhead_ns_ = splitPosition;
        setSingleSelection(QString::fromStdString(right));
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::deleteSelectedClip() {
    if (selected_clip_ids_.isEmpty()) {
        return;
    }
    try {
        std::vector<std::string> selectedIds;
        selectedIds.reserve(static_cast<std::size_t>(selected_clip_ids_.size()));
        for (const auto& id : selected_clip_ids_) selectedIds.push_back(id.toStdString());
        timeline_.erase_clips(selectedIds);
        setSingleSelection(timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id));
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedClipVolumePercent(int percent) {
    if (selected_clip_ids_.isEmpty()) return;
    const auto selected = selected_clip_id_.toStdString();
    const auto found = std::find_if(timeline_.clips().begin(), timeline_.clips().end(),
        [&selected](const auto& clip) { return clip.id == selected; });
    if (found == timeline_.clips().end()) return;
    auto audio = found->audio;
    audio.gain = static_cast<double>(std::clamp(percent, 0, 400)) / 100.0;
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_audio(ids, audio);
        emit selectedClipChanged();
        publishTimeline();
        setStatus(QStringLiteral("선택 클립 볼륨 · %1%").arg(percent));
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedClipMuted(bool muted) {
    if (selected_clip_ids_.isEmpty()) return;
    const auto selected = selected_clip_id_.toStdString();
    const auto found = std::find_if(timeline_.clips().begin(), timeline_.clips().end(),
        [&selected](const auto& clip) { return clip.id == selected; });
    if (found == timeline_.clips().end()) return;
    auto audio = found->audio;
    audio.muted = muted;
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_audio(ids, audio);
        emit selectedClipChanged();
        publishTimeline();
        setStatus(muted ? "선택 클립 음소거" : "선택 클립 음소거 해제");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedClipFadeInMs(int milliseconds) {
    if (selected_clip_ids_.isEmpty()) return;
    const auto selected = selected_clip_id_.toStdString();
    const auto found = std::find_if(timeline_.clips().begin(), timeline_.clips().end(),
        [&selected](const auto& clip) { return clip.id == selected; });
    if (found == timeline_.clips().end()) return;
    auto audio = found->audio;
    audio.fade_in = static_cast<ffgui::TimeNs>(std::clamp(milliseconds, 0, 3'600'000)) * 1'000'000;
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_audio(ids, audio);
        emit selectedClipChanged();
        publishTimeline();
        setStatus("선택 클립 페이드 인 변경");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedClipFadeOutMs(int milliseconds) {
    if (selected_clip_ids_.isEmpty()) return;
    const auto selected = selected_clip_id_.toStdString();
    const auto found = std::find_if(timeline_.clips().begin(), timeline_.clips().end(),
        [&selected](const auto& clip) { return clip.id == selected; });
    if (found == timeline_.clips().end()) return;
    auto audio = found->audio;
    audio.fade_out = static_cast<ffgui::TimeNs>(std::clamp(milliseconds, 0, 3'600'000)) * 1'000'000;
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_audio(ids, audio);
        emit selectedClipChanged();
        publishTimeline();
        setStatus("선택 클립 페이드 아웃 변경");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedClipSpeedPercent(int percent) {
    if (selected_clip_ids_.isEmpty()) return;
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        const auto clamped = std::clamp(percent, 25, 400);
        timeline_.set_clips_playback_rate(ids, static_cast<double>(clamped) / 100.0);
        publishTimeline();
        setStatus(QStringLiteral("선택 클립 속도 · %1%").arg(clamped));
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedClipBrightness(int percent) {
    if (selected_clip_ids_.isEmpty()) return;
    auto color = ffgui::ClipColor{
        static_cast<double>(std::clamp(percent, -100, 100)) / 100.0,
        static_cast<double>(selectedClipContrast()) / 100.0,
        static_cast<double>(selectedClipSaturation()) / 100.0};
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_color(ids, color);
        publishTimeline();
        setStatus(QStringLiteral("밝기 · %1").arg(percent));
    } catch (const std::exception& error) { setStatus(QString::fromUtf8(error.what())); }
}

void EditorController::setSelectedClipContrast(int percent) {
    if (selected_clip_ids_.isEmpty()) return;
    auto color = ffgui::ClipColor{
        static_cast<double>(selectedClipBrightness()) / 100.0,
        static_cast<double>(std::clamp(percent, 0, 200)) / 100.0,
        static_cast<double>(selectedClipSaturation()) / 100.0};
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_color(ids, color);
        publishTimeline();
        setStatus(QStringLiteral("대비 · %1%").arg(percent));
    } catch (const std::exception& error) { setStatus(QString::fromUtf8(error.what())); }
}

void EditorController::setSelectedClipSaturation(int percent) {
    if (selected_clip_ids_.isEmpty()) return;
    auto color = ffgui::ClipColor{
        static_cast<double>(selectedClipBrightness()) / 100.0,
        static_cast<double>(selectedClipContrast()) / 100.0,
        static_cast<double>(std::clamp(percent, 0, 200)) / 100.0};
    try {
        std::vector<std::string> ids;
        for (const auto& id : selected_clip_ids_) ids.push_back(id.toStdString());
        timeline_.set_clips_color(ids, color);
        publishTimeline();
        setStatus(QStringLiteral("채도 · %1%").arg(percent));
    } catch (const std::exception& error) { setStatus(QString::fromUtf8(error.what())); }
}

void EditorController::setSelectedClipDissolveMs(int milliseconds) {
    if (selected_clip_id_.isEmpty()) return;
    try {
        timeline_.set_clip_dissolve(
            selected_clip_id_.toStdString(),
            static_cast<ffgui::TimeNs>(std::max(0, milliseconds)) * 1'000'000);
        publishTimeline();
        setStatus(milliseconds > 0
            ? QStringLiteral("디졸브 · %1초").arg(milliseconds / 1000.0, 0, 'f', 2)
            : QStringLiteral("디졸브 제거"));
    } catch (const std::exception& error) { setStatus(QString::fromUtf8(error.what())); }
}

void EditorController::trimAllClipEdges(int frontFrames, int backFrames) {
    try {
        timeline_.trim_all_clip_edges(
            static_cast<std::size_t>(std::max(0, frontFrames)),
            static_cast<std::size_t>(std::max(0, backFrames)));
        publishTimeline();
        setStatus(QStringLiteral("전체 트림 · 앞 %1프레임 / 뒤 %2프레임")
            .arg(frontFrames).arg(backFrames));
    } catch (const std::exception& error) { setStatus(QString::fromUtf8(error.what())); }
}

void EditorController::addCaptionAtPlayhead() {
    addTextOverlay(QStringLiteral("새 문구"), 2000);
}

void EditorController::addTextOverlay(const QString& text, int durationMs) {
    if (durationNs() <= 0 || playhead_ns_ >= durationNs()) return;
    try {
        const auto cleaned = text.trimmed();
        if (cleaned.isEmpty()) throw std::invalid_argument("문구를 입력하세요");
        std::string id;
        do {
            id = "caption-" + std::to_string(++generated_caption_id_);
        } while (std::ranges::any_of(
            timeline_.captions(), [&id](const auto& caption) { return caption.id == id; }));
        const auto start = timeline_.nearest_frame_time(playhead_ns_).value_or(playhead_ns_);
        const auto available = durationNs() - start;
        const auto duration = std::clamp<ffgui::TimeNs>(
            static_cast<ffgui::TimeNs>(durationMs) * 1'000'000,
            std::min<ffgui::TimeNs>(100'000'000, available), available);
        timeline_.add_caption(ffgui::CaptionCue{
            id, cleaned.toUtf8().toStdString(), start, duration, 0.5, 0.5, 44});
        selected_caption_id_ = QString::fromStdString(id);
        publishTimeline();
        emit captionSelectionChanged();
        setStatus("현재 위치에 문구를 추가했습니다. 화면에서 끌어 배치하세요");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::selectCaption(const QString& captionId) {
    const auto id = captionId.toStdString();
    if (std::ranges::none_of(
            timeline_.captions(), [&id](const auto& caption) { return caption.id == id; })) {
        return;
    }
    selected_caption_id_ = captionId;
    emit captionSelectionChanged();
}

void EditorController::updateSelectedCaption(const QString& text, int durationMs) {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    if (found == timeline_.captions().end()) return;
    try {
        auto replacement = *found;
        const auto cleaned = text.trimmed();
        if (cleaned.isEmpty()) throw std::invalid_argument("자막 내용은 비워둘 수 없습니다");
        replacement.text = cleaned.toUtf8().toStdString();
        const auto available = durationNs() - replacement.timeline_in;
        replacement.duration = std::clamp<ffgui::TimeNs>(
            static_cast<ffgui::TimeNs>(durationMs) * 1'000'000,
            std::min<ffgui::TimeNs>(100'000'000, available),
            available);
        timeline_.update_caption(std::move(replacement));
        publishTimeline();
        emit captionSelectionChanged();
        setStatus("자막을 수정했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::updateCaptionPosition(
    const QString& captionId,
    qreal positionX,
    qreal positionY) {
    const auto id = captionId.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    if (found == timeline_.captions().end()) return;
    try {
        auto replacement = *found;
        replacement.position_x = std::clamp<double>(positionX, 0.0, 1.0);
        replacement.position_y = std::clamp<double>(positionY, 0.0, 1.0);
        timeline_.update_caption(std::move(replacement));
        selected_caption_id_ = captionId;
        publishTimeline();
        setStatus("문구 위치를 변경했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedCaptionFontSize(int pixels) {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    if (found == timeline_.captions().end()) return;
    try {
        auto replacement = *found;
        replacement.font_size = std::clamp(pixels, 12, 160);
        timeline_.update_caption(std::move(replacement));
        publishTimeline();
        setStatus("문구 크기를 변경했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::setSelectedCaptionBackgroundOpacity(int percent) {
    const auto id = selected_caption_id_.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    if (found == timeline_.captions().end()) return;
    try {
        auto replacement = *found;
        replacement.background_opacity = std::clamp(percent, 0, 100);
        timeline_.update_caption(std::move(replacement));
        publishTimeline();
        setStatus(percent > 0 ? "문구 배경을 조정했습니다" : "문구 배경을 제거했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::deleteSelectedCaption() {
    if (selected_caption_id_.isEmpty()) return;
    try {
        timeline_.erase_caption(selected_caption_id_.toStdString());
        selected_caption_id_.clear();
        publishTimeline();
        emit captionSelectionChanged();
        setStatus("자막을 삭제했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::moveCaption(const QString& captionId, qint64 timelineIn) {
    const auto id = captionId.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    if (found == timeline_.captions().end()) return;
    try {
        auto replacement = *found;
        replacement.timeline_in = std::clamp<ffgui::TimeNs>(
            timelineIn, 0, durationNs() - replacement.duration);
        timeline_.update_caption(std::move(replacement));
        selected_caption_id_ = captionId;
        publishTimeline();
        setStatus("자막 위치를 이동했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::trimCaption(
    const QString& captionId,
    qint64 timelineIn,
    qint64 duration) {
    const auto id = captionId.toStdString();
    const auto found = std::ranges::find(timeline_.captions(), id, &ffgui::CaptionCue::id);
    if (found == timeline_.captions().end()) return;
    try {
        const auto start = std::clamp<ffgui::TimeNs>(timelineIn, 0, durationNs() - 100'000'000);
        const auto available = durationNs() - start;
        auto replacement = *found;
        replacement.timeline_in = start;
        replacement.duration = std::clamp<ffgui::TimeNs>(duration, 100'000'000, available);
        timeline_.update_caption(std::move(replacement));
        selected_caption_id_ = captionId;
        publishTimeline();
        setStatus("자막 구간을 조정했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::importSrtUrl(const QUrl& url) {
    if (!url.isLocalFile() || durationNs() <= 0) {
        setStatus("자막을 넣을 타임라인과 로컬 SRT 파일이 필요합니다");
        return;
    }
    try {
        QFile file(url.toLocalFile());
        if (!file.open(QIODevice::ReadOnly)) throw std::runtime_error("SRT file could not be opened");
        const auto contents = file.readAll();
        const auto parsed = ffgui::parse_srt(std::string_view(
            contents.constData(), static_cast<std::size_t>(contents.size())));
        std::vector<ffgui::CaptionCue> imported;
        for (const auto& cue : parsed) {
            if (cue.timeline_in >= durationNs()) continue;
            std::string id;
            do {
                id = "caption-" + std::to_string(++generated_caption_id_);
            } while (std::ranges::any_of(timeline_.captions(),
                [&id](const auto& caption) { return caption.id == id; }));
            imported.push_back(ffgui::CaptionCue{
                std::move(id),
                cue.text,
                cue.timeline_in,
                std::min<ffgui::TimeNs>(cue.duration, durationNs() - cue.timeline_in)});
        }
        if (imported.empty()) {
            throw std::invalid_argument("타임라인 범위 안에 가져올 자막이 없습니다");
        }
        const auto firstId = QString::fromStdString(imported.front().id);
        const auto importedCount = imported.size();
        timeline_.add_captions(std::move(imported));
        selected_caption_id_ = firstId;
        publishTimeline();
        setStatus(QStringLiteral("SRT 자막 %1개를 가져왔습니다").arg(importedCount));
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::exportSrtUrl(const QUrl& url) {
    if (!url.isLocalFile() || timeline_.captions().empty()) {
        setStatus("내보낼 자막과 로컬 SRT 경로가 필요합니다");
        return;
    }
    try {
        std::vector<ffgui::SrtCue> cues;
        cues.reserve(timeline_.captions().size());
        for (const auto& caption : timeline_.captions()) {
            cues.push_back(ffgui::SrtCue{
                caption.text, caption.timeline_in, caption.duration});
        }
        const auto serialized = ffgui::serialize_srt(cues);
        QSaveFile file(url.toLocalFile());
        if (!file.open(QIODevice::WriteOnly) ||
            file.write(serialized.data(), static_cast<qint64>(serialized.size())) !=
                static_cast<qint64>(serialized.size()) || !file.commit()) {
            throw std::runtime_error("SRT file could not be saved atomically");
        }
        setStatus("SRT 자막을 내보냈습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::duplicateSelectedClip() {
    if (selected_clip_ids_.isEmpty()) return;
    try {
        const auto& clips = timeline_.clips();
        std::vector<ffgui::Clip> duplicates;
        QStringList duplicateIds;
        std::size_t insertionIndex = 0;
        for (std::size_t index = 0; index < clips.size(); ++index) {
            const auto clipId = QString::fromStdString(clips[index].id);
            if (!selected_clip_ids_.contains(clipId)) continue;
            insertionIndex = index + 1;
            auto duplicate = clips[index];
            duplicate.id = makeUniqueClipId(duplicate.id + "-copy");
            duplicateIds.push_back(QString::fromStdString(duplicate.id));
            duplicates.push_back(std::move(duplicate));
        }
        if (duplicates.empty()) return;
        timeline_.insert_clips(insertionIndex, std::move(duplicates));
        selected_clip_ids_ = std::move(duplicateIds);
        selected_clip_id_ = selected_clip_ids_.back();
        selection_anchor_id_ = selected_clip_ids_.front();
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::undo() {
    if (timeline_.undo()) {
        setSingleSelection(timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id));
        publishTimeline();
    }
}

void EditorController::redo() {
    if (timeline_.redo()) {
        setSingleSelection(timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id));
        publishTimeline();
    }
}

void EditorController::saveProject(const QString& path) {
    try {
        QJsonArray assets;
        std::vector<std::string> assetIds;
        assetIds.reserve(timeline_.assets().size());
        for (const auto& [id, asset] : timeline_.assets()) {
            static_cast<void>(asset);
            assetIds.push_back(id);
        }
        std::sort(assetIds.begin(), assetIds.end());
        for (const auto& id : assetIds) {
            const auto& asset = timeline_.assets().at(id);
            QJsonArray framePts;
            for (const auto pts : asset.frame_pts()) {
                framePts.push_back(timeString(pts));
            }
            QJsonArray audioPeaks;
            for (const auto peak : asset.audio_peaks()) {
                audioPeaks.push_back(peak);
            }
            QJsonArray keyframePts;
            for (const auto pts : asset.keyframe_pts()) {
                keyframePts.push_back(timeString(pts));
            }
            assets.push_back(QJsonObject{
                {"id", QString::fromStdString(id)},
                {"path", QString::fromStdWString(asset.path().wstring())},
                {"durationNs", timeString(asset.duration())},
                {"framePtsNs", framePts},
                {"audioPeaks", audioPeaks},
                {"keyframePtsNs", keyframePts},
                {"thumbnailAtlas", thumbnail_atlases_.value(QString::fromStdString(id))}});
        }

        QJsonArray clips;
        for (const auto& clip : timeline_.clips()) {
            clips.push_back(QJsonObject{
                {"id", QString::fromStdString(clip.id)},
                {"assetId", QString::fromStdString(clip.asset_id)},
                {"sourceInNs", timeString(clip.source_in)},
                {"durationNs", timeString(clip.duration)},
                {"audioGain", clip.audio.gain},
                {"audioMuted", clip.audio.muted},
                {"audioFadeInNs", timeString(clip.audio.fade_in)},
                {"audioFadeOutNs", timeString(clip.audio.fade_out)},
                {"playbackRate", clip.playback_rate},
                {"brightness", clip.color.brightness},
                {"contrast", clip.color.contrast},
                {"saturation", clip.color.saturation},
                {"transitionInNs", timeString(clip.transition_in)}});
        }
        QJsonArray captions;
        for (const auto& caption : timeline_.captions()) {
            captions.push_back(QJsonObject{
                {"id", QString::fromStdString(caption.id)},
                {"text", QString::fromUtf8(caption.text)},
                {"timelineInNs", timeString(caption.timeline_in)},
                {"durationNs", timeString(caption.duration)},
                {"positionX", caption.position_x},
                {"positionY", caption.position_y},
                {"fontSize", caption.font_size},
                {"backgroundOpacity", caption.background_opacity}});
        }
        const QJsonObject stamp{
            {"enabled", stamp_enabled_},
            {"worker", stamp_worker_},
            {"information", stamp_information_},
            {"barPercent", stamp_bar_percent_},
            {"opacity", stamp_opacity_},
            {"mode", stamp_mode_}};
        const QJsonDocument document(QJsonObject{
            {"format", "ffmpegGUI-next"},
            {"version", 1},
            {"assets", assets},
            {"clips", clips},
            {"captions", captions},
            {"stamp", stamp}});

        QSaveFile file(path);
        if (!file.open(QIODevice::WriteOnly) || file.write(document.toJson()) < 0 || !file.commit()) {
            throw std::runtime_error("project file could not be saved atomically");
        }
        setStatus("프로젝트 저장 완료");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::loadProject(const QString& path) {
    if (importing_) {
        setStatus("미디어 분석 중에는 프로젝트를 열 수 없습니다");
        return;
    }
    try {
        QFile file(path);
        if (!file.open(QIODevice::ReadOnly)) {
            throw std::runtime_error("project file could not be opened");
        }
        QJsonParseError parseError;
        const auto document = QJsonDocument::fromJson(file.readAll(), &parseError);
        const auto root = document.object();
        if (parseError.error != QJsonParseError::NoError ||
            root.value("format").toString() != "ffmpegGUI-next" ||
            root.value("version").toInt() != 1) {
            throw std::runtime_error("unsupported or damaged project file");
        }

        ffgui::TimelineModel loaded;
        QHash<QString, QString> loadedAtlases;
        for (const auto value : root.value("assets").toArray()) {
            const auto object = value.toObject();
            const auto assetId = object.value("id").toString();
            std::vector<ffgui::TimeNs> framePts;
            for (const auto pts : object.value("framePtsNs").toArray()) {
                framePts.push_back(parseTime(pts, "framePtsNs"));
            }
            std::vector<float> audioPeaks;
            for (const auto peak : object.value("audioPeaks").toArray()) {
                audioPeaks.push_back(static_cast<float>(peak.toDouble()));
            }
            std::vector<ffgui::TimeNs> keyframePts;
            for (const auto pts : object.value("keyframePtsNs").toArray()) {
                keyframePts.push_back(parseTime(pts, "keyframePtsNs"));
            }
            loaded.add_asset(ffgui::MediaAsset{
                assetId.toStdString(),
                std::filesystem::path(object.value("path").toString().toStdWString()),
                parseTime(object.value("durationNs"), "durationNs"),
                std::move(framePts),
                std::move(audioPeaks),
                std::move(keyframePts)});
            const auto atlas = object.value("thumbnailAtlas").toString();
            if (QFileInfo(atlas).isFile()) {
                loadedAtlases.insert(assetId, atlas);
            }
        }
        for (const auto value : root.value("clips").toArray()) {
            const auto object = value.toObject();
            loaded.append_clip(ffgui::Clip{
                object.value("id").toString().toStdString(),
                object.value("assetId").toString().toStdString(),
                parseTime(object.value("sourceInNs"), "sourceInNs"),
                parseTime(object.value("durationNs"), "durationNs"),
                ffgui::ClipAudio{
                    object.contains("audioGain") ? object.value("audioGain").toDouble() : 1.0,
                    object.value("audioMuted").toBool(false),
                    object.contains("audioFadeInNs")
                        ? parseTime(object.value("audioFadeInNs"), "audioFadeInNs") : 0,
                    object.contains("audioFadeOutNs")
                        ? parseTime(object.value("audioFadeOutNs"), "audioFadeOutNs") : 0},
                object.contains("playbackRate")
                    ? object.value("playbackRate").toDouble() : 1.0,
                ffgui::ClipColor{
                    object.value("brightness").toDouble(0.0),
                    object.contains("contrast") ? object.value("contrast").toDouble() : 1.0,
                    object.contains("saturation") ? object.value("saturation").toDouble() : 1.0},
                object.contains("transitionInNs")
                    ? parseTime(object.value("transitionInNs"), "transitionInNs") : 0});
        }
        for (const auto value : root.value("captions").toArray()) {
            const auto object = value.toObject();
            loaded.add_caption(ffgui::CaptionCue{
                object.value("id").toString().toStdString(),
                object.value("text").toString().toUtf8().toStdString(),
                parseTime(object.value("timelineInNs"), "timelineInNs"),
                parseTime(object.value("durationNs"), "captionDurationNs"),
                object.contains("positionX") ? object.value("positionX").toDouble() : 0.5,
                object.contains("positionY") ? object.value("positionY").toDouble() : 0.5,
                object.contains("fontSize") ? object.value("fontSize").toInt() : 44,
                object.contains("backgroundOpacity")
                    ? object.value("backgroundOpacity").toInt() : 0});
        }
        const auto stamp = root.value("stamp").toObject();
        loaded.clear_history();
        timeline_ = std::move(loaded);
        thumbnail_atlases_ = std::move(loadedAtlases);
        thumbnail_images_.clear();
        waveform_cache_.clear();
        stamp_enabled_ = stamp.value("enabled").toBool(false);
        stamp_worker_ = stamp.value("worker").toString();
        stamp_information_ = stamp.value("information").toString();
        stamp_bar_percent_ = std::clamp(stamp.value("barPercent").toInt(9), 4, 25);
        stamp_opacity_ = std::clamp(stamp.value("opacity").toInt(90), 0, 100);
        stamp_mode_ = std::clamp(stamp.value("mode").toInt(0), 0, 1);
        setSingleSelection(timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id));
        publishTimeline(true);
        emit graphicsChanged();
        setStatus("프로젝트 불러오기 완료");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::saveProjectUrl(const QUrl& url) {
    if (url.isLocalFile()) {
        saveProject(url.toLocalFile());
    } else {
        setStatus("로컬 프로젝트 경로만 저장할 수 있습니다");
    }
}

void EditorController::loadProjectUrl(const QUrl& url) {
    if (url.isLocalFile()) {
        loadProject(url.toLocalFile());
    } else {
        setStatus("로컬 프로젝트 경로만 열 수 있습니다");
    }
}

bool EditorController::outputExists(const QUrl& url) const {
    return url.isLocalFile() && QFileInfo::exists(url.toLocalFile());
}

void EditorController::setExportQuality(int quality) {
    quality = std::clamp(quality, 0, 2);
    if (export_quality_ == quality) return;
    export_quality_ = quality;
    emit exportSettingsChanged();
}

void EditorController::setExportCodec(int codec) {
    codec = std::clamp(codec, 0, 2);
    if (export_codec_ == codec) return;
    export_codec_ = codec;
    emit exportSettingsChanged();
}

void EditorController::setExportContainer(int container) {
    container = std::clamp(container, 0, 2);
    if (export_container_ == container) return;
    export_container_ = container;
    emit exportSettingsChanged();
}

void EditorController::setExportResolution(int resolution) {
    resolution = std::clamp(resolution, 0, 3);
    if (export_resolution_ == resolution) return;
    export_resolution_ = resolution;
    emit exportSettingsChanged();
}

void EditorController::setExportFrameRate(int frameRate) {
    frameRate = std::clamp(frameRate, 0, 3);
    if (export_frame_rate_ == frameRate) return;
    export_frame_rate_ = frameRate;
    emit exportSettingsChanged();
}

void EditorController::setStampEnabled(bool enabled) {
    if (stamp_enabled_ == enabled) return;
    stamp_enabled_ = enabled;
    emit graphicsChanged();
    setStatus(enabled ? "스탬프를 표시합니다" : "스탬프를 숨겼습니다");
}

void EditorController::setStampWorker(const QString& worker) {
    const auto cleaned = worker.trimmed();
    if (stamp_worker_ == cleaned) return;
    stamp_worker_ = cleaned;
    emit graphicsChanged();
}

void EditorController::setStampInformation(const QString& information) {
    const auto cleaned = information.trimmed();
    if (stamp_information_ == cleaned) return;
    stamp_information_ = cleaned;
    emit graphicsChanged();
}

void EditorController::setStampBarPercent(int percent) {
    percent = std::clamp(percent, 4, 25);
    if (stamp_bar_percent_ == percent) return;
    stamp_bar_percent_ = percent;
    emit graphicsChanged();
}

void EditorController::setStampOpacity(int percent) {
    percent = std::clamp(percent, 0, 100);
    if (stamp_opacity_ == percent) return;
    stamp_opacity_ = percent;
    emit graphicsChanged();
}

void EditorController::setStampMode(int mode) {
    mode = std::clamp(mode, 0, 1);
    if (stamp_mode_ == mode) return;
    stamp_mode_ = mode;
    emit graphicsChanged();
    setStatus(mode == 0 ? "스탬프를 영상 위에 겹칩니다"
                        : "원본 영상 크기를 유지하고 캔버스 높이를 확장합니다");
}

QString EditorController::exportExtension() const {
    if (export_container_ == 1) return QStringLiteral("mkv");
    if (export_container_ == 2) return QStringLiteral("mov");
    return QStringLiteral("mp4");
}

QString EditorController::timeText(qint64 timelinePosition) const {
    const auto milliseconds = std::max<qint64>(0, timelinePosition) / 1'000'000;
    const auto hours = milliseconds / 3'600'000;
    const auto minutes = (milliseconds / 60'000) % 60;
    const auto seconds = (milliseconds / 1'000) % 60;
    const auto millis = milliseconds % 1'000;
    return QStringLiteral("%1:%2:%3.%4")
        .arg(hours, 2, 10, QLatin1Char('0'))
        .arg(minutes, 2, 10, QLatin1Char('0'))
        .arg(seconds, 2, 10, QLatin1Char('0'))
        .arg(millis, 3, 10, QLatin1Char('0'));
}

qint64 EditorController::frameNumberAt(qint64 timelinePosition) const {
    const auto clamped = std::clamp<qint64>(timelinePosition, 0, durationNs());
    qint64 frameBase = 0;
    qint64 cursor = 0;
    for (const auto& clip : timeline_.clips()) {
        const auto* asset = timeline_.asset(clip.asset_id);
        const auto clipEnd = cursor + clip.timeline_duration();
        if (asset == nullptr || asset->frame_pts().empty()) {
            cursor = clipEnd;
            continue;
        }
        const auto& frames = asset->frame_pts();
        const auto first = std::lower_bound(frames.begin(), frames.end(), clip.source_in);
        const auto last = std::lower_bound(frames.begin(), frames.end(), clip.source_out());
        if (clamped >= clipEnd) {
            frameBase += std::distance(first, last);
            cursor = clipEnd;
            continue;
        }
        const auto local = std::max<qint64>(0, clamped - cursor);
        const auto sourceTime = clip.source_in + clip.source_offset_for_timeline(local);
        const auto current = std::upper_bound(first, last, sourceTime);
        const auto offset = current == first ? 0 : std::distance(first, current) - 1;
        return frameBase + offset;
    }
    return frameBase;
}

qint64 EditorController::frameCountBetween(qint64 first, qint64 second) const {
    return std::abs(frameNumberAt(second) - frameNumberAt(first));
}

QUrl EditorController::uniqueOutputUrl(const QUrl& url) const {
    if (!url.isLocalFile()) return {};
    const QFileInfo info(url.toLocalFile());
    if (!info.exists()) return url;
    const auto directory = info.absoluteDir();
    const auto base = info.completeBaseName();
    const auto suffix = info.suffix().isEmpty() ? QStringLiteral("mp4") : info.suffix();
    for (int number = 1; number < 10'000; ++number) {
        const auto candidate = directory.filePath(
            QStringLiteral("%1_%2.%3").arg(base).arg(number, 3, 10, QLatin1Char('0')).arg(suffix));
        if (!QFileInfo::exists(candidate)) return QUrl::fromLocalFile(candidate);
    }
    return {};
}

void EditorController::exportTimelineUrl(const QUrl& url) {
    if (exporting_) {
        setStatus("이미 내보내는 중입니다");
        return;
    }
    if (!url.isLocalFile() || timeline_.clips().empty()) {
        setStatus("내보낼 타임라인과 로컬 출력 경로가 필요합니다");
        return;
    }
    auto output = QFileInfo(url.toLocalFile()).absoluteFilePath();
    if (QFileInfo(output).suffix().isEmpty()) output += "." + exportExtension();
    if (QFileInfo::exists(output)) {
        setStatus("기존 파일을 덮어쓰지 않습니다. 새 이름을 선택하세요");
        return;
    }

    ffgui::ExportRequest request;
    request.output_path = std::filesystem::path(output.toStdWString());
    request.prefer_stream_copy = export_codec_ == 2;
    request.quality = static_cast<ffgui::ExportQuality>(export_quality_);
    if (export_resolution_ == 1) {
        request.output_width = 3840; request.output_height = 2160;
    } else if (export_resolution_ == 2) {
        request.output_width = 1920; request.output_height = 1080;
    } else if (export_resolution_ == 3) {
        request.output_width = 1280; request.output_height = 720;
    }
    if (export_frame_rate_ == 1) request.output_fps = 60;
    else if (export_frame_rate_ == 2) request.output_fps = 30;
    else if (export_frame_rate_ == 3) request.output_fps = 24;
    const auto exportSnapshot = timeline_.snapshot();
    if (exportSnapshot.empty()) return;
    last_export_matched_preview_ = false;
    for (const auto& span : exportSnapshot) {
        const auto* asset = timeline_.asset(span.clip.asset_id);
        request.clips.push_back(ffgui::ExportClipInput{
            span.source_path,
            span.clip.source_in,
            span.clip.duration,
            asset != nullptr && !asset->audio_peaks().empty(),
            asset != nullptr ? asset->duration() : 0,
            asset != nullptr ? asset->keyframe_pts() : std::vector<ffgui::TimeNs>{},
            span.clip.audio.gain,
            span.clip.audio.muted,
            span.clip.audio.fade_in,
            span.clip.audio.fade_out,
            span.clip.playback_rate,
            span.clip.color.brightness,
            span.clip.color.contrast,
            span.clip.color.saturation,
            span.clip.transition_in});
    }
    for (const auto& caption : timeline_.captions()) {
        request.captions.push_back(ffgui::ExportCaptionInput{
            caption.text,
            caption.timeline_in,
            caption.duration,
            caption.position_x,
            caption.position_y,
            caption.font_size,
            caption.background_opacity});
    }
    request.stamp = ffgui::ExportStampInput{
        stamp_enabled_,
        stamp_worker_.toUtf8().toStdString(),
        stamp_information_.toUtf8().toStdString(),
        stamp_bar_percent_,
        stamp_opacity_,
        stamp_mode_ == 1};
    const auto exportCache = QDir(QStandardPaths::writableLocation(QStandardPaths::CacheLocation))
        .filePath("export-jobs");
    QDir().mkpath(exportCache);
    export_concat_path_ = QDir(exportCache).filePath(QStringLiteral("%1-%2.ffconcat")
        .arg(QCoreApplication::applicationPid())
        .arg(QDateTime::currentMSecsSinceEpoch()));
    request.concat_script_path = std::filesystem::path(export_concat_path_.toStdWString());
    export_subtitle_path_ = QDir(exportCache).filePath(QStringLiteral("%1-%2.ass")
        .arg(QCoreApplication::applicationPid())
        .arg(QDateTime::currentMSecsSinceEpoch()));
    request.subtitle_script_path = std::filesystem::path(export_subtitle_path_.toStdWString());
    export_request_ = std::move(request);
    // The export contract is the immutable model snapshot captured above. Preview preparation
    // is asynchronous and must never make a newer edit unexportable or export stale clips.
    last_export_matched_preview_ = true;
    export_cpu_fallback_ = false;
    export_cancelled_ = false;
    last_export_stream_copy_ = false;
    export_progress_ = 0;
    export_stage_ = "출력 준비 중";
    export_output_name_ = QFileInfo(output).fileName();
    const auto logDirectory = QDir(
        QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation))
        .filePath("logs");
    QDir().mkpath(logDirectory);
    export_log_path_ = QDir(logDirectory).filePath(QStringLiteral("export-%1.log")
        .arg(QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss-zzz")));
    export_log_file_ = std::make_unique<QFile>(export_log_path_);
    static_cast<void>(export_log_file_->open(QIODevice::WriteOnly | QIODevice::Text));
    if (export_log_file_->isOpen()) {
        export_log_file_->write(QStringLiteral(
            "output=%1\ntimeline_revision=%2\nclips=%3\nexpected_duration_ns=%4\n")
            .arg(output)
            .arg(timeline_.revision())
            .arg(exportSnapshot.size())
            .arg(durationNs())
            .toUtf8());
    }
    exporting_ = true;
    emit exportProgressChanged();
    emit exportingChanged();
#ifdef FFGUI_HAS_GES
    if (playing_ || preview_should_play_) {
        preview_should_play_ = false;
        queuePreviewOperation(false);
    }
#endif
    startExportProcess(export_codec_ == 1
        ? ffgui::ExportVideoEncoder::hevc_nvenc
        : ffgui::ExportVideoEncoder::h264_nvenc);
}

void EditorController::startExportProcess(ffgui::ExportVideoEncoder encoder) {
    try {
        export_request_->video_encoder = encoder;
        const auto plan = ffgui::compile_ffmpeg_export(*export_request_);
        export_duration_ns_ = plan.duration;
        export_stream_copy_active_ = plan.mode == ffgui::ExportMode::stream_copy;
        if (export_stream_copy_active_) {
            QSaveFile script(export_concat_path_);
            const auto contents = QByteArray::fromStdString(plan.concat_script);
            if (!script.open(QIODevice::WriteOnly) || script.write(contents) != contents.size() ||
                !script.commit()) {
                throw std::runtime_error("stream-copy concat script could not be written");
            }
        }
        if (!plan.subtitle_script.empty()) {
            QSaveFile script(export_subtitle_path_);
            const auto contents = QByteArray::fromStdString(plan.subtitle_script);
            if (!script.open(QIODevice::WriteOnly) || script.write(contents) != contents.size() ||
                !script.commit()) {
                throw std::runtime_error("subtitle ASS script could not be written");
            }
        }
        QStringList arguments;
        arguments.reserve(static_cast<qsizetype>(plan.arguments.size()));
        for (const auto& argument : plan.arguments) {
            arguments.push_back(QString::fromUtf8(argument.data(), static_cast<qsizetype>(argument.size())));
        }
        export_stderr_.clear();
        export_process_.setProgram(ffgui::locate_ffmpeg());
        export_process_.setArguments(arguments);
        export_stage_ = export_stream_copy_active_
            ? QStringLiteral("무손실 복사")
            : (encoder == ffgui::ExportVideoEncoder::h264_nvenc ||
               encoder == ffgui::ExportVideoEncoder::hevc_nvenc
                ? QStringLiteral("NVENC 인코딩")
                : QStringLiteral("CPU 인코딩"));
        if (export_log_file_ && export_log_file_->isOpen()) {
            export_log_file_->write(QStringLiteral("\n--- %1 ---\n%2 %3\n")
                .arg(export_stage_, export_process_.program(), arguments.join(' ')).toUtf8());
            export_log_file_->flush();
        }
        qInfo().noquote() << "export process started"
                          << "stage=" << export_stage_
                          << "duration_ns=" << export_duration_ns_
                          << "output=" << export_output_name_
                          << "log=" << export_log_path_;
        setStatus(export_stream_copy_active_
            ? "내보내는 중 · 무손실 복사"
            : (encoder == ffgui::ExportVideoEncoder::h264_nvenc ||
               encoder == ffgui::ExportVideoEncoder::hevc_nvenc
                ? "내보내는 중 · NVENC"
                : "내보내는 중 · CPU"));
        export_process_.start();
        emit exportProgressChanged();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
        finishExport(false);
    }
}

void EditorController::startExportValidation() {
    if (!export_request_.has_value()) {
        finishExport(false);
        return;
    }
    try {
        export_stage_ = "결과 검증 중";
        export_progress_ = std::max<qreal>(export_progress_, 0.99);
        emit exportProgressChanged();
        setStatus("내보낸 영상의 스트림과 재생시간을 확인하는 중입니다");
        const auto output = QString::fromStdWString(export_request_->output_path.wstring());
        export_validation_process_.setProgram(ffgui::locate_ffprobe());
        export_validation_process_.setArguments({
            "-v", "error", "-show_entries", "stream=codec_type:format=duration",
            "-of", "json", output});
        export_validation_process_.start();
    } catch (const std::exception& error) {
        export_stderr_.append(error.what());
        finishExport(false);
    }
}

void EditorController::cancelExport() {
    if (!exporting_) return;
    export_cancelled_ = true;
    export_stage_ = "취소 중";
    emit exportProgressChanged();
    setStatus("내보내기를 취소하는 중입니다");
    if (export_process_.state() != QProcess::NotRunning) export_process_.kill();
    if (export_validation_process_.state() != QProcess::NotRunning) {
        export_validation_process_.kill();
    }
}

void EditorController::finishExport(bool success) {
    if (!exporting_) return;
    const auto output = export_request_.has_value()
        ? QString::fromStdWString(export_request_->output_path.wstring())
        : QString{};
    if (success) {
        last_export_stream_copy_ = export_stream_copy_active_;
        export_progress_ = 1;
        setStatus(QStringLiteral("내보내기 완료 · %1").arg(QFileInfo(output).fileName()));
    } else {
        QFile::remove(output);
        if (export_cancelled_) {
            setStatus("내보내기가 취소되었습니다");
        } else {
            const auto lines = QString::fromUtf8(export_stderr_).trimmed().split('\n');
            const auto detail = lines.isEmpty() ? QString{} : lines.back().trimmed();
            setStatus(detail.isEmpty()
                ? QStringLiteral("내보내기에 실패했습니다")
                : QStringLiteral("내보내기 실패 · %1").arg(detail));
        }
    }
    qInfo().noquote() << "export job finished"
                      << "success=" << success
                      << "cancelled=" << export_cancelled_
                      << "output=" << output
                      << "log=" << export_log_path_;
    if (!export_concat_path_.isEmpty()) QFile::remove(export_concat_path_);
    if (!export_subtitle_path_.isEmpty()) QFile::remove(export_subtitle_path_);
    export_concat_path_.clear();
    export_subtitle_path_.clear();
    export_stream_copy_active_ = false;
    exporting_ = false;
    export_stage_.clear();
    emit exportProgressChanged();
    emit exportingChanged();
    emit exportFinished(success, QUrl::fromLocalFile(output));
    export_request_.reset();
    if (export_log_file_) {
        export_log_file_->flush();
        export_log_file_->close();
        export_log_file_.reset();
    }
}

void EditorController::queuePreviewOperation(bool restorePosition) {
#ifdef FFGUI_HAS_GES
    preview_update_timer_.stop();
    if (restorePosition) pending_preview_seek_ = playhead_ns_;
    preview_operation_pending_ = true;
    startPreviewOperation();
#else
    static_cast<void>(restorePosition);
#endif
}

void EditorController::startPreviewOperation() {
#ifdef FFGUI_HAS_GES
    if (preview_watcher_.isRunning() || !preview_operation_pending_) return;

    const auto generation = preview_generation_;
    const bool rebuild = !preview_applied_generation_.has_value() ||
        preview_applied_generation_.value() != generation;
    auto spans = rebuild ? preview_snapshot_ : std::vector<ffgui::TimelineSpan>{};
    // Caption overlay operations can invalidate the NLE composition during an accurate seek.
    // Keep the core editing preview video/audio-only until the overlay path has its own
    // gap-safe composition and regression suite.
    auto captions = std::vector<ffgui::CaptionCue>{};
    const auto seekTarget = pending_preview_seek_;
    const bool shouldPlay = preview_should_play_;
    const bool shouldStop = preview_stop_requested_;
    pending_preview_seek_.reset();
    preview_stop_requested_ = false;
    preview_operation_pending_ = false;
    if (!preview_busy_) {
        preview_busy_ = true;
        emit previewBusyChanged();
    }
    if (preview_failed_) {
        preview_failed_ = false;
        emit previewFailedChanged();
    }
    setStatus(rebuild
        ? QStringLiteral("미리보기 타임라인 준비 중…")
        : QStringLiteral("미리보기 위치 이동 중…"));

    auto* player = player_.get();
    preview_watcher_.setFuture(QtConcurrent::run(
        [player,
         generation,
         rebuild,
         spans = std::move(spans),
         captions = std::move(captions),
         seekTarget,
         shouldPlay,
         shouldStop]() mutable {
            PreviewOperationResult result;
            result.generation = generation;
            result.rebuilt = rebuild;
            QElapsedTimer elapsed;
            elapsed.start();
            qInfo().noquote() << "preview operation started"
                              << "generation=" << generation
                              << "rebuild=" << rebuild
                              << "seek=" << seekTarget.value_or(-1)
                              << "play=" << shouldPlay;
            try {
                if (rebuild) player->set_timeline(std::move(spans), std::move(captions));
                if (shouldStop) {
                    player->stop();
                } else {
                    if (seekTarget.has_value() && player->duration() > 0) {
                        const auto target = std::clamp<qint64>(
                            seekTarget.value(), 0, static_cast<qint64>(player->duration()));
                        player->seek(target);
                    }
                    if (shouldPlay) {
                        player->play();
                    } else if (player->state() == ffgui::PlaybackState::playing) {
                        player->pause();
                    }
                }
                result.success = true;
            } catch (const std::exception& error) {
                result.error = QString::fromUtf8(error.what());
            }
            qInfo().noquote() << "preview operation finished"
                              << "generation=" << generation
                              << "success=" << result.success
                              << "elapsed_ms=" << elapsed.elapsed()
                              << "error=" << result.error;
            return result;
        }));
#endif
}

void EditorController::publishTimeline(bool resetPlayhead) {
    QElapsedTimer publishElapsed;
    publishElapsed.start();
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
#endif
    if (resetPlayhead) {
        playhead_ns_ = 0;
    } else {
        playhead_ns_ = std::clamp<qint64>(playhead_ns_, 0, durationNs());
    }
    preview_snapshot_ = timeline_.snapshot();
    preview_revision_ = timeline_.revision();
    ++preview_generation_;
    clips_cache_.reset();
    media_assets_cache_.reset();
    captions_cache_.reset();
    const auto previousIn = in_point_ns_;
    const auto previousOut = out_point_ns_;
    if (in_point_ns_ > durationNs()) in_point_ns_ = -1;
    if (out_point_ns_ > durationNs()) out_point_ns_ = durationNs();
    if (in_point_ns_ >= 0 && out_point_ns_ >= 0 && in_point_ns_ >= out_point_ns_) {
        in_point_ns_ = -1;
        out_point_ns_ = -1;
    }
    emit timelineChanged();
    emit playheadChanged();
    if (previousIn != in_point_ns_ || previousOut != out_point_ns_) emit rangeChanged();
    emit selectedClipChanged();
    if (!selected_caption_id_.isEmpty()) {
        const auto selected = selected_caption_id_.toStdString();
        if (std::ranges::none_of(timeline_.captions(),
                [&selected](const auto& caption) { return caption.id == selected; })) {
            selected_caption_id_.clear();
        }
    }
    emit captionSelectionChanged();
    emit historyChanged();
#ifdef FFGUI_HAS_GES
    preview_update_timer_.start();
    setStatus(timeline_.clips().empty() ? "미디어를 추가하세요" : "미리보기 갱신 중");
#else
    setStatus(timeline_.clips().empty() ? "미디어를 추가하세요" : "재생 준비 완료");
#endif
    if (publishElapsed.elapsed() >= 50) {
        qWarning().noquote() << "timeline publish blocked the UI"
                             << "elapsed_ms=" << publishElapsed.elapsed()
                             << "clips=" << timeline_.clips().size();
    }
}

void EditorController::setStatus(QString status) {
    if (status_ == status) {
        return;
    }
    status_ = std::move(status);
    qInfo().noquote() << "status changed" << status_;
    emit statusChanged();
}
