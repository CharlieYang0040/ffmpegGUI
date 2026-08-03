#pragma once

#include "core/timeline_model.hpp"
#include "export/ffmpeg_export_plan.hpp"

#ifdef FFGUI_HAS_GES
#include "integration/ges/ges_sequence_player.hpp"
#endif

#include <QObject>
#include <QFutureWatcher>
#include <QHash>
#include <QProcess>
#include <QStringList>
#include <QVariantList>
#include <QUrl>
#include <QWindow>
#include <QtQml/qqmlregistration.h>

#include <memory>
#include <optional>

class QQmlEngine;
class QJSEngine;

class EditorController final : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(QVariantList clips READ clips NOTIFY timelineChanged)
    Q_PROPERTY(QVariantList mediaAssets READ mediaAssets NOTIFY timelineChanged)
    Q_PROPERTY(qint64 durationNs READ durationNs NOTIFY timelineChanged)
    Q_PROPERTY(qint64 playheadNs READ playheadNs NOTIFY playheadChanged)
    Q_PROPERTY(bool playing READ playing NOTIFY playingChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QString selectedClipId READ selectedClipId NOTIFY selectedClipChanged)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY historyChanged)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY historyChanged)
    Q_PROPERTY(bool importing READ importing NOTIFY importingChanged)
    Q_PROPERTY(QWindow* videoWindow READ videoWindow CONSTANT)
    Q_PROPERTY(bool gpuSceneGraphPreview READ gpuSceneGraphPreview CONSTANT)
    Q_PROPERTY(bool exporting READ exporting NOTIFY exportingChanged)
    Q_PROPERTY(qreal exportProgress READ exportProgress NOTIFY exportProgressChanged)

public:
    explicit EditorController(QObject* parent);
    ~EditorController() override;

    [[nodiscard]] QVariantList clips() const;
    [[nodiscard]] QVariantList mediaAssets() const;
    [[nodiscard]] qint64 durationNs() const noexcept;
    [[nodiscard]] qint64 playheadNs() const noexcept { return playhead_ns_; }
    [[nodiscard]] bool playing() const noexcept { return playing_; }
    [[nodiscard]] QString status() const { return status_; }
    [[nodiscard]] QString selectedClipId() const { return selected_clip_id_; }
    [[nodiscard]] bool canUndo() const noexcept { return timeline_.can_undo(); }
    [[nodiscard]] bool canRedo() const noexcept { return timeline_.can_redo(); }
    [[nodiscard]] bool importing() const noexcept { return importing_; }
    [[nodiscard]] QWindow* videoWindow() const noexcept { return video_window_; }
    [[nodiscard]] bool gpuSceneGraphPreview() const noexcept { return use_d3d_scene_graph_; }
    [[nodiscard]] bool exporting() const noexcept { return exporting_; }
    [[nodiscard]] qreal exportProgress() const noexcept { return export_progress_; }
    [[nodiscard]] bool lastExportUsedStreamCopy() const noexcept {
        return last_export_stream_copy_;
    }
    [[nodiscard]] bool lastExportMatchedPreview() const noexcept {
        return last_export_matched_preview_;
    }
    [[nodiscard]] std::uint64_t videoFramesPresented() const noexcept {
        return video_frames_presented_;
    }
    [[nodiscard]] std::uint64_t videoFramesDelivered() const noexcept {
        return video_frames_delivered_;
    }
    [[nodiscard]] std::uint64_t videoFramesReceived() const noexcept;
    static EditorController* create(QQmlEngine* engine, QJSEngine* scriptEngine);
    static void setSingletonInstance(EditorController* instance);

    void loadFiles(const QStringList& paths);
    void setVideoWindow(QWindow* window);

public slots:
    void seek(qint64 timelinePosition);
    void togglePlayback();
    void stepFrame(int direction);
    void jumpEditPoint(int direction);
    void stop();
    void selectClip(const QString& clipId);
    void trimClip(const QString& clipId, qint64 sourceIn, qint64 duration);
    void moveClip(const QString& clipId, int insertionIndex);
    void insertAssetAtTime(const QString& assetId, qint64 timelinePosition);
    void splitAtPlayhead();
    void duplicateSelectedClip();
    void deleteSelectedClip();
    void undo();
    void redo();
    void saveProject(const QString& path);
    void loadProject(const QString& path);
    void loadUrls(const QList<QUrl>& urls);
    void saveProjectUrl(const QUrl& url);
    void loadProjectUrl(const QUrl& url);
    void exportTimelineUrl(const QUrl& url);
    void cancelExport();
    [[nodiscard]] bool outputExists(const QUrl& url) const;
    [[nodiscard]] QUrl uniqueOutputUrl(const QUrl& url) const;
    void attachVideoItem(QObject* item);

signals:
    void timelineChanged();
    void playheadChanged();
    void playingChanged();
    void statusChanged();
    void selectedClipChanged();
    void historyChanged();
    void importingChanged();
    void mediaImportFinished(bool success);
    void exportingChanged();
    void exportProgressChanged();
    void exportFinished(bool success, QUrl outputUrl);

private:
    struct PendingImport final {
        ffgui::MediaAsset asset;
        std::string clip_id;
        QString thumbnail_atlas;
    };

    void publishTimeline(bool resetPlayhead = false);
    void setStatus(QString status);
    void startExportProcess(ffgui::ExportVideoEncoder encoder);
    void finishExport(bool success);
    [[nodiscard]] std::string makeUniqueClipId(const std::string& prefix);

    ffgui::TimelineModel timeline_;
    std::vector<ffgui::TimelineSpan> preview_snapshot_;
    std::uint64_t preview_revision_{};
    std::uint64_t video_frames_presented_{};
    std::uint64_t video_frames_delivered_{};
    qint64 playhead_ns_{};
    bool playing_{};
    QString status_{"미디어를 추가하세요"};
    QString selected_clip_id_;
    std::uint64_t generated_clip_id_{};
    std::uint64_t generated_asset_id_{};
    QObject* video_item_{};
    QWindow* video_window_{};
    bool use_d3d_scene_graph_{};
    bool importing_{};
    QFutureWatcher<std::vector<PendingImport>> import_watcher_;
    QHash<QString, QString> thumbnail_atlases_;
    QProcess export_process_;
    std::optional<ffgui::ExportRequest> export_request_;
    QByteArray export_stderr_;
    bool exporting_{};
    bool export_cpu_fallback_{};
    bool export_cancelled_{};
    bool export_stream_copy_active_{};
    bool last_export_stream_copy_{};
    bool last_export_matched_preview_{};
    qreal export_progress_{};
    ffgui::TimeNs export_duration_ns_{};
    QString export_concat_path_;
    static EditorController* singleton_instance_;
#ifdef FFGUI_HAS_GES
    std::unique_ptr<ffgui::GesSequencePlayer> player_;
#endif
};
