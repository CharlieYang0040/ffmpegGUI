#include "editor_controller.hpp"
#include "ffprobe_analyzer.hpp"

#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaObject>
#include <QJSEngine>
#include <QSaveFile>
#include <QtConcurrentRun>

#include <algorithm>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

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
                    const auto duration = item.asset.duration();
                    timeline_.add_asset(std::move(item.asset));
                    timeline_.append_clip(ffgui::Clip{
                        std::move(item.clip_id), assetId, 0, duration});
                    if (selected_clip_id_.isEmpty()) {
                        selected_clip_id_ = QString::fromStdString(timeline_.clips().back().id);
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
#ifdef FFGUI_HAS_GES
    player_ = std::make_unique<ffgui::GesSequencePlayer>("d3d11videosink", "wasapi2sink");
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
}

EditorController::~EditorController() = default;

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

qint64 EditorController::durationNs() const noexcept {
    return static_cast<qint64>(timeline_.duration());
}

void EditorController::setVideoWindow(QWindow* window) {
    video_window_ = window;
    if (video_window_ == nullptr) {
        return;
    }
    video_window_->create();
#ifdef FFGUI_HAS_GES
    player_->set_video_window_handle(static_cast<std::uintptr_t>(video_window_->winId()));
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
            const auto serial = std::to_string(generated_asset_id_);
            requests.push_back(Request{
                info.absoluteFilePath(), std::move(assetId), "clip-" + serial});
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
                    result.push_back(PendingImport{
                        ffgui::analyze_media(
                            ffprobe, ffmpeg, request.path, std::move(request.asset_id)),
                        clipId});
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

void EditorController::stop() {
#ifdef FFGUI_HAS_GES
    player_->stop();
#endif
    playhead_ns_ = 0;
    emit playheadChanged();
}

void EditorController::selectClip(const QString& clipId) {
    if (selected_clip_id_ == clipId) {
        return;
    }
    selected_clip_id_ = clipId;
    emit selectedClipChanged();
}

void EditorController::trimClip(const QString& clipId, qint64 sourceIn, qint64 duration) {
    try {
        timeline_.trim_clip(clipId.toStdString(), sourceIn, duration);
        selected_clip_id_ = clipId;
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::moveClip(const QString& clipId, int insertionIndex) {
    try {
        timeline_.move_clip(clipId.toStdString(), static_cast<std::size_t>(std::max(0, insertionIndex)));
        selected_clip_id_ = clipId;
        publishTimeline();
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
        const auto serial = std::to_string(++generated_clip_id_);
        const auto left = mapped->clip_id + "-left-" + serial;
        const auto right = mapped->clip_id + "-right-" + serial;
        timeline_.split_at(playhead_ns_, left, right);
        selected_clip_id_ = QString::fromStdString(right);
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::deleteSelectedClip() {
    if (selected_clip_id_.isEmpty()) {
        return;
    }
    try {
        timeline_.erase_clip(selected_clip_id_.toStdString());
        selected_clip_id_ = timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id);
        publishTimeline();
    } catch (const std::exception& error) {
        setStatus(QString::fromUtf8(error.what()));
    }
}

void EditorController::undo() {
    if (timeline_.undo()) {
        selected_clip_id_ = timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id);
        publishTimeline();
    }
}

void EditorController::redo() {
    if (timeline_.redo()) {
        selected_clip_id_ = timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id);
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
            assets.push_back(QJsonObject{
                {"id", QString::fromStdString(id)},
                {"path", QString::fromStdWString(asset.path().wstring())},
                {"durationNs", timeString(asset.duration())},
                {"framePtsNs", framePts},
                {"audioPeaks", audioPeaks}});
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
        for (const auto value : root.value("assets").toArray()) {
            const auto object = value.toObject();
            std::vector<ffgui::TimeNs> framePts;
            for (const auto pts : object.value("framePtsNs").toArray()) {
                framePts.push_back(parseTime(pts, "framePtsNs"));
            }
            std::vector<float> audioPeaks;
            for (const auto peak : object.value("audioPeaks").toArray()) {
                audioPeaks.push_back(static_cast<float>(peak.toDouble()));
            }
            loaded.add_asset(ffgui::MediaAsset{
                object.value("id").toString().toStdString(),
                std::filesystem::path(object.value("path").toString().toStdWString()),
                parseTime(object.value("durationNs"), "durationNs"),
                std::move(framePts),
                std::move(audioPeaks)});
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
        selected_clip_id_ = timeline_.clips().empty()
            ? QString{}
            : QString::fromStdString(timeline_.clips().front().id);
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

void EditorController::publishTimeline(bool resetPlayhead) {
#ifdef FFGUI_HAS_GES
    if (playing_) {
        player_->stop();
    }
#endif
    if (resetPlayhead) {
        playhead_ns_ = 0;
    } else {
        playhead_ns_ = std::clamp<qint64>(playhead_ns_, 0, durationNs());
    }
#ifdef FFGUI_HAS_GES
    player_->set_timeline(timeline_.snapshot());
    if (playhead_ns_ > 0 && playhead_ns_ < durationNs()) {
        player_->seek(playhead_ns_);
    }
#endif
    emit timelineChanged();
    emit playheadChanged();
    emit selectedClipChanged();
    emit historyChanged();
    setStatus(timeline_.clips().empty() ? "미디어를 추가하세요" : "재생 준비 완료");
}

void EditorController::setStatus(QString status) {
    if (status_ == status) {
        return;
    }
    status_ = std::move(status);
    emit statusChanged();
}
