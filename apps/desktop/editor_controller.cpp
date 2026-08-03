#include "editor_controller.hpp"
#include "ffprobe_analyzer.hpp"
#include "d3d11_video_item.hpp"

#include <QFile>
#include <QCoreApplication>
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
#include <QtConcurrentRun>

#include <algorithm>
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
                setStatus(QString::fromUtf8(error.what()));
            }
            importing_ = false;
            emit importingChanged();
            emit mediaImportFinished(success);
        });
    export_process_.setProcessChannelMode(QProcess::SeparateChannels);
#ifdef Q_OS_WIN
    export_process_.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments* args) {
        args->flags |= CREATE_NO_WINDOW;
    });
#endif
    connect(&export_process_, &QProcess::readyReadStandardError, this, [this] {
        export_stderr_.append(export_process_.readAllStandardError());
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
                finishExport(true);
                return;
            }
            if (!export_cancelled_ && export_stream_copy_active_) {
                export_request_->prefer_stream_copy = false;
                QFile::remove(QString::fromStdWString(export_request_->output_path.wstring()));
                QFile::remove(export_concat_path_);
                setStatus("무손실 복사를 적용할 수 없어 NVENC로 다시 시도합니다");
                startExportProcess(ffgui::ExportVideoEncoder::h264_nvenc);
                return;
            }
            if (!export_cancelled_ && !export_cpu_fallback_) {
                export_cpu_fallback_ = true;
                QFile::remove(QString::fromStdWString(export_request_->output_path.wstring()));
                setStatus("NVENC를 사용할 수 없어 CPU 인코딩으로 다시 시도합니다");
                startExportProcess(ffgui::ExportVideoEncoder::libx264);
                return;
            }
            finishExport(false);
        });
    connect(&export_process_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (exporting_ && error == QProcess::FailedToStart) {
            finishExport(false);
        }
    });
#ifdef FFGUI_HAS_GES
    use_d3d_scene_graph_ = qEnvironmentVariableIntValue("FFGUI_EXPERIMENTAL_D3D11_QSG") == 1;
    player_ = std::make_unique<ffgui::GesSequencePlayer>(
        use_d3d_scene_graph_ ? "appsink" : "d3d11videosink",
        "wasapi2sink");
    player_->set_video_frame_callback([this](ffgui::D3D11VideoFrame frame) {
        QMetaObject::invokeMethod(
            this,
            [this, frame = std::move(frame)]() mutable {
                if (auto* item = qobject_cast<D3D11VideoItem*>(video_item_)) {
                    ++video_frames_delivered_;
                    item->submitFrame(std::move(frame));
                }
            },
            Qt::QueuedConnection);
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
                setStatus(QString::fromUtf8(message));
            },
            Qt::QueuedConnection);
    });
#endif
    preview_update_timer_.setSingleShot(true);
    preview_update_timer_.setInterval(50);
    connect(&preview_update_timer_, &QTimer::timeout, this, [this] {
        static_cast<void>(applyPreviewTimeline(true));
    });
}

void EditorController::setVideoWindow(QWindow* window) {
    video_window_ = window;
    if (video_window_ == nullptr || use_d3d_scene_graph_) return;
    video_window_->create();
#ifdef FFGUI_HAS_GES
    player_->set_video_window_handle(static_cast<std::uintptr_t>(video_window_->winId()));
#endif
}

EditorController::~EditorController() {
    if (export_process_.state() != QProcess::NotRunning) {
        export_process_.kill();
        export_process_.waitForFinished(3'000);
    }
    if (!export_concat_path_.isEmpty()) QFile::remove(export_concat_path_);
}

std::uint64_t EditorController::videoFramesReceived() const noexcept {
#ifdef FFGUI_HAS_GES
    return player_ ? player_->video_frames_received() : 0;
#else
    return 0;
#endif
}

QVariantList EditorController::clips() const {
    QVariantList result;
    const auto spans = timeline_.snapshot();
    for (std::size_t index = 0; index < spans.size(); ++index) {
        const auto& span = spans[index];
        QVariantMap value;
        value.insert("id", QString::fromStdString(span.clip.id));
        value.insert("name", QString::fromStdWString(span.source_path.stem().wstring()));
        value.insert("timelineInNs", static_cast<qint64>(span.timeline_in));
        value.insert("sourceInNs", static_cast<qint64>(span.clip.source_in));
        value.insert("durationNs", static_cast<qint64>(span.clip.duration));
        const auto* asset = timeline_.asset(span.clip.asset_id);
        value.insert("assetDurationNs", static_cast<qint64>(asset ? asset->duration() : 0));
        value.insert(
            "thumbnailAtlas",
            thumbnail_atlases_.value(QString::fromStdString(span.clip.asset_id)));
        QVariantList waveform;
        if (asset != nullptr) {
            waveform.reserve(static_cast<qsizetype>(asset->audio_peaks().size()));
            for (const auto peak : asset->audio_peaks()) {
                waveform.push_back(peak);
            }
        }
        value.insert("waveform", waveform);
        value.insert("color", index % 2 == 0 ? "#315a94" : "#3b6599");
        result.push_back(value);
    }
    return result;
}

QVariantList EditorController::mediaAssets() const {
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
    return result;
}

qint64 EditorController::durationNs() const noexcept {
    return static_cast<qint64>(timeline_.duration());
}

void EditorController::attachVideoItem(QObject* item) {
    auto* videoItem = qobject_cast<D3D11VideoItem*>(item);
    if (videoItem == nullptr) {
        setStatus("D3D11 미리보기 화면을 연결할 수 없습니다");
        return;
    }
    video_item_ = videoItem;
    connect(videoItem, &D3D11VideoItem::framePresented, this, [this](quint64) {
        ++video_frames_presented_;
    });
#ifdef FFGUI_HAS_GES
    connect(videoItem, &D3D11VideoItem::d3d11DeviceReady, this, [this](quintptr device) {
        player_->set_d3d11_device(reinterpret_cast<void*>(device));
        preview_applied_generation_.reset();
        if (!preview_snapshot_.empty()) static_cast<void>(applyPreviewTimeline(true));
    });
    if (videoItem->devicePointer() != 0) {
        player_->set_d3d11_device(reinterpret_cast<void*>(videoItem->devicePointer()));
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
    try {
        if (!applyPreviewTimeline(false)) return;
        player_->seek(playhead_ns_);
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
#endif
}

void EditorController::togglePlayback() {
#ifdef FFGUI_HAS_GES
    try {
        if (playing_) {
            player_->pause();
        } else {
            if (!applyPreviewTimeline(true)) return;
            if (playhead_ns_ >= durationNs()) {
                seek(0);
            }
            player_->play();
        }
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
#endif
}

void EditorController::stepFrame(int direction) {
    if (direction == 0 || timeline_.clips().empty()) return;
#ifdef FFGUI_HAS_GES
    try {
        if (playing_) player_->pause();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
        return;
    }
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

void EditorController::stop() {
#ifdef FFGUI_HAS_GES
    player_->stop();
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
                {"durationNs", timeString(clip.duration)}});
        }
        const QJsonDocument document(QJsonObject{
            {"format", "ffmpegGUI-next"},
            {"version", 1},
            {"assets", assets},
            {"clips", clips}});

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
                parseTime(object.value("durationNs"), "durationNs")});
        }
        loaded.clear_history();
        timeline_ = std::move(loaded);
        thumbnail_atlases_ = std::move(loadedAtlases);
        setSingleSelection(timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id));
        publishTimeline(true);
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
    if (QFileInfo(output).suffix().isEmpty()) output += ".mp4";
    if (QFileInfo::exists(output)) {
        setStatus("기존 파일을 덮어쓰지 않습니다. 새 이름을 선택하세요");
        return;
    }

    ffgui::ExportRequest request;
    request.output_path = std::filesystem::path(output.toStdWString());
    if (preview_revision_ != timeline_.revision() || preview_snapshot_.empty()) {
        setStatus("미리보기와 편집 상태가 일치하지 않아 출력을 시작하지 않았습니다");
        return;
    }
    last_export_matched_preview_ = false;
    for (const auto& span : preview_snapshot_) {
        const auto* asset = timeline_.asset(span.clip.asset_id);
        request.clips.push_back(ffgui::ExportClipInput{
            span.source_path,
            span.clip.source_in,
            span.clip.duration,
            asset != nullptr && !asset->audio_peaks().empty(),
            asset != nullptr ? asset->duration() : 0,
            asset != nullptr ? asset->keyframe_pts() : std::vector<ffgui::TimeNs>{}});
    }
    const auto exportCache = QDir(QStandardPaths::writableLocation(QStandardPaths::CacheLocation))
        .filePath("export-jobs");
    QDir().mkpath(exportCache);
    export_concat_path_ = QDir(exportCache).filePath(QStringLiteral("%1-%2.ffconcat")
        .arg(QCoreApplication::applicationPid())
        .arg(QDateTime::currentMSecsSinceEpoch()));
    request.concat_script_path = std::filesystem::path(export_concat_path_.toStdWString());
    export_request_ = std::move(request);
    last_export_matched_preview_ = true;
    export_cpu_fallback_ = false;
    export_cancelled_ = false;
    last_export_stream_copy_ = false;
    export_progress_ = 0;
    exporting_ = true;
    emit exportProgressChanged();
    emit exportingChanged();
#ifdef FFGUI_HAS_GES
    if (playing_) player_->pause();
#endif
    startExportProcess(ffgui::ExportVideoEncoder::h264_nvenc);
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
        QStringList arguments;
        arguments.reserve(static_cast<qsizetype>(plan.arguments.size()));
        for (const auto& argument : plan.arguments) {
            arguments.push_back(QString::fromUtf8(argument.data(), static_cast<qsizetype>(argument.size())));
        }
        export_stderr_.clear();
        export_process_.setProgram(ffgui::locate_ffmpeg());
        export_process_.setArguments(arguments);
        setStatus(export_stream_copy_active_
            ? "내보내는 중 · 무손실 복사"
            : (encoder == ffgui::ExportVideoEncoder::h264_nvenc
                ? "내보내는 중 · NVENC"
                : "내보내는 중 · CPU"));
        export_process_.start();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
        finishExport(false);
    }
}

void EditorController::cancelExport() {
    if (!exporting_) return;
    export_cancelled_ = true;
    setStatus("내보내기를 취소하는 중입니다");
    export_process_.kill();
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
    if (!export_concat_path_.isEmpty()) QFile::remove(export_concat_path_);
    export_concat_path_.clear();
    export_stream_copy_active_ = false;
    exporting_ = false;
    emit exportProgressChanged();
    emit exportingChanged();
    emit exportFinished(success, QUrl::fromLocalFile(output));
    export_request_.reset();
}

bool EditorController::applyPreviewTimeline(bool restorePosition) {
#ifdef FFGUI_HAS_GES
    if (preview_applied_generation_.has_value() &&
        preview_applied_generation_.value() == preview_generation_) {
        return true;
    }
    preview_update_timer_.stop();
    try {
        player_->set_timeline(preview_snapshot_);
        preview_applied_generation_ = preview_generation_;
        ++preview_rebuild_count_;
        if (restorePosition && playhead_ns_ > 0 && playhead_ns_ < durationNs()) {
            player_->seek(playhead_ns_);
        }
        setStatus(timeline_.clips().empty() ? "미디어를 추가하세요" : "재생 준비 완료");
        return true;
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
        return false;
    }
#else
    static_cast<void>(restorePosition);
    return true;
#endif
}

void EditorController::publishTimeline(bool resetPlayhead) {
#ifdef FFGUI_HAS_GES
    try {
        if (playing_) player_->stop();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
#endif
    if (resetPlayhead) {
        playhead_ns_ = 0;
    } else {
        playhead_ns_ = std::clamp<qint64>(playhead_ns_, 0, durationNs());
    }
    preview_snapshot_ = timeline_.snapshot();
    preview_revision_ = timeline_.revision();
    ++preview_generation_;
    emit timelineChanged();
    emit playheadChanged();
    emit selectedClipChanged();
    emit historyChanged();
#ifdef FFGUI_HAS_GES
    preview_update_timer_.start();
    setStatus(timeline_.clips().empty() ? "미디어를 추가하세요" : "미리보기 갱신 중");
#else
    setStatus(timeline_.clips().empty() ? "미디어를 추가하세요" : "재생 준비 완료");
#endif
}

void EditorController::setStatus(QString status) {
    if (status_ == status) {
        return;
    }
    status_ = std::move(status);
    emit statusChanged();
}
