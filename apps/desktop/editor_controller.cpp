#include "editor_controller.hpp"
#include "ffprobe_analyzer.hpp"
#include "d3d11_video_item.hpp"
#include "color_scope_item.hpp"
#include "core/subtitle_srt.hpp"
#include "core/render_preflight.hpp"
#include "color/color_frame_processor.hpp"
#include "color/grade_processor.hpp"
#include "color/ocio_engine.hpp"

#include <QFile>
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaObject>
#include <QPointer>
#include <QJSEngine>
#include <QSaveFile>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QDateTime>
#include <QDebug>
#include <QDesktopServices>
#include <QGuiApplication>
#include <QClipboard>
#include <QQuickWindow>
#include <QSettings>
#include <QSet>
#include <QtConcurrentRun>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef FFGUI_HAS_GES
#ifndef NOMINMAX
#define NOMINMAX
#endif
#define GST_USE_UNSTABLE_API
#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/d3d11/gstd3d11.h>
#endif

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

QString mediaKindName(ffgui::MediaKind kind) {
    switch (kind) {
    case ffgui::MediaKind::animated_image: return QStringLiteral("animatedImage");
    case ffgui::MediaKind::still_image: return QStringLiteral("stillImage");
    case ffgui::MediaKind::image_sequence: return QStringLiteral("imageSequence");
    case ffgui::MediaKind::video: return QStringLiteral("video");
    }
    return QStringLiteral("video");
}

ffgui::MediaKind parseMediaKind(const QString& value) {
    if (value == QStringLiteral("animatedImage")) return ffgui::MediaKind::animated_image;
    if (value == QStringLiteral("stillImage")) return ffgui::MediaKind::still_image;
    if (value == QStringLiteral("imageSequence")) return ffgui::MediaKind::image_sequence;
    return ffgui::MediaKind::video;
}

QJsonObject serializeGradeGraph(const ffgui::GradeGraph& graph) {
    QJsonArray nodes;
    for (const auto& node : graph.nodes()) {
        QJsonObject parameters;
        for (const auto& [name, value] : node.parameters) {
            parameters.insert(QString::fromStdString(name), value);
        }
        QJsonObject curves;
        for (const auto& [name, points] : node.curves) {
            QJsonArray serializedPoints;
            for (const auto& point : points) {
                serializedPoints.push_back(QJsonArray{point.x, point.y});
            }
            curves.insert(QString::fromStdString(name), serializedPoints);
        }
        QJsonObject parameterKeyframes;
        for (const auto& [name, keyframes] : node.parameter_keyframes) {
            QJsonArray serializedKeyframes;
            for (const auto& keyframe : keyframes) {
                serializedKeyframes.push_back(QJsonObject{
                    {"sourceTimeNs", QString::number(keyframe.source_time)},
                    {"value", keyframe.value}});
            }
            parameterKeyframes.insert(QString::fromStdString(name), serializedKeyframes);
        }
        nodes.push_back(QJsonObject{
            {"id", QString::fromStdString(node.id)},
            {"name", QString::fromUtf8(node.name)},
            {"type", static_cast<int>(node.type)},
            {"enabled", node.enabled},
            {"mix", node.mix},
            {"parameters", parameters},
            {"curves", curves},
            {"parameterKeyframes", parameterKeyframes},
            {"externalPath", QString::fromUtf8(node.external_path)},
            {"sharedId", QString::fromStdString(node.shared_id)}});
    }
    return QJsonObject{{"nodes", nodes}};
}

ffgui::GradeGraph parseGradeGraph(const QJsonObject& object) {
    ffgui::GradeGraph graph;
    for (const auto value : object.value("nodes").toArray()) {
        const auto serialized = value.toObject();
        ffgui::GradeNode node;
        node.id = serialized.value("id").toString().toStdString();
        node.name = serialized.value("name").toString().toUtf8().toStdString();
        node.type = static_cast<ffgui::GradeNodeType>(
            std::clamp(serialized.value("type").toInt(), 0,
                       static_cast<int>(ffgui::GradeNodeType::power_window)));
        node.enabled = serialized.value("enabled").toBool(true);
        node.mix = serialized.value("mix").toDouble(1.0);
        node.external_path = serialized.value("externalPath").toString().toUtf8().toStdString();
        node.shared_id = serialized.value("sharedId").toString().toStdString();
        const auto parameters = serialized.value("parameters").toObject();
        for (auto it = parameters.begin(); it != parameters.end(); ++it) {
            node.parameters.emplace(it.key().toStdString(), it.value().toDouble());
        }
        const auto curves = serialized.value("curves").toObject();
        for (auto it = curves.begin(); it != curves.end(); ++it) {
            std::vector<ffgui::CurvePoint> points;
            for (const auto pointValue : it.value().toArray()) {
                const auto point = pointValue.toArray();
                if (point.size() == 2) points.push_back({point[0].toDouble(), point[1].toDouble()});
            }
            node.curves.emplace(it.key().toStdString(), std::move(points));
        }
        const auto parameterKeyframes = serialized.value("parameterKeyframes").toObject();
        for (auto it = parameterKeyframes.begin(); it != parameterKeyframes.end(); ++it) {
            std::vector<ffgui::GradeParameterKeyframe> keyframes;
            for (const auto keyframeValue : it.value().toArray()) {
                const auto keyframe = keyframeValue.toObject();
                bool validTime = false;
                const auto sourceTime = keyframe.value("sourceTimeNs")
                    .toString().toLongLong(&validTime);
                if (validTime) keyframes.push_back({sourceTime, keyframe.value("value").toDouble()});
            }
            node.parameter_keyframes.emplace(it.key().toStdString(), std::move(keyframes));
        }
        graph.add(std::move(node));
    }
    return graph;
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
    connect(this, &EditorController::playheadChanged,
            this, &EditorController::gradeUiChanged);
    connect(this, &EditorController::selectedClipChanged,
            this, &EditorController::gradeUiChanged);
    connect(this, &EditorController::timelineChanged,
            this, &EditorController::gradeUiChanged);
    QSettings settings;
    output_directory_ = settings.value(QStringLiteral("output/lastDirectory")).toString();
    if (output_directory_.isEmpty()) {
        output_directory_ = QDir(
            QStandardPaths::writableLocation(QStandardPaths::MoviesLocation))
            .filePath(QStringLiteral("ffmpegGUI Exports"));
    }
    connect(
        &import_watcher_,
        &QFutureWatcher<std::vector<PendingImport>>::finished,
        this,
        [this] {
            bool success = false;
            try {
                auto imported = import_watcher_.result();
                bool addedAsset = false;
                for (auto& item : imported) {
                    const auto assetId = item.asset.id();
                    const auto assetKey = QString::fromStdString(assetId);
                    waveform_cache_.remove(assetKey);
                    thumbnail_images_.remove(assetKey);
                    const auto duration = item.asset.duration();
                    if (!item.thumbnail_atlas.isEmpty()) {
                        thumbnail_atlases_.insert(assetKey, std::move(item.thumbnail_atlas));
                    }
                    if (item.replace_existing) {
                        timeline_.replace_asset(std::move(item.asset));
                    } else {
                        timeline_.add_asset(std::move(item.asset));
                        timeline_.append_clip(ffgui::Clip{
                            std::move(item.clip_id), assetId, 0, duration});
                        addedAsset = true;
                        if (selected_clip_id_.isEmpty()) {
                            setSingleSelection(
                                QString::fromStdString(timeline_.clips().back().id));
                        }
                    }
                }
                if (addedAsset) timeline_.clear_history();
                publishTimeline(addedAsset);
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
            if (!export_cancelled_ && !export_cpu_fallback_ &&
                export_request_.has_value() && !export_request_->gif.enabled) {
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
        if (frame.cpu_format == ffgui::PreviewCpuFormat::rgba16le) {
            QMetaObject::invokeMethod(this, [this, frame = std::move(frame)]() mutable {
                submitFloatVideoFrame(std::move(frame));
            }, Qt::QueuedConnection);
            return;
        }
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
    player_->set_scope_frame_callback([this](ffgui::PreviewVideoFrame frame) {
        bool scheduleDelivery = false;
        {
            std::scoped_lock lock(pending_scope_frame_mutex_);
            pending_scope_frame_ = std::move(frame);
            if (!scope_frame_delivery_queued_) {
                scope_frame_delivery_queued_ = true;
                scheduleDelivery = true;
            }
        }
        if (!scheduleDelivery) return;
        QMetaObject::invokeMethod(this, [this] {
            std::optional<ffgui::PreviewVideoFrame> frame;
            {
                std::scoped_lock lock(pending_scope_frame_mutex_);
                frame = std::move(pending_scope_frame_);
                pending_scope_frame_.reset();
                scope_frame_delivery_queued_ = false;
            }
            if (frame.has_value() && scopes_visible_) {
                submitScopeFrame(std::move(*frame));
            }
        }, Qt::QueuedConnection);
    });
    player_->set_scope_capture_enabled(scopes_visible_);
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
                if (state == ffgui::PlaybackState::stopped && preview_should_play_ &&
                    durationNs() > 0 && playhead_ns_ >= durationNs()) {
                    playhead_ns_ = 0;
                    emit playheadChanged();
                    pending_preview_seek_ = 0;
                    queuePreviewOperation(false);
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
    float_playback_timer_.setTimerType(Qt::PreciseTimer);
    float_playback_timer_.setInterval(8);
    connect(&float_playback_timer_, &QTimer::timeout, this, &EditorController::advanceFloatPlayback);
#ifdef FFGUI_HAS_GES
    connect(
        &preview_watcher_,
        &QFutureWatcher<PreviewOperationResult>::finished,
        this,
        [this] {
            const auto result = preview_watcher_.result();
            const bool generationAdvanced = result.generation != preview_generation_;
            const bool retryPending = preview_operation_pending_ || generationAdvanced;
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
                if (retryPending) {
                    qWarning().noquote() << "stale preview operation failed; retrying latest request:"
                                         << result.error;
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
            }

            if (retryPending) {
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
    connect(
        &float_scrub_watcher_,
        &QFutureWatcher<FloatScrubResult>::finished,
        this,
        [this] {
            auto result = float_scrub_watcher_.result();
            float_scrub_active_ = false;
            if (result.elapsed_ms >= 100 || result.requested_frame != result.resolved_frame) {
                qInfo().noquote() << "float scrub frame completed"
                                  << "elapsed_ms=" << result.elapsed_ms
                                  << "frame=" << result.requested_frame
                                  << "resolved=" << result.resolved_frame;
            }
            if (!result.error.isEmpty()) {
                qWarning().noquote() << "float scrub frame failed" << result.error;
                setStatus(result.error);
                stopFloatPlayback();
            } else if (result.generation == float_scrub_generation_) {
                auto* item = qobject_cast<VideoPreviewItem*>(video_item_);
                if (item != nullptr) {
                    auto scopeFrame = result.frame;
                    ++scrub_frames_submitted_;
                    item->submitFrame(std::move(result.frame));
                    if (scopes_visible_) submitScopeFrame(std::move(scopeFrame));
                    if (result.requested_frame != result.resolved_frame) {
                        setStatus(QStringLiteral("누락 프레임 %1 · %2 프레임으로 대체")
                            .arg(result.requested_frame).arg(result.resolved_frame));
                    } else if (!float_playback_running_) {
                        setStatus(QStringLiteral("원본 float 프레임 표시 완료"));
                    }
                }
            }
            if (pending_float_scrub_ns_.has_value()) {
                const auto next = *pending_float_scrub_ns_;
                pending_float_scrub_ns_.reset();
                startFloatScrubFrame(next);
            }
        });
    connect(
        &float_export_watcher_,
        &QFutureWatcher<FloatExportResult>::finished,
        this,
        [this] {
            const auto result = float_export_watcher_.result();
            float_export_active_ = false;
            float_export_cancel_.reset();
            if (!exporting_) return;
            if (export_log_file_ && export_log_file_->isOpen()) {
                export_log_file_->write("\n--- float frame server ---\n");
                export_log_file_->write(result.success
                    ? QByteArrayLiteral("completed\n") : result.error + '\n');
                export_log_file_->flush();
            }
            if (result.success && !export_cancelled_) {
                startExportValidation();
                return;
            }
            export_stderr_.append(result.error);
            finishExport(false);
        });
    connect(
        &float_video_watcher_,
        &QFutureWatcher<FloatVideoResult>::finished,
        this,
        [this] {
            auto result = float_video_watcher_.result();
            float_video_active_ = false;
            if (!result.error.isEmpty()) {
                qWarning().noquote() << "float video frame failed" << result.error;
                pending_float_video_frame_.reset();
                preview_should_play_ = false;
                setStatus(result.error);
                queuePreviewOperation(false);
                return;
            } else if (result.generation == preview_generation_) {
                ++float_video_frames_processed_;
                if (auto* item = qobject_cast<VideoPreviewItem*>(video_item_)) {
                    auto scopeFrame = result.frame;
                    ++video_frames_delivered_;
                    item->submitFrame(std::move(result.frame));
                    if (scopes_visible_) submitScopeFrame(std::move(scopeFrame));
                }
                if (float_video_frames_processed_ <= 2 || result.elapsed_ms >= 100) {
                    qInfo().noquote() << "float video frame completed"
                                      << "count=" << float_video_frames_processed_
                                      << "elapsed_ms=" << result.elapsed_ms;
                }
            }
            if (pending_float_video_frame_.has_value()) {
                auto next = std::move(*pending_float_video_frame_);
                pending_float_video_frame_.reset();
                startFloatVideoFrame(std::move(next));
            }
        });
    connect(
        &scope_watcher_,
        &QFutureWatcher<ScopeResult>::finished,
        this,
        [this] {
            const auto result = scope_watcher_.result();
            scope_active_ = false;
            if (result.error.isEmpty() && result.analysis != nullptr && scopes_visible_) {
                if (auto* item = qobject_cast<ColorScopeItem*>(scope_item_)) {
                    item->submitAnalysis(*result.analysis);
                    ++scope_frames_analyzed_;
                    emit scopeFrameChanged();
                }
            } else if (!result.error.isEmpty()) {
                qWarning().noquote() << "scope analysis failed:" << result.error;
            }
            if (scopes_visible_ && pending_scope_analysis_frame_.has_value()) {
                auto next = std::move(*pending_scope_analysis_frame_);
                pending_scope_analysis_frame_.reset();
                startScopeFrame(std::move(next));
            } else if (!scopes_visible_) {
                pending_scope_analysis_frame_.reset();
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
    stopFloatPlayback();
    if (float_export_cancel_) float_export_cancel_->store(true);
    if (float_export_watcher_.isRunning()) float_export_watcher_.waitForFinished();
    pending_float_video_frame_.reset();
    if (float_video_watcher_.isRunning()) float_video_watcher_.waitForFinished();
    pending_scope_analysis_frame_.reset();
    if (scope_watcher_.isRunning()) scope_watcher_.waitForFinished();
    pending_float_scrub_ns_.reset();
    ++float_scrub_generation_;
    if (float_scrub_watcher_.isRunning()) float_scrub_watcher_.waitForFinished();
    if (preview_watcher_.isRunning()) preview_watcher_.waitForFinished();
#endif
    if (import_watcher_.isRunning()) import_watcher_.waitForFinished();
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
    for (const auto& path : export_color_lut_paths_) QFile::remove(path);
}

std::uint64_t EditorController::videoFramesReceived() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->video_frames_received() : 0;
#else
    return 0;
#endif
}

std::uint64_t EditorController::sourceColorLutBindings() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->source_color_lut_bindings() : 0;
#else
    return 0;
#endif
}

std::uint64_t EditorController::sourceGpuColorLutBindings() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->source_gpu_color_lut_bindings() : 0;
#else
    return 0;
#endif
}

bool EditorController::directD3dCompositorEnabled() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ && player_->direct_d3d_compositor_enabled();
#else
    return false;
#endif
}

std::uint64_t EditorController::d3dCompositorInstances() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->d3d_compositor_instances() : 0;
#else
    return 0;
#endif
}

std::uint64_t EditorController::d3dDownloadInstances() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->d3d_download_instances() : 0;
#else
    return 0;
#endif
}

std::uint64_t EditorController::systemCompositorInstances() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->system_compositor_instances() : 0;
#else
    return 0;
#endif
}

bool EditorController::videoSurfaceExposed() const noexcept {
    const auto* item = qobject_cast<const VideoPreviewItem*>(video_item_);
    if (item != nullptr) {
        qInfo().noquote() << "video surface state"
                          << "size=" << item->width() << "x" << item->height()
                          << "visible=" << item->isVisible()
                          << "window=" << (item->window() != nullptr)
                          << "exposed=" << (item->window() != nullptr && item->window()->isExposed());
    }
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
        value.insert("name", QString::fromStdWString(span.source_path.filename().wstring()));
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
        value.insert("mediaKind", asset ? mediaKindName(asset->kind()) : QStringLiteral("video"));
        QVariantList missingFrameTimes;
        if (asset != nullptr && asset->image_sequence().has_value()) {
            const auto& sequence = asset->image_sequence().value();
            const auto frameDuration = sequence.frame_rate.frame_duration();
            for (const auto frame : sequence.missing_frames) {
                missingFrameTimes.push_back(static_cast<qint64>(
                    static_cast<long long>(frame - sequence.first_frame) * frameDuration));
            }
        }
        value.insert("missingFrameTimesNs", missingFrameTimes);
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
        QVariantList exrPartOptions;
        QVariantList exrViewOptions;
        QVariantList exrLayerOptions;
        QString exrPart;
        QString exrView;
        QString exrLayer;
        if (asset->image_sequence().has_value()) {
            const auto& sequence = asset->image_sequence().value();
            exrPart = QString::fromStdString(sequence.exr_part);
            exrView = QString::fromStdString(sequence.exr_view);
            exrLayer = QString::fromStdString(sequence.exr_layer);
            QSet<QString> seenParts;
            QSet<QString> seenViews;
            for (const auto& part : sequence.exr_parts) {
                const auto name = QString::fromStdString(part.name);
                const auto view = QString::fromStdString(part.view);
                if (!seenParts.contains(name)) {
                    exrPartOptions.push_back(QVariantMap{{"label", name}, {"value", name}});
                    seenParts.insert(name);
                }
                if (name == exrPart && !seenViews.contains(view)) {
                    exrViewOptions.push_back(QVariantMap{
                        {"label", view.isEmpty() ? QStringLiteral("기본") : view},
                        {"value", view}});
                    seenViews.insert(view);
                }
                if (name == exrPart && view == exrView) {
                    if (part.layers.empty()) {
                        exrLayerOptions.push_back(QVariantMap{
                            {"label", QStringLiteral("RGBA")}, {"value", QString{}}});
                    } else {
                        for (const auto& layer : part.layers) {
                            const auto value = QString::fromStdString(layer);
                            exrLayerOptions.push_back(QVariantMap{{"label", value}, {"value", value}});
                        }
                    }
                }
            }
        }
        int useCount = 0;
        for (const auto& clip : timeline_.clips()) {
            if (clip.asset_id == asset->id()) ++useCount;
        }
        result.push_back(QVariantMap{
            {"id", id},
            {"name", file.completeBaseName()},
            {"path", file.absoluteFilePath()},
            {"durationNs", static_cast<qint64>(asset->duration())},
            {"kind", mediaKindName(asset->kind())},
            {"colorSpace", QString::fromStdString(asset->source_color().input_color_space)},
            {"colorUnresolved", asset->source_color().unresolved},
            {"missingFrameCount", asset->image_sequence().has_value()
                ? static_cast<int>(asset->image_sequence()->missing_frames.size()) : 0},
            {"sequenceRange", asset->image_sequence().has_value()
                ? QStringLiteral("%1–%2").arg(asset->image_sequence()->first_frame)
                    .arg(asset->image_sequence()->last_frame) : QString{}},
            {"exrPart", exrPart},
            {"exrView", exrView},
            {"exrLayer", exrLayer},
            {"exrPartOptions", exrPartOptions},
            {"exrViewOptions", exrViewOptions},
            {"exrLayerOptions", exrLayerOptions},
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

int EditorController::missingFrameCount() const {
    int result = 0;
    for (const auto& clip : timeline_.clips()) {
        const auto* asset = timeline_.asset(clip.asset_id);
        if (asset == nullptr || !asset->image_sequence().has_value()) continue;
        const auto& sequence = asset->image_sequence().value();
        const auto frameDuration = sequence.frame_rate.frame_duration();
        for (const auto frame : sequence.missing_frames) {
            const auto sourceTime = static_cast<ffgui::TimeNs>(
                static_cast<long long>(frame - sequence.first_frame) * frameDuration);
            if (sourceTime >= clip.source_in && sourceTime < clip.source_out()) ++result;
        }
    }
    return result;
}

std::optional<ffgui::TimeNs> EditorController::selectedClipSourceTime() const {
    if (selected_clip_id_.isEmpty()) return std::nullopt;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto spans = timeline_.snapshot();
    const auto span = std::ranges::find_if(spans, [&selectedId](const auto& value) {
        return value.clip.id == selectedId;
    });
    if (span == spans.end()) return std::nullopt;
    const auto local = std::clamp<ffgui::TimeNs>(
        playhead_ns_ - span->timeline_in, 0,
        std::max<ffgui::TimeNs>(0, span->clip.timeline_duration() - 1));
    return ffgui::checked_add(
        span->clip.source_in, span->clip.source_offset_for_timeline(local));
}

QVariantList EditorController::selectedGradeNodes() const {
    QVariantList result;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return result;
    const auto* asset = timeline_.asset(clip->asset_id);
    const auto keyframeSupported = asset != nullptr && asset->image_sequence().has_value();
    const auto sourceTime = selectedClipSourceTime().value_or(clip->source_in);
    for (const auto& node : clip->grade.nodes()) {
        QVariantMap parameters;
        for (const auto& [name, value] : node.parameters) {
            parameters.insert(QString::fromStdString(name),
                ffgui::evaluate_grade_parameter(node, name, value, sourceTime));
        }
        QStringList keyframedParameters;
        QStringList keyframesAtPlayhead;
        for (const auto& [name, keyframes] : node.parameter_keyframes) {
            if (keyframes.empty()) continue;
            const auto qName = QString::fromStdString(name);
            keyframedParameters.push_back(qName);
            if (std::ranges::any_of(keyframes, [sourceTime](const auto& keyframe) {
                    return keyframe.source_time == sourceTime;
                })) {
                keyframesAtPlayhead.push_back(qName);
            }
        }
        QVariantMap curveMidpoints;
        for (const auto& [name, points] : node.curves) {
            auto midpoint = 0.5;
            if (!points.empty()) {
                if (0.5 <= points.front().x) midpoint = points.front().y;
                else if (0.5 >= points.back().x) midpoint = points.back().y;
                else {
                    const auto upper = std::upper_bound(
                        points.begin(), points.end(), 0.5,
                        [](double value, const ffgui::CurvePoint& point) {
                            return value < point.x;
                        });
                    const auto& right = *upper;
                    const auto& left = *(upper - 1);
                    const auto amount = (0.5 - left.x) / (right.x - left.x);
                    midpoint = std::lerp(left.y, right.y, amount);
                }
            }
            curveMidpoints.insert(
                QString::fromStdString(name),
                static_cast<int>(std::lround((midpoint - 0.5) * 200.0)));
        }
        result.push_back(QVariantMap{
            {"id", QString::fromStdString(node.id)},
            {"name", QString::fromUtf8(node.name)},
            {"type", static_cast<int>(node.type)},
            {"enabled", node.enabled},
            {"mixPercent", static_cast<int>(std::lround(node.mix * 100.0))},
            {"parameters", parameters},
            {"parameterNames", parameters.keys()},
            {"keyframedParameters", keyframedParameters},
            {"keyframesAtPlayhead", keyframesAtPlayhead},
            {"keyframeSupported", keyframeSupported},
            {"shared", !node.shared_id.empty()},
            {"sharedId", QString::fromStdString(node.shared_id)},
            {"curveMidpoints", curveMidpoints},
            {"externalPath", QString::fromUtf8(node.external_path)},
            {"externalFileName", node.external_path.empty()
                ? QString{} : QFileInfo(QString::fromUtf8(node.external_path)).fileName()},
            {"lutRepresentable", node.lut_representable()}});
    }
    return result;
}

void EditorController::addGradeNode(int type) {
    if (selected_clip_id_.isEmpty()) return;
    type = std::clamp(type, 0, static_cast<int>(ffgui::GradeNodeType::color_warper));
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    try {
        auto graph = clip->grade;
        graph.add(ffgui::make_default_grade_node(
            static_cast<ffgui::GradeNodeType>(type),
            makeUniqueGradeNodeId()));
        timeline_.set_clip_grade_graph(selectedId, std::move(graph));
        publishTimeline();
        setStatus("컬러 노드를 추가했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::commitGradeNodeEdit(
    const std::string& clip_id, ffgui::GradeGraph graph, const std::string& node_id) {
    const auto* node = graph.node(node_id);
    if (node == nullptr) throw std::out_of_range("grade node was not found");
    if (node->shared_id.empty()) {
        timeline_.set_clip_grade_graph(clip_id, std::move(graph));
    } else {
        timeline_.set_shared_grade_node(node->shared_id, *node);
    }
    publishTimeline();
}

void EditorController::addGradeLutUrl(const QUrl& url) {
    if (selected_clip_id_.isEmpty() || !url.isLocalFile()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    const auto localPath = QDir::toNativeSeparators(url.toLocalFile());
    const auto utf8Path = localPath.toUtf8().toStdString();
    try {
        ffgui::validate_grade_lut_file(utf8Path);
        auto graph = clip->grade;
        auto node = ffgui::make_default_grade_node(
            ffgui::GradeNodeType::lut,
            makeUniqueGradeNodeId());
        node.external_path = utf8Path;
        const auto displayName = QFileInfo(localPath).completeBaseName().trimmed();
        node.name = displayName.isEmpty()
            ? ffgui::grade_node_type_name(ffgui::GradeNodeType::lut)
            : "LUT · " + displayName.toUtf8().toStdString();
        graph.add(std::move(node));
        timeline_.set_clip_grade_graph(selectedId, std::move(graph));
        publishTimeline();
        setStatus("LUT / Look을 검증하고 컬러 노드에 추가했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::removeGradeNode(const QString& nodeId) {
    if (selected_clip_id_.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    try {
        auto graph = clip->grade;
        graph.remove(nodeId.toStdString());
        timeline_.set_clip_grade_graph(selectedId, std::move(graph));
        publishTimeline();
        setStatus("컬러 노드를 삭제했습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::moveGradeNode(const QString& nodeId, int direction) {
    if (selected_clip_id_.isEmpty() || direction == 0) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    const auto& nodes = graph.nodes();
    const auto found = std::ranges::find(nodes, nodeId.toStdString(), &ffgui::GradeNode::id);
    if (found == nodes.end()) return;
    const auto index = static_cast<int>(std::distance(nodes.begin(), found));
    const auto target = std::clamp(index + direction, 0, static_cast<int>(nodes.size()) - 1);
    if (target == index) return;
    graph.move(nodeId.toStdString(), direction > 0
        ? static_cast<std::size_t>(target + 1) : static_cast<std::size_t>(target));
    timeline_.set_clip_grade_graph(selectedId, std::move(graph));
    publishTimeline();
}

void EditorController::copyGradeNode(const QString& nodeId) {
    if (selected_clip_id_.isEmpty()) return;
    const auto clip = std::ranges::find(
        timeline_.clips(), selected_clip_id_.toStdString(), &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    const auto* node = clip->grade.node(nodeId.toStdString());
    if (node == nullptr) return;
    grade_node_clipboard_ = *node;
    grade_clipboard_source_clip_id_ = selected_clip_id_;
    emit gradeClipboardChanged();
    setStatus("컬러 노드를 복사했습니다");
}

void EditorController::pasteGradeNode() {
    if (selected_clip_id_.isEmpty() || !grade_node_clipboard_.has_value()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    try {
        auto graph = clip->grade;
        auto node = grade_node_clipboard_.value();
        node.id = makeUniqueGradeNodeId();
        if (grade_clipboard_source_clip_id_ == selected_clip_id_) node.shared_id.clear();
        if (node.shared_id.empty()) node.name += " 복사";
        node.validate();
        graph.add(std::move(node));
        timeline_.set_clip_grade_graph(selectedId, std::move(graph));
        publishTimeline();
        setStatus("복사한 컬러 노드를 붙여넣었습니다");
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::resetGradeNode(const QString& nodeId) {
    if (selected_clip_id_.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* current = graph.node(nodeId.toStdString());
    if (current == nullptr) return;
    const auto original = *current;
    auto replacement = ffgui::make_default_grade_node(original.type, original.id);
    replacement.name = original.name;
    replacement.shared_id = original.shared_id;
    if (original.type == ffgui::GradeNodeType::lut) {
        replacement.external_path = original.external_path;
    }
    if (replacement == original) return;
    *current = std::move(replacement);
    commitGradeNodeEdit(selectedId, std::move(graph), nodeId.toStdString());
    setStatus("컬러 노드를 기본값으로 초기화했습니다");
}

void EditorController::makeGradeNodeShared(const QString& nodeId) {
    if (selected_clip_id_.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    if (node == nullptr || !node->shared_id.empty()) return;
    node->shared_id = makeUniqueSharedGradeId();
    timeline_.set_clip_grade_graph(selectedId, std::move(graph));
    publishTimeline();
    setStatus("공유 그레이드로 전환했습니다. 다른 클립에 복사해 연결할 수 있습니다");
}

void EditorController::unlinkGradeNode(const QString& nodeId) {
    if (selected_clip_id_.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    if (node == nullptr || node->shared_id.empty()) return;
    node->shared_id.clear();
    timeline_.set_clip_grade_graph(selectedId, std::move(graph));
    publishTimeline();
    setStatus("이 노드를 공유 그레이드에서 분리했습니다");
}

void EditorController::setGradeNodeEnabled(const QString& nodeId, bool enabled) {
    if (selected_clip_id_.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    if (node == nullptr || node->enabled == enabled) return;
    node->enabled = enabled;
    commitGradeNodeEdit(selectedId, std::move(graph), nodeId.toStdString());
}

void EditorController::setGradeNodeName(const QString& nodeId, const QString& name) {
    if (selected_clip_id_.isEmpty()) return;
    const auto cleaned = name.simplified().left(80);
    if (cleaned.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    const auto utf8Name = cleaned.toUtf8().toStdString();
    if (node == nullptr || node->name == utf8Name) return;
    node->name = utf8Name;
    node->validate();
    commitGradeNodeEdit(selectedId, std::move(graph), nodeId.toStdString());
}

void EditorController::setGradeNodeMix(const QString& nodeId, int percent) {
    if (selected_clip_id_.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    const auto mix = std::clamp(percent, 0, 100) / 100.0;
    if (node == nullptr || node->mix == mix) return;
    node->mix = mix;
    commitGradeNodeEdit(selectedId, std::move(graph), nodeId.toStdString());
}

void EditorController::setGradeParameter(
    const QString& nodeId, const QString& parameter, double value) {
    if (selected_clip_id_.isEmpty() || parameter.isEmpty() || !std::isfinite(value)) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    if (node == nullptr) return;
    const auto key = parameter.toStdString();
    if (!node->parameters.contains(key)) return;
    const auto sourceTime = selectedClipSourceTime();
    auto& keyframes = node->parameter_keyframes[key];
    const bool editsAnimation = !keyframes.empty() && sourceTime.has_value();
    if (editsAnimation) {
        const auto found = std::ranges::lower_bound(
            keyframes, *sourceTime, {}, &ffgui::GradeParameterKeyframe::source_time);
        if (found != keyframes.end() && found->source_time == *sourceTime) {
            if (found->value == value) return;
            found->value = value;
        } else {
            keyframes.insert(found, {*sourceTime, value});
        }
    } else {
        node->parameter_keyframes.erase(key);
        if (node->parameters[key] == value) return;
        node->parameters[key] = value;
    }
    node->validate();
    if (editsAnimation) {
        timeline_.set_clip_grade_graph(selectedId, std::move(graph));
        publishTimeline();
    } else {
        commitGradeNodeEdit(selectedId, std::move(graph), nodeId.toStdString());
    }
}

void EditorController::toggleGradeParameterKeyframe(
    const QString& nodeId, const QString& parameterName) {
    const auto sourceTime = selectedClipSourceTime();
    if (selected_clip_id_.isEmpty() || parameterName.isEmpty() || !sourceTime.has_value()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    const auto key = parameterName.toStdString();
    if (node == nullptr || !node->parameters.contains(key)) return;
    auto& keyframes = node->parameter_keyframes[key];
    const auto found = std::ranges::lower_bound(
        keyframes, *sourceTime, {}, &ffgui::GradeParameterKeyframe::source_time);
    if (found != keyframes.end() && found->source_time == *sourceTime) {
        keyframes.erase(found);
        if (keyframes.empty()) node->parameter_keyframes.erase(key);
    } else {
        const auto value = ffgui::evaluate_grade_parameter(
            *node, key, node->parameters.at(key), *sourceTime);
        keyframes.insert(found, {*sourceTime, value});
    }
    node->validate();
    timeline_.set_clip_grade_graph(selectedId, std::move(graph));
    publishTimeline();
}

void EditorController::setGradeCurveMidpoint(
    const QString& nodeId, const QString& curveName, int adjustmentPercent) {
    if (selected_clip_id_.isEmpty() || curveName.isEmpty()) return;
    const auto selectedId = selected_clip_id_.toStdString();
    const auto clip = std::ranges::find(timeline_.clips(), selectedId, &ffgui::Clip::id);
    if (clip == timeline_.clips().end()) return;
    auto graph = clip->grade;
    auto* node = graph.node(nodeId.toStdString());
    if (node == nullptr) return;
    const auto key = curveName.toStdString();
    if (!node->curves.contains(key)) return;
    const auto adjustment = std::clamp(adjustmentPercent, -100, 100);
    const auto midpoint = 0.5 + adjustment / 200.0;
    const std::vector<ffgui::CurvePoint> replacement{
        {0.0, 0.0}, {0.5, midpoint}, {1.0, 1.0}};
    if (node->curves[key] == replacement) return;
    node->curves[key] = replacement;
    node->validate();
    commitGradeNodeEdit(selectedId, std::move(graph), nodeId.toStdString());
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

void EditorController::attachScopeItem(QObject* item) {
    auto* scopeItem = qobject_cast<ColorScopeItem*>(item);
    if (scopeItem == nullptr) {
        setStatus(QStringLiteral("컬러 스코프 화면을 연결할 수 없습니다"));
        return;
    }
    scope_item_ = scopeItem;
    scopeItem->setMode(scope_mode_);
}

void EditorController::setScopesVisible(bool visible) {
    if (scopes_visible_ == visible) return;
    scopes_visible_ = visible;
#ifdef FFGUI_HAS_GES
    player_->set_scope_capture_enabled(visible);
    if (!visible) {
        pending_scope_analysis_frame_.reset();
    } else if (!timeline_.clips().empty()) {
        pending_preview_seek_ = playhead_ns_;
        queuePreviewOperation(false);
    }
#endif
    emit scopeSettingsChanged();
}

void EditorController::setScopeMode(int mode) {
    const auto clamped = std::clamp(mode, 0, 3);
    if (scope_mode_ == clamped) return;
    scope_mode_ = clamped;
    if (auto* item = qobject_cast<ColorScopeItem*>(scope_item_)) item->setMode(scope_mode_);
    emit scopeSettingsChanged();
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
            std::optional<ffgui::ImageSequenceDescriptor> sequence;
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
                info.absoluteFilePath(), std::move(assetId), makeUniqueClipId("clip"),
                std::nullopt});
        }
        if (requests.empty()) {
            return;
        }
        const auto ffprobe = ffgui::locate_ffprobe();
        const auto ffmpeg = ffgui::locate_ffmpeg();
        importing_ = true;
        emit importingChanged();
        setStatus(QString("미디어 준비 중 · %1개 선택").arg(requests.size()));
        import_watcher_.setFuture(QtConcurrent::run(
            [ffprobe, ffmpeg, requests = std::move(requests)]() mutable {
                std::vector<PendingImport> result;
                result.reserve(requests.size());
                QSet<QString> scheduledSequences;
                for (auto& request : requests) {
                    request.sequence = ffgui::detect_image_sequence(
                        std::filesystem::path(request.path.toStdWString()), {24, 1});
                    if (request.sequence.has_value()) {
                        const auto& sequence = request.sequence.value();
                        const auto sequenceKey = QStringLiteral("%1|%2|%3|%4")
                            .arg(QString::fromStdWString(sequence.directory.wstring()),
                                 QString::fromStdString(sequence.prefix),
                                 QString::fromStdString(sequence.suffix))
                            .arg(sequence.padding);
                        if (scheduledSequences.contains(sequenceKey)) continue;
                        scheduledSequences.insert(sequenceKey);
                    }
                    const auto clipId = std::move(request.clip_id);
                    auto analyzed = ffgui::analyze_media_source(
                        ffprobe, ffmpeg, request.path, std::move(request.asset_id),
                        std::move(request.sequence));
                    result.push_back(PendingImport{
                        std::move(analyzed.asset),
                        clipId,
                        std::move(analyzed.thumbnail_atlas),
                        false});
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

void EditorController::updateExrSelection(
    const QString& assetId,
    const QString& part,
    const QString& view,
    const QString& layer) {
    if (importing_) {
        setStatus("현재 미디어 작업이 끝난 후 EXR 선택을 변경하세요");
        return;
    }
    const auto* asset = timeline_.asset(assetId.toStdString());
    if (asset == nullptr || !asset->image_sequence().has_value() ||
        asset->image_sequence()->exr_parts.empty()) {
        setStatus("선택 가능한 EXR 시퀀스가 아닙니다");
        return;
    }
    auto sequence = asset->image_sequence().value();
    const auto requestedPart = part.toStdString();
    const auto requestedView = view.toStdString();
    const auto requestedLayer = layer.toStdString();
    const auto option = std::ranges::find_if(sequence.exr_parts, [&](const auto& candidate) {
        return candidate.name == requestedPart &&
            (requestedView.empty() || candidate.view == requestedView);
    });
    if (option == sequence.exr_parts.end()) {
        setStatus("EXR part/view 조합을 찾을 수 없습니다");
        return;
    }
    if (!requestedLayer.empty() &&
        std::ranges::find(option->layers, requestedLayer) == option->layers.end()) {
        setStatus("선택한 EXR part에 해당 AOV 레이어가 없습니다");
        return;
    }
    sequence.exr_part = requestedPart;
    sequence.exr_view = option->view;
    sequence.exr_layer = requestedLayer;
    const auto sourcePath = QString::fromStdWString(asset->path().wstring());
    const auto ffprobe = ffgui::locate_ffprobe();
    const auto ffmpeg = ffgui::locate_ffmpeg();
    importing_ = true;
    emit importingChanged();
    setStatus(QStringLiteral("EXR AOV 준비 중 · %1%2")
        .arg(part, requestedLayer.empty() ? QString{} : QStringLiteral(" / ") + layer));
    import_watcher_.setFuture(QtConcurrent::run(
        [ffprobe, ffmpeg, sourcePath, assetId, sequence = std::move(sequence)]() mutable {
            auto analyzed = ffgui::analyze_media_source(
                ffprobe, ffmpeg, sourcePath, assetId.toStdString(), std::move(sequence));
            std::vector<PendingImport> result;
            result.push_back(PendingImport{
                std::move(analyzed.asset), {}, std::move(analyzed.thumbnail_atlas), true});
            return result;
        }));
}

void EditorController::setAssetInputColorSpace(
    const QString& assetId, const QString& colorSpace) {
    const auto id = assetId.trimmed().toStdString();
    const auto requested = colorSpace.trimmed().toStdString();
    const auto* asset = timeline_.asset(id);
    if (asset == nullptr || requested.empty()) {
        setStatus(QStringLiteral("입력 색공간을 선택하세요"));
        return;
    }
    try {
        auto validationSettings = color_pipeline_;
        if (validationSettings.mode == ffgui::ColorPipelineMode::legacy) {
            validationSettings.mode = ffgui::ColorPipelineMode::aces_managed;
        }
        const auto spaces = ffgui::OcioEngine(validationSettings).color_spaces();
        if (std::ranges::find(spaces, requested) == spaces.end()) {
            setStatus(QStringLiteral("현재 OCIO 설정에 없는 색공간입니다 · %1")
                .arg(QString::fromStdString(requested)));
            return;
        }
        auto replacement = *asset;
        auto descriptor = replacement.source_color();
        descriptor.input_color_space = requested;
        descriptor.unresolved = false;
        replacement.set_source_color(std::move(descriptor));
        timeline_.replace_asset(std::move(replacement));
        publishTimeline(false);
        setStatus(QStringLiteral("입력 색공간 지정 · %1")
            .arg(QString::fromStdString(requested)));
    } catch (const std::exception& error) {
        setStatus(QStringLiteral("입력 색공간을 적용할 수 없습니다 · %1")
            .arg(QString::fromUtf8(error.what())));
    }
}

void EditorController::seek(qint64 timelinePosition) {
    stopFloatPlayback();
    playhead_ns_ = std::clamp<qint64>(timelinePosition, 0, durationNs());
    emit playheadChanged();
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
    if (submitFloatScrubFrame(playhead_ns_)) return;
    pending_preview_seek_ = playhead_ns_;
    queuePreviewOperation(false);
#endif
}

void EditorController::scrub(qint64 timelinePosition, bool finalPosition) {
    stopFloatPlayback();
    playhead_ns_ = std::clamp<qint64>(timelinePosition, 0, durationNs());
    emit playheadChanged();
    const auto floatSubmitted = submitFloatScrubFrame(playhead_ns_);
    if (!floatSubmitted) submitCachedScrubFrame(playhead_ns_);
#ifdef FFGUI_HAS_GES
    preview_should_play_ = false;
    if (!finalPosition || floatSubmitted) return;
    pending_preview_seek_ = playhead_ns_;
    queuePreviewOperation(false);
#else
    static_cast<void>(finalPosition);
#endif
}

bool EditorController::submitFloatScrubFrame(qint64 timelinePosition) {
#ifdef FFGUI_HAS_GES
    if (video_item_ == nullptr) return false;
    const auto mapped = timeline_.locate(timelinePosition);
    if (!mapped.has_value()) return false;
    const auto* asset = timeline_.asset(mapped->asset_id);
    if (asset == nullptr || !asset->image_sequence().has_value()) return false;
    if (float_scrub_active_) {
        pending_float_scrub_ns_ = timelinePosition;
    } else {
        startFloatScrubFrame(timelinePosition);
    }
    return true;
#else
    static_cast<void>(timelinePosition);
    return false;
#endif
}

void EditorController::startFloatScrubFrame(qint64 timelinePosition) {
#ifdef FFGUI_HAS_GES
    const auto mapped = timeline_.locate(timelinePosition);
    if (!mapped.has_value()) return;
    const auto* asset = timeline_.asset(mapped->asset_id);
    if (asset == nullptr || !asset->image_sequence().has_value()) return;
    const auto timeline = timeline_;
    const auto settings = color_pipeline_;
    const auto outputSpace = settings.mode == ffgui::ColorPipelineMode::legacy
        ? std::string{}
        : settings.output_space.empty() ? std::string{"sRGB - Display"} : settings.output_space;
    const auto generation = ++float_scrub_generation_;
    float_scrub_active_ = true;
    float_scrub_watcher_.setFuture(QtConcurrent::run(
        [this, timeline, settings, outputSpace, timelinePosition, generation] {
            FloatScrubResult result;
            result.generation = generation;
            QElapsedTimer elapsed;
            elapsed.start();
            try {
                auto rendered = timeline_frame_server_.render(
                    timeline, timelinePosition, settings, outputSpace);
                result.requested_frame = rendered.requested_sequence_frame;
                result.resolved_frame = rendered.resolved_sequence_frame;
                const auto& processed = rendered.processed;
                result.frame.width = static_cast<std::uint32_t>(processed.width);
                result.frame.height = static_cast<std::uint32_t>(processed.height);
                result.frame.cpu_stride = result.frame.width * 4;
                result.frame.cpu_pixels = std::make_shared<std::vector<std::uint8_t>>(
                    static_cast<std::size_t>(result.frame.cpu_stride) * result.frame.height);
                const auto pixels = static_cast<std::size_t>(processed.width) * processed.height;
                for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
                    const auto* rgba = processed.rgba.data() + pixel * 4;
                    auto alpha = std::clamp(std::isfinite(rgba[3]) ? rgba[3] : 0.0F, 0.0F, 1.0F);
                    auto red = std::isfinite(rgba[0]) ? rgba[0] : 0.0F;
                    auto green = std::isfinite(rgba[1]) ? rgba[1] : 0.0F;
                    auto blue = std::isfinite(rgba[2]) ? rgba[2] : 0.0F;
                    if (processed.premultiplied && alpha > 0.0F) {
                        red /= alpha; green /= alpha; blue /= alpha;
                    }
                    auto* bgra = result.frame.cpu_pixels->data() + pixel * 4;
                    bgra[0] = static_cast<std::uint8_t>(std::lround(std::clamp(blue, 0.0F, 1.0F) * 255.0F));
                    bgra[1] = static_cast<std::uint8_t>(std::lround(std::clamp(green, 0.0F, 1.0F) * 255.0F));
                    bgra[2] = static_cast<std::uint8_t>(std::lround(std::clamp(red, 0.0F, 1.0F) * 255.0F));
                    bgra[3] = static_cast<std::uint8_t>(std::lround(alpha * 255.0F));
                }
                result.frame.pts = timelinePosition;
                result.frame.serial = (1ULL << 62) + generation;
            } catch (const std::exception& error) {
                result.error = QStringLiteral("float 미리보기 실패: %1")
                    .arg(QString::fromUtf8(error.what()));
            }
            result.elapsed_ms = elapsed.elapsed();
            return result;
        }));
#else
    static_cast<void>(timelinePosition);
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
    if (float_playback_running_) {
        stopFloatPlayback();
        setStatus(QStringLiteral("일시 정지"));
        return;
    }
    if (canUseFloatPlayback()) {
        startFloatPlayback();
        return;
    }
    preview_should_play_ = !(preview_should_play_ || playing_);
    if (preview_should_play_ && playhead_ns_ >= durationNs()) {
        playhead_ns_ = 0;
        emit playheadChanged();
    }
    if (preview_should_play_) pending_preview_seek_ = playhead_ns_;
    queuePreviewOperation(false);
#endif
}

bool EditorController::canUseFloatPlayback() const {
#ifdef FFGUI_HAS_GES
    if (video_item_ == nullptr || timeline_.clips().empty()) return false;
    return std::ranges::all_of(timeline_.clips(), [this](const auto& clip) {
        const auto* asset = timeline_.asset(clip.asset_id);
        return asset != nullptr && asset->image_sequence().has_value();
    });
#else
    return false;
#endif
}

void EditorController::startFloatPlayback() {
#ifdef FFGUI_HAS_GES
    if (!canUseFloatPlayback() || durationNs() <= 0) return;
    preview_should_play_ = false;
    if (playhead_ns_ >= durationNs()) {
        playhead_ns_ = 0;
        emit playheadChanged();
    }
    float_playback_origin_ns_ = playhead_ns_;
    float_playback_clock_.restart();
    float_playback_running_ = true;
    if (!playing_) {
        playing_ = true;
        emit playingChanged();
    }
    setStatus(QStringLiteral("재생 중 · float 프레임"));
    submitFloatScrubFrame(playhead_ns_);
    float_playback_timer_.start();
#endif
}

void EditorController::stopFloatPlayback(bool rewindAtEnd) {
    if (!float_playback_running_) return;
    float_playback_timer_.stop();
    float_playback_running_ = false;
    pending_float_scrub_ns_.reset();
    if (playing_) {
        playing_ = false;
        emit playingChanged();
    }
    if (rewindAtEnd) {
        playhead_ns_ = 0;
        emit playheadChanged();
        submitFloatScrubFrame(playhead_ns_);
    }
}

void EditorController::advanceFloatPlayback() {
#ifdef FFGUI_HAS_GES
    if (!float_playback_running_) return;
    const auto elapsedNs = float_playback_clock_.nsecsElapsed();
    const auto target = std::min<qint64>(
        durationNs(), float_playback_origin_ns_ + elapsedNs);
    if (target != playhead_ns_) {
        playhead_ns_ = target;
        emit playheadChanged();
    }
    if (target >= durationNs()) {
        stopFloatPlayback(true);
        setStatus(QStringLiteral("재생 완료 · 처음으로 이동"));
        return;
    }
    submitFloatScrubFrame(target);
#endif
}

bool EditorController::requiresFloatVideoPreview() const {
#ifdef FFGUI_HAS_GES
    // Ordinary video and mixed timelines apply their clip LUT inside each GES source,
    // before alpha composition. The composited appsink must therefore stay on its normal
    // BGRA/D3D11 path instead of grading the already blended frame a second time.
    return false;
#else
    return false;
#endif
}

void EditorController::submitFloatVideoFrame(ffgui::PreviewVideoFrame frame) {
#ifdef FFGUI_HAS_GES
    if (frame.cpu_format != ffgui::PreviewCpuFormat::rgba16le ||
        frame.cpu_pixels == nullptr) return;
    if (float_video_active_) {
        pending_float_video_frame_ = std::move(frame);
    } else {
        startFloatVideoFrame(std::move(frame));
    }
#else
    static_cast<void>(frame);
#endif
}

void EditorController::startFloatVideoFrame(ffgui::PreviewVideoFrame frame) {
#ifdef FFGUI_HAS_GES
    const auto mapped = timeline_.locate(frame.pts);
    if (!mapped.has_value()) return;
    const auto clip = std::ranges::find(timeline_.clips(), mapped->clip_id, &ffgui::Clip::id);
    const auto* asset = timeline_.asset(mapped->asset_id);
    if (clip == timeline_.clips().end() || asset == nullptr) return;
    const auto sourceColor = asset->source_color();
    const auto settings = color_pipeline_;
    const auto grade = color_pipeline_.mode == ffgui::ColorPipelineMode::legacy
        ? clip->grade : ffgui::compose_clip_grade(*clip);
    const auto outputSpace = settings.mode == ffgui::ColorPipelineMode::legacy
        ? std::string{}
        : settings.output_space.empty() ? std::string{"sRGB - Display"} : settings.output_space;
    const auto generation = preview_generation_;
    const auto sourceTime = mapped->source_time;
    float_video_active_ = true;
    float_video_watcher_.setFuture(QtConcurrent::run(
        [frame = std::move(frame), sourceColor, settings, grade, outputSpace, generation,
         sourceTime]() mutable {
            FloatVideoResult result;
            result.generation = generation;
            QElapsedTimer elapsed;
            elapsed.start();
            try {
                const auto expected = static_cast<std::size_t>(frame.cpu_stride) * frame.height;
                if (frame.width == 0 || frame.height == 0 || frame.cpu_stride < frame.width * 8 ||
                    frame.cpu_pixels->size() < expected) {
                    throw std::invalid_argument("16-bit preview frame storage is invalid");
                }
                ffgui::FloatImageFrame source;
                source.width = static_cast<int>(frame.width);
                source.height = static_cast<int>(frame.height);
                source.color_space = sourceColor.input_color_space;
                source.rgba.resize(static_cast<std::size_t>(frame.width) * frame.height * 4);
                for (std::uint32_t row = 0; row < frame.height; ++row) {
                    const auto* input = reinterpret_cast<const std::uint16_t*>(
                        frame.cpu_pixels->data() + static_cast<std::size_t>(row) * frame.cpu_stride);
                    for (std::uint32_t column = 0; column < frame.width; ++column) {
                        const auto sourceIndex = static_cast<std::size_t>(column) * 4;
                        const auto targetIndex =
                            (static_cast<std::size_t>(row) * frame.width + column) * 4;
                        for (std::size_t channel = 0; channel < 4; ++channel) {
                            source.rgba[targetIndex + channel] =
                                static_cast<float>(input[sourceIndex + channel]) / 65535.0F;
                        }
                    }
                }
                const auto processed = ffgui::process_color_frame(
                    source, sourceColor, settings, grade, outputSpace, sourceTime);
                auto pixels = std::make_shared<std::vector<std::uint8_t>>(
                    static_cast<std::size_t>(frame.width) * frame.height * 4);
                const auto pixelCount = static_cast<std::size_t>(frame.width) * frame.height;
                for (std::size_t pixel = 0; pixel < pixelCount; ++pixel) {
                    const auto* rgba = processed.rgba.data() + pixel * 4;
                    auto* bgra = pixels->data() + pixel * 4;
                    bgra[0] = static_cast<std::uint8_t>(std::lround(
                        std::clamp(std::isfinite(rgba[2]) ? rgba[2] : 0.0F, 0.0F, 1.0F) * 255.0F));
                    bgra[1] = static_cast<std::uint8_t>(std::lround(
                        std::clamp(std::isfinite(rgba[1]) ? rgba[1] : 0.0F, 0.0F, 1.0F) * 255.0F));
                    bgra[2] = static_cast<std::uint8_t>(std::lround(
                        std::clamp(std::isfinite(rgba[0]) ? rgba[0] : 0.0F, 0.0F, 1.0F) * 255.0F));
                    bgra[3] = static_cast<std::uint8_t>(std::lround(
                        std::clamp(std::isfinite(rgba[3]) ? rgba[3] : 1.0F, 0.0F, 1.0F) * 255.0F));
                }
                frame.cpu_pixels = std::move(pixels);
                frame.cpu_stride = frame.width * 4;
                frame.cpu_format = ffgui::PreviewCpuFormat::bgra8;
                frame.sample.reset();
                result.frame = std::move(frame);
            } catch (const std::exception& error) {
                result.error = QStringLiteral("float 영상 미리보기 실패: %1")
                    .arg(QString::fromUtf8(error.what()));
            }
            result.elapsed_ms = elapsed.elapsed();
            return result;
        }));
#else
    static_cast<void>(frame);
#endif
}

void EditorController::submitScopeFrame(ffgui::PreviewVideoFrame frame) {
#ifdef FFGUI_HAS_GES
    const bool cpuFrame = frame.cpu_format == ffgui::PreviewCpuFormat::bgra8 &&
        frame.cpu_pixels != nullptr && frame.width > 0 && frame.height > 0 &&
        frame.cpu_stride >= frame.width * 4;
    if (!cpuFrame && frame.sample == nullptr) return;
    if (scope_active_) {
        pending_scope_analysis_frame_ = std::move(frame);
    } else {
        startScopeFrame(std::move(frame));
    }
#else
    static_cast<void>(frame);
#endif
}

void EditorController::startScopeFrame(ffgui::PreviewVideoFrame frame) {
#ifdef FFGUI_HAS_GES
    scope_active_ = true;
    scope_watcher_.setFuture(QtConcurrent::run([frame = std::move(frame)]() mutable {
        ScopeResult result;
        try {
            if (frame.cpu_pixels != nullptr) {
                const auto expected = static_cast<std::size_t>(frame.cpu_stride) * frame.height;
                if (frame.cpu_pixels->size() < expected) {
                    throw std::invalid_argument("scope frame storage is invalid");
                }
                result.analysis = std::make_shared<ffgui::ScopeAnalysis>(
                    ffgui::analyze_scope_bgra8(
                        frame.cpu_pixels->data(), frame.width, frame.height, frame.cpu_stride,
                        frame.serial, ffgui::ScopeReferenceStage::post_display));
            } else {
                auto* sample = static_cast<GstSample*>(frame.sample.get());
                auto* buffer = sample != nullptr ? gst_sample_get_buffer(sample) : nullptr;
                auto* caps = sample != nullptr ? gst_sample_get_caps(sample) : nullptr;
                GstVideoInfo info{};
                if (buffer == nullptr || caps == nullptr ||
                    !gst_video_info_from_caps(&info, caps)) {
                    throw std::invalid_argument("scope GPU sample has invalid video metadata");
                }
                const auto format = GST_VIDEO_INFO_FORMAT(&info);
                if (format != GST_VIDEO_FORMAT_RGBA && format != GST_VIDEO_FORMAT_BGRA) {
                    throw std::invalid_argument("scope GPU sample is not RGBA/BGRA");
                }
                GstMapInfo map{};
                if (!gst_buffer_map(buffer, &map, GST_MAP_READ)) {
                    throw std::runtime_error("scope GPU frame download failed");
                }
                auto stride = static_cast<std::size_t>(
                    std::max(0, GST_VIDEO_INFO_PLANE_STRIDE(&info, 0)));
                if (gst_buffer_n_memory(buffer) > 0) {
                    auto* memory = gst_buffer_peek_memory(buffer, 0);
                    if (memory != nullptr && gst_is_d3d11_memory(memory)) {
                        guint resourceStride{};
                        if (gst_d3d11_memory_get_resource_stride(
                                GST_D3D11_MEMORY_CAST(memory), &resourceStride)) {
                            stride = resourceStride;
                        }
                    }
                }
                const auto width = static_cast<std::size_t>(GST_VIDEO_INFO_WIDTH(&info));
                const auto height = static_cast<std::size_t>(GST_VIDEO_INFO_HEIGHT(&info));
                if (stride < width * 4 || map.size < stride * height) {
                    gst_buffer_unmap(buffer, &map);
                    throw std::invalid_argument("scope GPU frame has invalid row stride");
                }
                std::optional<ffgui::ScopeAnalysis> analysis;
                try {
                    analysis = format == GST_VIDEO_FORMAT_RGBA
                        ? ffgui::analyze_scope_rgba8(
                            map.data, width, height, stride, frame.serial,
                            ffgui::ScopeReferenceStage::post_display)
                        : ffgui::analyze_scope_bgra8(
                            map.data, width, height, stride, frame.serial,
                            ffgui::ScopeReferenceStage::post_display);
                } catch (...) {
                    gst_buffer_unmap(buffer, &map);
                    throw;
                }
                gst_buffer_unmap(buffer, &map);
                result.analysis = std::make_shared<ffgui::ScopeAnalysis>(
                    std::move(*analysis));
            }
        } catch (const std::exception& error) {
            result.error = QString::fromUtf8(error.what());
        }
        return result;
    }));
#else
    static_cast<void>(frame);
#endif
}

bool EditorController::canUseFloatExport() const {
#ifdef FFGUI_HAS_GES
    if (timeline_.clips().empty() || !timeline_.captions().empty() || stamp_enabled_) return false;
    return std::ranges::all_of(timeline_.clips(), [this](const auto& clip) {
        const auto* asset = timeline_.asset(clip.asset_id);
        return asset != nullptr && asset->image_sequence().has_value();
    });
#else
    return false;
#endif
}

void EditorController::startFloatExport() {
#ifdef FFGUI_HAS_GES
    if (!export_request_.has_value() || !canUseFloatExport()) {
        export_stderr_.append("float export prerequisites are not satisfied");
        finishExport(false);
        return;
    }
    const auto timeline = timeline_;
    const auto settings = color_pipeline_;
    const auto request = *export_request_;
    const auto outputSpace = settings.mode == ffgui::ColorPipelineMode::legacy
        ? std::string{}
        : settings.output_space.empty() ? std::string{"sRGB - Display"} : settings.output_space;
    const auto* firstAsset = timeline.asset(timeline.clips().front().asset_id);
    const auto sourceRate = firstAsset->image_sequence()->frame_rate.value();
    const auto fps = request.gif.enabled
        ? request.gif.fps
        : request.output_fps > 0 ? request.output_fps
        : std::max(1, static_cast<int>(std::lround(sourceRate)));
    const auto duration = timeline.duration();
    const auto frameCount = std::max<qint64>(1, static_cast<qint64>(std::ceil(
        static_cast<long double>(duration) * fps / ffgui::kNanosecondsPerSecond)));
    export_duration_ns_ = duration;
    export_stage_ = request.gif.enabled
        ? QStringLiteral("float GIF 렌더링") : QStringLiteral("float 컬러 렌더링");
    export_stream_copy_active_ = false;
    if (export_log_file_ && export_log_file_->isOpen()) {
        export_log_file_->write(QStringLiteral(
            "\n--- float frame server start ---\nfps=%1\nframes=%2\nduration_ns=%3\n")
            .arg(fps).arg(frameCount).arg(duration).toUtf8());
        export_log_file_->flush();
    }
    emit exportProgressChanged();
    setStatus(QStringLiteral("내보내는 중 · 공통 float 프레임 서버"));
    float_export_cancel_ = std::make_shared<std::atomic_bool>(false);
    const auto cancelled = float_export_cancel_;
    const auto ffmpeg = ffgui::locate_ffmpeg();
    const auto quality = export_quality_;
    const auto codec = export_codec_;
    QPointer<EditorController> guard(this);
    float_export_active_ = true;
    float_export_watcher_.setFuture(QtConcurrent::run(
        [timeline, settings, outputSpace, request, fps, duration, frameCount, cancelled,
         ffmpeg, quality, codec, guard]() mutable {
            FloatExportResult result;
            ffgui::TimelineFrameServer server;
            const auto renderFrame = [&](qint64 frameIndex) {
                const auto time = std::min<ffgui::TimeNs>(
                    duration - 1,
                    static_cast<ffgui::TimeNs>(std::llround(
                        static_cast<long double>(frameIndex) *
                        ffgui::kNanosecondsPerSecond / fps)));
                return server.render(timeline, time, settings, outputSpace).processed;
            };
            try {
                auto first = renderFrame(0);
                if (first.width <= 0 || first.height <= 0) {
                    throw std::runtime_error("float export produced an empty frame");
                }
                const auto sourceWidth = first.width;
                const auto sourceHeight = first.height;
                const auto encode = [&](const QString& encoder) {
                    QProcess process;
                    process.setProcessChannelMode(QProcess::SeparateChannels);
#ifdef Q_OS_WIN
                    process.setCreateProcessArgumentsModifier(
                        [](QProcess::CreateProcessArguments* args) { args->flags |= CREATE_NO_WINDOW; });
#endif
                    QStringList arguments{
                        "-hide_banner", "-loglevel", "warning", "-y",
                        "-f", "rawvideo", "-pixel_format", "rgba64le",
                        "-video_size", QStringLiteral("%1x%2").arg(sourceWidth).arg(sourceHeight),
                        "-framerate", QString::number(fps), "-i", "pipe:0", "-an"};
                    if (request.gif.enabled) {
                        const auto dither = request.gif.dither == ffgui::GifDither::bayer
                            ? QStringLiteral("bayer:bayer_scale=3")
                            : request.gif.dither == ffgui::GifDither::sierra2_4a
                            ? QStringLiteral("sierra2_4a") : QStringLiteral("none");
                        arguments << "-filter_complex"
                            << QStringLiteral(
                                "[0:v]scale=%1:%2:force_original_aspect_ratio=decrease:flags=lanczos,"
                                "pad=%1:%2:(ow-iw)/2:(oh-ih)/2:color=black,split[a][b];"
                                "[a]palettegen=max_colors=%3:reserve_transparent=1[p];"
                                "[b][p]paletteuse=dither=%4[v]")
                                .arg(request.gif.width).arg(request.gif.height)
                                .arg(request.gif.colors).arg(dither)
                            << "-map" << "[v]" << "-loop" << (request.gif.loop ? "0" : "-1");
                    } else {
                        if (request.output_width > 0 && request.output_height > 0) {
                            arguments << "-vf" << QStringLiteral(
                                "scale=%1:%2:force_original_aspect_ratio=decrease:flags=lanczos,"
                                "pad=%1:%2:(ow-iw)/2:(oh-ih)/2:color=black")
                                .arg(request.output_width).arg(request.output_height);
                        } else {
                            arguments << "-vf" << "scale=trunc(iw/2)*2:trunc(ih/2)*2";
                        }
                        const auto quantizer = quality == 0 ? 18 : quality == 2 ? 28 : 23;
                        arguments << "-c:v" << encoder;
                        if (encoder.contains("nvenc")) {
                            arguments << "-preset" << "p5" << "-rc" << "vbr"
                                      << "-cq" << QString::number(quantizer) << "-b:v" << "0";
                        } else {
                            arguments << "-preset" << "medium"
                                      << "-crf" << QString::number(quantizer);
                        }
                        arguments << "-pix_fmt" << (encoder.contains("265") || encoder.contains("hevc")
                            ? "yuv420p10le" : "yuv420p");
                    }
                    arguments << QString::fromStdWString(request.output_path.wstring());
                    process.start(ffmpeg, arguments);
                    if (!process.waitForStarted(10'000)) {
                        return QByteArray("FFmpeg float encoder could not be started");
                    }
                    QByteArray stderrOutput;
                    const auto submit = [&](const ffgui::FloatImageFrame& frame) {
                        if (frame.width != sourceWidth || frame.height != sourceHeight) {
                            throw std::runtime_error(
                                "float export requires matching source dimensions");
                        }
                        QByteArray bytes;
                        bytes.resize(frame.width * frame.height * 8);
                        auto* destination = reinterpret_cast<std::uint16_t*>(bytes.data());
                        const auto pixels = static_cast<std::size_t>(frame.width) * frame.height;
                        for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
                            const auto* rgba = frame.rgba.data() + pixel * 4;
                            auto alpha = std::clamp(
                                std::isfinite(rgba[3]) ? rgba[3] : 0.0F, 0.0F, 1.0F);
                            for (std::size_t channel = 0; channel < 3; ++channel) {
                                auto value = std::isfinite(rgba[channel]) ? rgba[channel] : 0.0F;
                                if (frame.premultiplied && alpha > 0.0F) value /= alpha;
                                destination[pixel * 4 + channel] = static_cast<std::uint16_t>(
                                    std::lround(std::clamp(value, 0.0F, 1.0F) * 65535.0F));
                            }
                            destination[pixel * 4 + 3] = static_cast<std::uint16_t>(
                                std::lround(alpha * 65535.0F));
                        }
                        if (process.write(bytes) != bytes.size() ||
                            !process.waitForBytesWritten(30'000)) {
                            throw std::runtime_error("FFmpeg stopped accepting float frames");
                        }
                    };
                    for (qint64 frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
                        if (cancelled->load()) {
                            process.kill();
                            process.waitForFinished(5'000);
                            return QByteArray("float export cancelled");
                        }
                        if (frameIndex == 0) submit(first);
                        else submit(renderFrame(frameIndex));
                        stderrOutput.append(process.readAllStandardError());
                        if (guard) {
                            const auto progress = std::min<qreal>(
                                0.98, static_cast<qreal>(frameIndex + 1) / frameCount * 0.98);
                            QMetaObject::invokeMethod(guard, [guard, progress] {
                                if (!guard || !guard->exporting_) return;
                                guard->export_progress_ = progress;
                                emit guard->exportProgressChanged();
                            }, Qt::QueuedConnection);
                        }
                    }
                    process.closeWriteChannel();
                    QElapsedTimer finishWait;
                    finishWait.start();
                    while (!process.waitForFinished(250)) {
                        stderrOutput.append(process.readAllStandardError());
                        if (cancelled->load()) process.kill();
                        if (finishWait.elapsed() > 120'000) {
                            process.kill();
                            process.waitForFinished(5'000);
                            stderrOutput.append("FFmpeg float encoder timed out while finalizing");
                            break;
                        }
                    }
                    stderrOutput.append(process.readAllStandardError());
                    return process.exitStatus() == QProcess::NormalExit && process.exitCode() == 0
                        ? QByteArray{} : stderrOutput;
                };
                if (request.gif.enabled) {
                    result.error = encode({});
                } else {
                    const auto hardware = codec == 1
                        ? QStringLiteral("hevc_nvenc") : QStringLiteral("h264_nvenc");
                    result.error = encode(hardware);
                    if (!result.error.isEmpty() && !cancelled->load()) {
                        QFile::remove(QString::fromStdWString(request.output_path.wstring()));
                        const auto software = codec == 1
                            ? QStringLiteral("libx265") : QStringLiteral("libx264");
                        result.error = encode(software);
                    }
                }
                result.success = result.error.isEmpty() && !cancelled->load();
            } catch (const std::exception& error) {
                result.error = error.what();
            }
            return result;
        }));
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

std::string EditorController::makeUniqueGradeNodeId() {
    for (;;) {
        const auto candidate = "grade-" + std::to_string(++generated_grade_node_id_);
        const auto exists = std::ranges::any_of(timeline_.clips(), [&candidate](const auto& clip) {
            return std::ranges::any_of(clip.grade.nodes(), [&candidate](const auto& node) {
                return node.id == candidate;
            });
        });
        if (!exists) return candidate;
    }
}

std::string EditorController::makeUniqueSharedGradeId() {
    for (;;) {
        const auto candidate =
            "shared-grade-" + std::to_string(++generated_shared_grade_id_);
        const auto exists = std::ranges::any_of(timeline_.clips(), [&candidate](const auto& clip) {
            return std::ranges::any_of(clip.grade.nodes(), [&candidate](const auto& node) {
                return node.shared_id == candidate;
            });
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
            QJsonObject assetObject{
                {"id", QString::fromStdString(id)},
                {"path", QString::fromStdWString(asset.path().wstring())},
                {"playbackPath", QString::fromStdWString(asset.playback_path().wstring())},
                {"exportPath", QString::fromStdWString(asset.export_path().wstring())},
                {"kind", mediaKindName(asset.kind())},
                {"durationNs", timeString(asset.duration())},
                {"framePtsNs", framePts},
                {"audioPeaks", audioPeaks},
                {"keyframePtsNs", keyframePts},
                {"thumbnailAtlas", thumbnail_atlases_.value(QString::fromStdString(id))}};
            const auto& color = asset.source_color();
            assetObject.insert("sourceColor", QJsonObject{
                {"inputColorSpace", QString::fromStdString(color.input_color_space)},
                {"primaries", QString::fromStdString(color.primaries)},
                {"transfer", QString::fromStdString(color.transfer)},
                {"matrix", QString::fromStdString(color.matrix)},
                {"range", QString::fromStdString(color.range)},
                {"iccProfile", QString::fromStdString(color.icc_profile)},
                {"unresolved", color.unresolved}});
            if (asset.image_sequence().has_value()) {
                const auto& sequence = asset.image_sequence().value();
                QJsonArray present;
                QJsonArray missing;
                QJsonArray channels;
                QJsonArray availableParts;
                QJsonArray availableLayers;
                QJsonArray availableChannels;
                QJsonArray exrParts;
                for (const auto frame : sequence.present_frames) present.push_back(frame);
                for (const auto frame : sequence.missing_frames) missing.push_back(frame);
                for (const auto& channel : sequence.channel_mapping) {
                    channels.push_back(QString::fromStdString(channel));
                }
                for (const auto& part : sequence.available_parts) availableParts.push_back(QString::fromStdString(part));
                for (const auto& layer : sequence.available_layers) availableLayers.push_back(QString::fromStdString(layer));
                for (const auto& channel : sequence.available_channels) availableChannels.push_back(QString::fromStdString(channel));
                for (const auto& part : sequence.exr_parts) {
                    QJsonArray layers;
                    QJsonArray partChannels;
                    for (const auto& layer : part.layers) layers.push_back(QString::fromStdString(layer));
                    for (const auto& channel : part.channels) partChannels.push_back(QString::fromStdString(channel));
                    exrParts.push_back(QJsonObject{
                        {"name", QString::fromStdString(part.name)},
                        {"view", QString::fromStdString(part.view)},
                        {"layers", layers},
                        {"channels", partChannels}});
                }
                assetObject.insert("imageSequence", QJsonObject{
                    {"directory", QString::fromStdWString(sequence.directory.wstring())},
                    {"prefix", QString::fromStdString(sequence.prefix)},
                    {"suffix", QString::fromStdString(sequence.suffix)},
                    {"padding", sequence.padding},
                    {"firstFrame", sequence.first_frame},
                    {"lastFrame", sequence.last_frame},
                    {"fpsNumerator", sequence.frame_rate.numerator},
                    {"fpsDenominator", sequence.frame_rate.denominator},
                    {"presentFrames", present},
                    {"missingFrames", missing},
                    {"exrPart", QString::fromStdString(sequence.exr_part)},
                    {"exrView", QString::fromStdString(sequence.exr_view)},
                    {"exrLayer", QString::fromStdString(sequence.exr_layer)},
                    {"deep", sequence.deep},
                    {"availableParts", availableParts},
                    {"availableLayers", availableLayers},
                    {"availableChannels", availableChannels},
                    {"exrParts", exrParts},
                    {"channels", channels}});
            }
            assets.push_back(assetObject);
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
                {"transitionInNs", timeString(clip.transition_in)},
                {"gradeGraph", serializeGradeGraph(clip.grade)}});
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
        const QJsonObject outputSettings{
            {"quality", export_quality_},
            {"codec", export_codec_},
            {"container", export_container_},
            {"resolution", export_resolution_},
            {"frameRate", export_frame_rate_},
            {"gifPreset", gif_preset_},
            {"gifResolution", gif_resolution_},
            {"gifFrameRate", gif_frame_rate_},
            {"gifColors", gif_colors_},
            {"gifDither", gif_dither_},
            {"gifLoop", gif_loop_},
            {"directory", output_directory_},
            {"nameTemplate", QStringLiteral("{sequence}_v{version:03}")}};
        const QJsonObject colorPipeline{
            {"mode", static_cast<int>(color_pipeline_.mode)},
            {"ocioConfigPath", QString::fromStdString(color_pipeline_.ocio_config_path)},
            {"workingSpace", QString::fromStdString(color_pipeline_.working_space)},
            {"display", QString::fromStdString(color_pipeline_.display)},
            {"view", QString::fromStdString(color_pipeline_.view)},
            {"outputSpace", QString::fromStdString(color_pipeline_.output_space)},
            {"displayTransformBypassed", color_pipeline_.display_transform_bypassed},
            {"hdrMonitoring", color_pipeline_.hdr_monitoring},
            {"hdrPeakNits", color_pipeline_.hdr_peak_nits},
            {"sdrWhiteNits", color_pipeline_.sdr_white_nits},
            {"maxCll", color_pipeline_.max_cll},
            {"maxFall", color_pipeline_.max_fall}};
        const QJsonDocument document(QJsonObject{
            {"format", "ffmpegGUI-next"},
            {"version", 4},
            {"assets", assets},
            {"clips", clips},
            {"captions", captions},
            {"stamp", stamp},
            {"colorPipeline", colorPipeline},
            {"outputSettings", outputSettings}});

        QSaveFile file(path);
        if (!file.open(QIODevice::WriteOnly) || file.write(document.toJson()) < 0 || !file.commit()) {
            throw std::runtime_error("project file could not be saved atomically");
        }
        current_project_path_ = QFileInfo(path).absoluteFilePath();
        emit exportSettingsChanged();
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
        const auto version = root.value("version").toInt();
        if (parseError.error != QJsonParseError::NoError ||
            root.value("format").toString() != "ffmpegGUI-next" ||
            (version < 1 || version > 4)) {
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
            std::optional<ffgui::ImageSequenceDescriptor> sequence;
            const auto sequenceObject = object.value("imageSequence").toObject();
            if (!sequenceObject.isEmpty()) {
                ffgui::ImageSequenceDescriptor value;
                value.directory = std::filesystem::path(
                    sequenceObject.value("directory").toString().toStdWString());
                value.prefix = sequenceObject.value("prefix").toString().toStdString();
                value.suffix = sequenceObject.value("suffix").toString().toStdString();
                value.padding = sequenceObject.value("padding").toInt();
                value.first_frame = sequenceObject.value("firstFrame").toInt();
                value.last_frame = sequenceObject.value("lastFrame").toInt();
                value.frame_rate = {
                    sequenceObject.value("fpsNumerator").toInt(24),
                    sequenceObject.value("fpsDenominator").toInt(1)};
                for (const auto frame : sequenceObject.value("presentFrames").toArray()) {
                    value.present_frames.push_back(frame.toInt());
                }
                for (const auto frame : sequenceObject.value("missingFrames").toArray()) {
                    value.missing_frames.push_back(frame.toInt());
                }
                value.exr_part = sequenceObject.value("exrPart").toString().toStdString();
                value.exr_view = sequenceObject.value("exrView").toString().toStdString();
                value.exr_layer = sequenceObject.value("exrLayer").toString().toStdString();
                value.deep = sequenceObject.value("deep").toBool(false);
                for (const auto item : sequenceObject.value("availableParts").toArray()) {
                    value.available_parts.push_back(item.toString().toStdString());
                }
                for (const auto item : sequenceObject.value("availableLayers").toArray()) {
                    value.available_layers.push_back(item.toString().toStdString());
                }
                for (const auto item : sequenceObject.value("availableChannels").toArray()) {
                    value.available_channels.push_back(item.toString().toStdString());
                }
                for (const auto item : sequenceObject.value("exrParts").toArray()) {
                    const auto partObject = item.toObject();
                    ffgui::ExrPartDescriptor part;
                    part.name = partObject.value("name").toString().toStdString();
                    part.view = partObject.value("view").toString().toStdString();
                    for (const auto layer : partObject.value("layers").toArray()) {
                        part.layers.push_back(layer.toString().toStdString());
                    }
                    for (const auto channel : partObject.value("channels").toArray()) {
                        part.channels.push_back(channel.toString().toStdString());
                    }
                    if (!part.name.empty()) value.exr_parts.push_back(std::move(part));
                }
                if (value.exr_parts.empty() && !value.exr_part.empty()) {
                    value.exr_parts.push_back(ffgui::ExrPartDescriptor{
                        value.exr_part, value.exr_view,
                        value.available_layers, value.available_channels});
                }
                value.channel_mapping.clear();
                for (const auto channel : sequenceObject.value("channels").toArray()) {
                    value.channel_mapping.push_back(channel.toString().toStdString());
                }
                if (value.channel_mapping.empty()) value.channel_mapping = {"R", "G", "B", "A"};
                sequence = std::move(value);
            }
            const auto colorObject = object.value("sourceColor").toObject();
            ffgui::SourceColorDescriptor sourceColor;
            sourceColor.input_color_space = colorObject.value("inputColorSpace").toString().toStdString();
            sourceColor.primaries = colorObject.value("primaries").toString().toStdString();
            sourceColor.transfer = colorObject.value("transfer").toString().toStdString();
            sourceColor.matrix = colorObject.value("matrix").toString().toStdString();
            sourceColor.range = colorObject.value("range").toString().toStdString();
            sourceColor.icc_profile = colorObject.value("iccProfile").toString().toStdString();
            sourceColor.unresolved = colorObject.value("unresolved").toBool(false);
            const auto sourcePath = object.value("path").toString();
            const auto playbackPath = object.value("playbackPath").toString(sourcePath);
            const auto exportPath = object.value("exportPath").toString(sourcePath);
            loaded.add_asset(ffgui::MediaAsset{
                assetId.toStdString(),
                std::filesystem::path(sourcePath.toStdWString()),
                parseTime(object.value("durationNs"), "durationNs"),
                std::move(framePts),
                std::move(audioPeaks),
                std::move(keyframePts),
                parseMediaKind(object.value("kind").toString()),
                std::move(sequence),
                std::move(sourceColor),
                std::filesystem::path(playbackPath.toStdWString()),
                std::filesystem::path(exportPath.toStdWString())});
            const auto atlas = object.value("thumbnailAtlas").toString();
            if (QFileInfo(atlas).isFile()) {
                loadedAtlases.insert(assetId, atlas);
            }
        }
        for (const auto value : root.value("clips").toArray()) {
            const auto object = value.toObject();
            auto clip = ffgui::Clip{
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
                    ? parseTime(object.value("transitionInNs"), "transitionInNs") : 0};
            clip.grade = parseGradeGraph(object.value("gradeGraph").toObject());
            loaded.append_clip(std::move(clip));
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
        const auto outputSettings = root.value("outputSettings").toObject();
        const auto colorPipeline = root.value("colorPipeline").toObject();
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
        if (!outputSettings.isEmpty()) {
            export_quality_ = std::clamp(outputSettings.value("quality").toInt(1), 0, 2);
            export_codec_ = std::clamp(outputSettings.value("codec").toInt(0), 0, 2);
            export_container_ = std::clamp(outputSettings.value("container").toInt(0), 0, 3);
            export_resolution_ = std::clamp(outputSettings.value("resolution").toInt(0), 0, 3);
            export_frame_rate_ = std::clamp(outputSettings.value("frameRate").toInt(0), 0, 3);
            gif_preset_ = std::clamp(outputSettings.value("gifPreset").toInt(1), 0, 3);
            gif_resolution_ = std::clamp(outputSettings.value("gifResolution").toInt(1), 0, 2);
            gif_frame_rate_ = std::clamp(outputSettings.value("gifFrameRate").toInt(1), 0, 3);
            gif_colors_ = std::clamp(outputSettings.value("gifColors").toInt(1), 0, 2);
            gif_dither_ = std::clamp(outputSettings.value("gifDither").toInt(0), 0, 2);
            gif_loop_ = outputSettings.value("gifLoop").toBool(true);
            if (version >= 2) {
                const auto savedDirectory = outputSettings.value("directory").toString();
                if (!savedDirectory.isEmpty()) output_directory_ = savedDirectory;
            }
        }
        color_pipeline_ = {};
        if (!colorPipeline.isEmpty()) {
            color_pipeline_.mode = static_cast<ffgui::ColorPipelineMode>(
                std::clamp(colorPipeline.value("mode").toInt(0), 0, 2));
            color_pipeline_.ocio_config_path = colorPipeline.value("ocioConfigPath").toString().toStdString();
            color_pipeline_.working_space = colorPipeline.value("workingSpace").toString("ACEScg").toStdString();
            color_pipeline_.display = colorPipeline.value("display").toString().toStdString();
            color_pipeline_.view = colorPipeline.value("view").toString().toStdString();
            color_pipeline_.output_space = colorPipeline.value("outputSpace").toString().toStdString();
            color_pipeline_.display_transform_bypassed = colorPipeline.value("displayTransformBypassed").toBool(false);
            color_pipeline_.hdr_monitoring = colorPipeline.value("hdrMonitoring").toBool(false);
            color_pipeline_.hdr_peak_nits = colorPipeline.value("hdrPeakNits").toInt(1000);
            color_pipeline_.sdr_white_nits = colorPipeline.value("sdrWhiteNits").toInt(203);
            color_pipeline_.max_cll = colorPipeline.value("maxCll").toInt(1000);
            color_pipeline_.max_fall = colorPipeline.value("maxFall").toInt(400);
            color_pipeline_.validate();
        }
        current_project_path_ = QFileInfo(path).absoluteFilePath();
        QSettings().setValue(QStringLiteral("output/lastDirectory"), output_directory_);
        setSingleSelection(timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id));
        publishTimeline(true);
        emit graphicsChanged();
        emit exportSettingsChanged();
        emit colorPipelineChanged();
        emit gifEstimateChanged();
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

QString EditorController::sequenceName() const {
    QString name;
    if (!current_project_path_.isEmpty()) {
        name = QFileInfo(current_project_path_).completeBaseName();
    } else if (!timeline_.clips().empty()) {
        const auto* asset = timeline_.asset(timeline_.clips().front().asset_id);
        if (asset != nullptr) name = QFileInfo(QString::fromStdWString(asset->path().wstring())).completeBaseName();
    }
    if (name.isEmpty()) name = QStringLiteral("sequence");
    static const QRegularExpression invalid(QStringLiteral(R"([<>:"/\\|?*\x00-\x1f])"));
    name.replace(invalid, QStringLiteral("_"));
    name = name.trimmed();
    while (name.endsWith('.') || name.endsWith(' ')) name.chop(1);
    return name.isEmpty() ? QStringLiteral("sequence") : name;
}

QString EditorController::nextOutputPath() const {
    if (output_directory_.isEmpty()) return {};
    const auto base = sequenceName();
    const auto suffix = exportExtension();
    const QDir directory(output_directory_);
    for (int version = 1; version <= 9999; ++version) {
        const auto candidate = directory.filePath(
            QStringLiteral("%1_v%2.%3").arg(base).arg(version, 3, 10, QLatin1Char('0')).arg(suffix));
        if (!QFileInfo::exists(candidate)) return QFileInfo(candidate).absoluteFilePath();
    }
    return {};
}

QString EditorController::nextOutputName() const {
    return QFileInfo(nextOutputPath()).fileName();
}

QString EditorController::outputDirectoryError() const {
    if (output_directory_.isEmpty()) return QStringLiteral("출력 폴더가 지정되지 않았습니다");
    const QFileInfo info(output_directory_);
    if (info.exists() && !info.isDir()) return QStringLiteral("출력 경로가 폴더가 아닙니다");
    if (info.exists() && !info.isWritable()) return QStringLiteral("출력 폴더에 쓸 수 없습니다");
    auto parent = info.absoluteDir();
    while (!parent.exists() && parent.cdUp()) {}
    if (!info.exists() && (!parent.exists() || !QFileInfo(parent.absolutePath()).isWritable())) {
        return QStringLiteral("출력 폴더를 만들 수 없습니다");
    }
    if (nextOutputPath().isEmpty()) return QStringLiteral("사용 가능한 버전 이름이 없습니다");
    return {};
}

bool EditorController::outputDirectoryValid() const {
    return outputDirectoryError().isEmpty();
}

bool EditorController::ensureOutputDirectory() {
    if (output_directory_.isEmpty() || !QDir().mkpath(output_directory_)) {
        setStatus("출력 폴더를 만들 수 없습니다");
        emit exportSettingsChanged();
        return false;
    }
    const auto error = outputDirectoryError();
    if (!error.isEmpty()) {
        setStatus(error);
        emit exportSettingsChanged();
        return false;
    }
    return true;
}

void EditorController::setOutputDirectoryUrl(const QUrl& url) {
    if (!url.isLocalFile()) {
        setStatus("로컬 출력 폴더만 사용할 수 있습니다");
        return;
    }
    const auto directory = QFileInfo(url.toLocalFile()).absoluteFilePath();
    if (!QDir().mkpath(directory) || !QFileInfo(directory).isDir()) {
        setStatus("출력 폴더를 만들 수 없습니다");
        return;
    }
    output_directory_ = QDir::cleanPath(directory);
    QSettings().setValue(QStringLiteral("output/lastDirectory"), output_directory_);
    emit exportSettingsChanged();
    setStatus("출력 폴더를 변경했습니다");
}

void EditorController::openOutputDirectory() {
    if (!ensureOutputDirectory()) return;
    if (!QDesktopServices::openUrl(QUrl::fromLocalFile(output_directory_))) {
        setStatus("출력 폴더를 열 수 없습니다");
    }
}

void EditorController::copyOutputDirectory() {
    if (output_directory_.isEmpty()) return;
    QGuiApplication::clipboard()->setText(QDir::toNativeSeparators(output_directory_));
    setStatus("출력 경로를 복사했습니다");
}

QString EditorController::exportElapsedText() const {
    if (!exporting_ || !export_elapsed_timer_.isValid()) return QStringLiteral("--:--");
    const auto seconds = export_elapsed_timer_.elapsed() / 1000;
    return QStringLiteral("%1:%2").arg(seconds / 60, 2, 10, QLatin1Char('0'))
        .arg(seconds % 60, 2, 10, QLatin1Char('0'));
}

QString EditorController::exportRemainingText() const {
    if (!exporting_ || export_progress_ <= 0.001 || !export_elapsed_timer_.isValid()) {
        return QStringLiteral("계산 중");
    }
    const auto elapsed = export_elapsed_timer_.elapsed() / 1000.0;
    const auto remaining = static_cast<qint64>(std::max(0.0, elapsed * (1.0 - export_progress_) / export_progress_));
    return QStringLiteral("%1:%2").arg(remaining / 60, 2, 10, QLatin1Char('0'))
        .arg(remaining % 60, 2, 10, QLatin1Char('0'));
}

QString EditorController::colorPipelineSummary() const {
    if (color_pipeline_.mode == ffgui::ColorPipelineMode::legacy) {
        return QStringLiteral("현재 색 유지 · Legacy");
    }
    if (color_pipeline_.mode == ffgui::ColorPipelineMode::aces_managed) {
        return color_pipeline_.hdr_monitoring
            ? QStringLiteral("ACEScg · HDR 모니터") : QStringLiteral("ACEScg · SDR 모니터");
    }
    return QFileInfo(QString::fromStdString(color_pipeline_.ocio_config_path)).fileName();
}

QStringList EditorController::inputColorSpaceOptions() const {
    try {
        auto settings = color_pipeline_;
        if (settings.mode == ffgui::ColorPipelineMode::legacy) {
            settings.mode = ffgui::ColorPipelineMode::aces_managed;
        }
        const auto spaces = ffgui::OcioEngine(settings).color_spaces();
        QStringList result;
        result.reserve(static_cast<qsizetype>(spaces.size()));
        for (const auto& space : spaces) result.push_back(QString::fromStdString(space));
        return result;
    } catch (...) {
        return {};
    }
}

void EditorController::setColorPipelineMode(int mode) {
    mode = std::clamp(mode, 0, 2);
    const auto value = static_cast<ffgui::ColorPipelineMode>(mode);
    if (value == ffgui::ColorPipelineMode::custom_ocio &&
        color_pipeline_.ocio_config_path.empty()) {
        setStatus("사용자 OCIO 설정 파일을 먼저 선택하세요");
        return;
    }
    if (color_pipeline_.mode == value) return;
    color_pipeline_.mode = value;
    emit colorPipelineChanged();
    publishTimeline(false);
    setStatus(value == ffgui::ColorPipelineMode::legacy
        ? "기존 색상을 유지합니다"
        : value == ffgui::ColorPipelineMode::aces_managed
            ? "ACES 2.0 · ACEScg 컬러 관리를 사용합니다"
            : "사용자 OCIO 컬러 관리를 사용합니다");
}

void EditorController::setCustomOcioUrl(const QUrl& url) {
    if (!url.isLocalFile()) {
        setStatus("로컬 OCIO 설정 파일만 사용할 수 있습니다");
        return;
    }
    const QFileInfo file(url.toLocalFile());
    const auto suffix = file.suffix().toLower();
    if (!file.isFile() || (suffix != "ocio" && suffix != "ocioz")) {
        setStatus(".ocio 또는 .ocioz 설정 파일을 선택하세요");
        return;
    }
    color_pipeline_.ocio_config_path = file.absoluteFilePath().toStdString();
    color_pipeline_.mode = ffgui::ColorPipelineMode::custom_ocio;
    emit colorPipelineChanged();
    publishTimeline(false);
    setStatus("사용자 OCIO 설정을 적용했습니다");
}

void EditorController::setHdrMonitoring(bool enabled) {
    if (color_pipeline_.hdr_monitoring == enabled) return;
    color_pipeline_.hdr_monitoring = enabled;
    emit colorPipelineChanged();
    setStatus(enabled ? "HDR 모니터 출력을 요청했습니다" : "SDR 모니터 출력을 사용합니다");
}

void EditorController::setHdrPeakNits(int nits) {
    nits = std::clamp(nits, 100, 10'000);
    if (color_pipeline_.hdr_peak_nits == nits) return;
    color_pipeline_.hdr_peak_nits = nits;
    color_pipeline_.max_cll = nits;
    emit colorPipelineChanged();
}

void EditorController::setSdrWhiteNits(int nits) {
    nits = std::clamp(nits, 80, 500);
    if (color_pipeline_.sdr_white_nits == nits) return;
    color_pipeline_.sdr_white_nits = nits;
    emit colorPipelineChanged();
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
    container = std::clamp(container, 0, 3);
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

void EditorController::setGifPreset(int preset) {
    preset = std::clamp(preset, 0, 3);
    if (preset == 3) {
        if (gif_preset_ == preset) return;
        gif_preset_ = preset;
        emit exportSettingsChanged();
        emit gifEstimateChanged();
        return;
    }
    gif_preset_ = preset;
    if (preset == 0) {
        gif_resolution_ = 0; gif_frame_rate_ = 0; gif_colors_ = 0; gif_dither_ = 0;
    } else if (preset == 1) {
        gif_resolution_ = 1; gif_frame_rate_ = 1; gif_colors_ = 1; gif_dither_ = 0;
    } else {
        gif_resolution_ = 2; gif_frame_rate_ = 2; gif_colors_ = 2; gif_dither_ = 1;
    }
    emit exportSettingsChanged();
    emit gifEstimateChanged();
}

void EditorController::setGifResolution(int resolution) {
    resolution = std::clamp(resolution, 0, 2);
    if (gif_resolution_ == resolution && gif_preset_ == 3) return;
    gif_resolution_ = resolution; gif_preset_ = 3; emit exportSettingsChanged(); emit gifEstimateChanged();
}

void EditorController::setGifFrameRate(int frameRate) {
    frameRate = std::clamp(frameRate, 0, 3);
    if (gif_frame_rate_ == frameRate && gif_preset_ == 3) return;
    gif_frame_rate_ = frameRate; gif_preset_ = 3; emit exportSettingsChanged(); emit gifEstimateChanged();
}

void EditorController::setGifColors(int colors) {
    colors = std::clamp(colors, 0, 2);
    if (gif_colors_ == colors && gif_preset_ == 3) return;
    gif_colors_ = colors; gif_preset_ = 3; emit exportSettingsChanged(); emit gifEstimateChanged();
}

void EditorController::setGifDither(int dither) {
    dither = std::clamp(dither, 0, 2);
    if (gif_dither_ == dither && gif_preset_ == 3) return;
    gif_dither_ = dither; gif_preset_ = 3; emit exportSettingsChanged(); emit gifEstimateChanged();
}

void EditorController::setGifLoop(bool loop) {
    if (gif_loop_ == loop) return;
    gif_loop_ = loop;
    emit exportSettingsChanged();
    emit gifEstimateChanged();
}

QString EditorController::gifEstimatedSizeText() const {
    static constexpr int widths[]{480, 640, 960};
    static constexpr int heights[]{270, 360, 540};
    static constexpr int rates[]{8, 12, 15, 20};
    static constexpr int colorCounts[]{64, 128, 256};
    static constexpr double colorFactors[]{0.08, 0.13, 0.20};
    static constexpr double ditherFactors[]{0.75, 1.25, 0.60};
    const auto seconds = static_cast<double>(durationNs()) / 1'000'000'000.0;
    const auto pixels = static_cast<double>(widths[gif_resolution_]) * heights[gif_resolution_] *
        rates[gif_frame_rate_] * seconds;
    const auto center = pixels / 1'000'000.0 * colorFactors[gif_colors_] *
        ditherFactors[gif_dither_];
    const auto low = std::max(0.1, center * 0.55);
    const auto high = std::max(0.2, center * 1.8);
    return QStringLiteral("예상 %1~%2 MB · %3초 · %4 fps · %5색")
        .arg(low, 0, 'f', 1)
        .arg(high, 0, 'f', 1)
        .arg(seconds, 0, 'f', 1)
        .arg(rates[gif_frame_rate_])
        .arg(colorCounts[gif_colors_]);
}

int EditorController::gifSizeRisk() const noexcept {
    static constexpr int widths[]{480, 640, 960};
    static constexpr int heights[]{270, 360, 540};
    static constexpr int rates[]{8, 12, 15, 20};
    static constexpr double colorFactors[]{0.08, 0.13, 0.20};
    static constexpr double ditherFactors[]{0.75, 1.25, 0.60};
    const auto seconds = static_cast<double>(durationNs()) / 1'000'000'000.0;
    const auto upperMb = static_cast<double>(widths[gif_resolution_]) * heights[gif_resolution_] *
        rates[gif_frame_rate_] * seconds / 1'000'000.0 * colorFactors[gif_colors_] *
        ditherFactors[gif_dither_] * 1.8;
    return upperMb >= 50.0 ? 2 : (upperMb >= 20.0 ? 1 : 0);
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
    if (export_container_ == 3) return QStringLiteral("gif");
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

void EditorController::exportTimeline() {
    if (exporting_) {
        setStatus("이미 내보내는 중입니다");
        return;
    }
    if (timeline_.clips().empty()) {
        setStatus("내보낼 타임라인이 없습니다");
        return;
    }
    if (!ensureOutputDirectory()) return;
    const auto output = nextOutputPath();
    if (output.isEmpty()) {
        setStatus("출력 파일 이름을 만들 수 없습니다");
        return;
    }
    exportTimelineUrl(QUrl::fromLocalFile(output));
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
    const auto expectedExtension = exportExtension();
    const QFileInfo requestedOutput(output);
    if (requestedOutput.suffix().isEmpty()) {
        output += "." + expectedExtension;
    } else if (requestedOutput.suffix().compare(expectedExtension, Qt::CaseInsensitive) != 0) {
        output = requestedOutput.absoluteDir().filePath(
            requestedOutput.completeBaseName() + "." + expectedExtension);
    }
    if (QFileInfo::exists(output)) {
        setStatus("기존 파일을 덮어쓰지 않습니다. 새 이름을 선택하세요");
        return;
    }

    const auto preflight = ffgui::build_render_preflight(timeline_, color_pipeline_);
    if (!preflight.can_render()) {
        const auto blocker = std::ranges::find(
            preflight.issues, ffgui::PreflightSeverity::blocker,
            &ffgui::PreflightIssue::severity);
        setStatus(blocker == preflight.issues.end()
            ? QStringLiteral("출력 사전 검사를 통과하지 못했습니다")
            : QStringLiteral("출력 중단: %1").arg(QString::fromStdString(blocker->message)));
        return;
    }
#ifdef FFGUI_HAS_GES
    // GES timeline rebuilds mutate a shared native graph. Never let a delayed preview
    // rebuild race export preparation or process teardown.
    preview_suspended_for_export_ = true;
    preview_update_timer_.stop();
    preview_operation_pending_ = false;
    pending_preview_seek_.reset();
    preview_should_play_ = false;
    if (preview_watcher_.isRunning()) preview_watcher_.waitForFinished();
    player_->stop();
#endif
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
    if (export_container_ == 3) {
        static constexpr int widths[]{480, 640, 960};
        static constexpr int heights[]{270, 360, 540};
        static constexpr int rates[]{8, 12, 15, 20};
        static constexpr int colors[]{64, 128, 256};
        request.prefer_stream_copy = false;
        request.output_width = 0;
        request.output_height = 0;
        request.output_fps = 0;
        request.gif = ffgui::GifExportSettings{
            true,
            widths[gif_resolution_],
            heights[gif_resolution_],
            rates[gif_frame_rate_],
            colors[gif_colors_],
            static_cast<ffgui::GifDither>(gif_dither_),
            gif_loop_};
    }
    const auto exportSnapshot = timeline_.snapshot();
    if (exportSnapshot.empty()) return;
    last_export_matched_preview_ = false;
    for (const auto& span : exportSnapshot) {
        const auto* asset = timeline_.asset(span.clip.asset_id);
        request.clips.push_back(ffgui::ExportClipInput{
            span.export_path,
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
    const auto exportJobId = QStringLiteral("%1-%2")
        .arg(QCoreApplication::applicationPid())
        .arg(QDateTime::currentMSecsSinceEpoch());
    export_concat_path_ = QDir(exportCache).filePath(exportJobId + ".ffconcat");
    request.concat_script_path = std::filesystem::path(export_concat_path_.toStdWString());
    export_subtitle_path_ = QDir(exportCache).filePath(exportJobId + ".ass");
    request.subtitle_script_path = std::filesystem::path(export_subtitle_path_.toStdWString());

    // Sequence-only jobs use the original float frame server. Other jobs retain the
    // established FFmpeg transition/audio/overlay graph and apply the exact clip color
    // transform as a 3D LUT before composition.
    const bool floatOnly = std::ranges::all_of(exportSnapshot, [this](const auto& span) {
        const auto* asset = timeline_.asset(span.clip.asset_id);
        return asset != nullptr && asset->image_sequence().has_value();
    }) && timeline_.captions().empty() && !stamp_enabled_;
    export_color_lut_paths_.clear();
    if (!floatOnly) {
        const auto outputSpace = color_pipeline_.mode == ffgui::ColorPipelineMode::legacy
            ? std::string{}
            : color_pipeline_.output_space.empty()
                ? std::string{"sRGB - Display"} : color_pipeline_.output_space;
        try {
            for (std::size_t index = 0; index < exportSnapshot.size(); ++index) {
                const auto& span = exportSnapshot[index];
                const auto* asset = timeline_.asset(span.clip.asset_id);
                const bool hasClipControls = span.clip.color.brightness != 0.0 ||
                    span.clip.color.contrast != 1.0 || span.clip.color.saturation != 1.0;
                if (asset == nullptr || (color_pipeline_.mode == ffgui::ColorPipelineMode::legacy &&
                    span.clip.grade.nodes().empty() && !hasClipControls)) {
                    continue;
                }
                const auto lutPath = QDir(exportCache).filePath(
                    QStringLiteral("%1-clip-%2.cube").arg(exportJobId).arg(index));
                const auto payload = ffgui::bake_color_cube(
                    asset->source_color(), color_pipeline_,
                    ffgui::compose_clip_grade(span.clip), outputSpace, 33);
                QSaveFile file(lutPath);
                const auto bytes = QByteArray::fromStdString(payload);
                if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() ||
                    !file.commit()) {
                    throw std::runtime_error("clip color LUT could not be written");
                }
                export_color_lut_paths_.push_back(lutPath);
                request.clips[index].color_lut_path =
                    std::filesystem::path(lutPath.toStdWString());
                request.clips[index].brightness = 0.0;
                request.clips[index].contrast = 1.0;
                request.clips[index].saturation = 1.0;
            }
        } catch (const std::exception& error) {
            for (const auto& path : export_color_lut_paths_) QFile::remove(path);
            export_color_lut_paths_.clear();
            setStatus(QStringLiteral("출력 중단: 컬러 준비 실패 · %1")
                .arg(QString::fromUtf8(error.what())));
#ifdef FFGUI_HAS_GES
            preview_suspended_for_export_ = false;
            queuePreviewOperation(true);
#endif
            return;
        }
    }
    export_request_ = std::move(request);
    // The export contract is the immutable model snapshot captured above. Preview preparation
    // is asynchronous and must never make a newer edit unexportable or export stale clips.
    last_export_matched_preview_ = true;
    export_cpu_fallback_ = false;
    export_cancelled_ = false;
    last_export_stream_copy_ = false;
    export_progress_ = 0;
    export_elapsed_timer_.start();
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
    if (canUseFloatExport()) {
        startFloatExport();
    } else {
        startExportProcess(export_codec_ == 1
            ? ffgui::ExportVideoEncoder::hevc_nvenc
            : ffgui::ExportVideoEncoder::h264_nvenc);
    }
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
        export_stage_ = export_request_->gif.enabled
            ? QStringLiteral("GIF 팔레트 최적화")
            : export_stream_copy_active_
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
        setStatus(export_request_->gif.enabled
            ? "내보내는 중 · GIF 팔레트 최적화"
            : export_stream_copy_active_
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
    if (float_export_cancel_) float_export_cancel_->store(true);
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
    for (const auto& path : export_color_lut_paths_) QFile::remove(path);
    export_concat_path_.clear();
    export_subtitle_path_.clear();
    export_color_lut_paths_.clear();
    export_stream_copy_active_ = false;
    exporting_ = false;
#ifdef FFGUI_HAS_GES
    preview_suspended_for_export_ = false;
#endif
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
#ifdef FFGUI_HAS_GES
    if (!timeline_.clips().empty()) queuePreviewOperation(true);
#endif
}

void EditorController::queuePreviewOperation(bool restorePosition) {
#ifdef FFGUI_HAS_GES
    if (preview_suspended_for_export_) return;
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
    if (preview_suspended_for_export_ || preview_watcher_.isRunning() ||
        !preview_operation_pending_) return;

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
    const auto colorSettings = color_pipeline_;
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
         shouldStop,
         colorSettings]() mutable {
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
                if (rebuild && colorSettings.mode != ffgui::ColorPipelineMode::legacy) {
                    ffgui::OcioEngine warmColorCache(colorSettings);
                    static_cast<void>(warmColorCache.managed());
                }
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
    stopFloatPlayback();
    preview_should_play_ = false;
    pending_float_video_frame_.reset();
    player_->set_legacy_source_color_enabled(
        color_pipeline_.mode == ffgui::ColorPipelineMode::legacy);
    player_->set_color_pipeline(
        color_pipeline_, color_pipeline_.mode == ffgui::ColorPipelineMode::legacy
            ? std::string{}
            : color_pipeline_.output_space.empty()
                ? std::string{"sRGB - Display"}
                : color_pipeline_.output_space);
    player_->set_float_output_enabled(requiresFloatVideoPreview());
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
    emit gifEstimateChanged();
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
