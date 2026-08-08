#pragma once

#include "core/timeline_model.hpp"
#include "export/ffmpeg_export_plan.hpp"

#ifdef FFGUI_HAS_GES
#include "integration/ges/ges_sequence_player.hpp"
#endif

#include <QObject>
#include <QFutureWatcher>
#include <QHash>
#include <QImage>
#include <QProcess>
#include <QStringList>
#include <QTimer>
#include <QVariantList>
#include <QUrl>
#include <QWindow>
#include <QtQml/qqmlregistration.h>

#include <memory>
#include <mutex>
#include <optional>

class QQmlEngine;
class QJSEngine;
class QFile;

class EditorController final : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(QVariantList clips READ clips NOTIFY timelineChanged)
    Q_PROPERTY(QVariantList mediaAssets READ mediaAssets NOTIFY timelineChanged)
    Q_PROPERTY(QVariantList captions READ captions NOTIFY timelineChanged)
    Q_PROPERTY(qint64 durationNs READ durationNs NOTIFY timelineChanged)
    Q_PROPERTY(qint64 playheadNs READ playheadNs NOTIFY playheadChanged)
    Q_PROPERTY(qint64 inPointNs READ inPointNs NOTIFY rangeChanged)
    Q_PROPERTY(qint64 outPointNs READ outPointNs NOTIFY rangeChanged)
    Q_PROPERTY(bool playing READ playing NOTIFY playingChanged)
    Q_PROPERTY(bool previewBusy READ previewBusy NOTIFY previewBusyChanged)
    Q_PROPERTY(bool previewFailed READ previewFailed NOTIFY previewFailedChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QString selectedClipId READ selectedClipId NOTIFY selectedClipChanged)
    Q_PROPERTY(QStringList selectedClipIds READ selectedClipIds NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipVolumePercent READ selectedClipVolumePercent NOTIFY selectedClipChanged)
    Q_PROPERTY(bool selectedClipMuted READ selectedClipMuted NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipFadeInMs READ selectedClipFadeInMs NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipFadeOutMs READ selectedClipFadeOutMs NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipSpeedPercent READ selectedClipSpeedPercent NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipBrightness READ selectedClipBrightness NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipContrast READ selectedClipContrast NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipSaturation READ selectedClipSaturation NOTIFY selectedClipChanged)
    Q_PROPERTY(int selectedClipDissolveMs READ selectedClipDissolveMs NOTIFY selectedClipChanged)
    Q_PROPERTY(QString selectedCaptionId READ selectedCaptionId NOTIFY captionSelectionChanged)
    Q_PROPERTY(QString selectedCaptionText READ selectedCaptionText NOTIFY captionSelectionChanged)
    Q_PROPERTY(int selectedCaptionDurationMs READ selectedCaptionDurationMs NOTIFY captionSelectionChanged)
    Q_PROPERTY(int selectedCaptionFontSize READ selectedCaptionFontSize NOTIFY captionSelectionChanged)
    Q_PROPERTY(int selectedCaptionBackgroundOpacity READ selectedCaptionBackgroundOpacity NOTIFY captionSelectionChanged)
    Q_PROPERTY(bool stampEnabled READ stampEnabled WRITE setStampEnabled NOTIFY graphicsChanged)
    Q_PROPERTY(QString stampWorker READ stampWorker WRITE setStampWorker NOTIFY graphicsChanged)
    Q_PROPERTY(QString stampInformation READ stampInformation WRITE setStampInformation NOTIFY graphicsChanged)
    Q_PROPERTY(int stampBarPercent READ stampBarPercent WRITE setStampBarPercent NOTIFY graphicsChanged)
    Q_PROPERTY(int stampOpacity READ stampOpacity WRITE setStampOpacity NOTIFY graphicsChanged)
    Q_PROPERTY(int stampMode READ stampMode WRITE setStampMode NOTIFY graphicsChanged)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY historyChanged)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY historyChanged)
    Q_PROPERTY(bool importing READ importing NOTIFY importingChanged)
    Q_PROPERTY(QWindow* videoWindow READ videoWindow CONSTANT)
    Q_PROPERTY(bool gpuSceneGraphPreview READ gpuSceneGraphPreview CONSTANT)
    Q_PROPERTY(bool inProcessPreview READ inProcessPreview CONSTANT)
    Q_PROPERTY(bool exporting READ exporting NOTIFY exportingChanged)
    Q_PROPERTY(qreal exportProgress READ exportProgress NOTIFY exportProgressChanged)
    Q_PROPERTY(QString exportStage READ exportStage NOTIFY exportProgressChanged)
    Q_PROPERTY(QString exportOutputName READ exportOutputName NOTIFY exportProgressChanged)
    Q_PROPERTY(int exportQuality READ exportQuality WRITE setExportQuality NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportCodec READ exportCodec WRITE setExportCodec NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportContainer READ exportContainer WRITE setExportContainer NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportResolution READ exportResolution WRITE setExportResolution NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportFrameRate READ exportFrameRate WRITE setExportFrameRate NOTIFY exportSettingsChanged)

public:
    explicit EditorController(QObject* parent);
    ~EditorController() override;

    [[nodiscard]] QVariantList clips() const;
    [[nodiscard]] QVariantList mediaAssets() const;
    [[nodiscard]] QVariantList captions() const;
    [[nodiscard]] qint64 durationNs() const noexcept;
    [[nodiscard]] qint64 playheadNs() const noexcept { return playhead_ns_; }
    [[nodiscard]] qint64 inPointNs() const noexcept { return in_point_ns_; }
    [[nodiscard]] qint64 outPointNs() const noexcept { return out_point_ns_; }
    [[nodiscard]] bool playing() const noexcept { return playing_; }
    [[nodiscard]] bool previewBusy() const noexcept { return preview_busy_; }
    [[nodiscard]] bool previewFailed() const noexcept { return preview_failed_; }
    [[nodiscard]] QString status() const { return status_; }
    [[nodiscard]] QString selectedClipId() const { return selected_clip_id_; }
    [[nodiscard]] QStringList selectedClipIds() const { return selected_clip_ids_; }
    [[nodiscard]] int selectedClipVolumePercent() const noexcept;
    [[nodiscard]] bool selectedClipMuted() const noexcept;
    [[nodiscard]] int selectedClipFadeInMs() const noexcept;
    [[nodiscard]] int selectedClipFadeOutMs() const noexcept;
    [[nodiscard]] int selectedClipSpeedPercent() const noexcept;
    [[nodiscard]] int selectedClipBrightness() const noexcept;
    [[nodiscard]] int selectedClipContrast() const noexcept;
    [[nodiscard]] int selectedClipSaturation() const noexcept;
    [[nodiscard]] int selectedClipDissolveMs() const noexcept;
    [[nodiscard]] QString selectedCaptionId() const { return selected_caption_id_; }
    [[nodiscard]] QString selectedCaptionText() const;
    [[nodiscard]] int selectedCaptionDurationMs() const noexcept;
    [[nodiscard]] int selectedCaptionFontSize() const noexcept;
    [[nodiscard]] int selectedCaptionBackgroundOpacity() const noexcept;
    [[nodiscard]] bool stampEnabled() const noexcept { return stamp_enabled_; }
    [[nodiscard]] QString stampWorker() const { return stamp_worker_; }
    [[nodiscard]] QString stampInformation() const { return stamp_information_; }
    [[nodiscard]] int stampBarPercent() const noexcept { return stamp_bar_percent_; }
    [[nodiscard]] int stampOpacity() const noexcept { return stamp_opacity_; }
    [[nodiscard]] int stampMode() const noexcept { return stamp_mode_; }
    [[nodiscard]] bool canUndo() const noexcept { return timeline_.can_undo(); }
    [[nodiscard]] bool canRedo() const noexcept { return timeline_.can_redo(); }
    [[nodiscard]] bool importing() const noexcept { return importing_; }
    [[nodiscard]] QWindow* videoWindow() const noexcept { return video_window_; }
    [[nodiscard]] bool gpuSceneGraphPreview() const noexcept { return use_d3d_scene_graph_; }
    [[nodiscard]] bool inProcessPreview() const noexcept { return in_process_preview_; }
    [[nodiscard]] bool exporting() const noexcept { return exporting_; }
    [[nodiscard]] qreal exportProgress() const noexcept { return export_progress_; }
    [[nodiscard]] QString exportStage() const { return export_stage_; }
    [[nodiscard]] QString exportOutputName() const { return export_output_name_; }
    [[nodiscard]] int exportQuality() const noexcept { return export_quality_; }
    [[nodiscard]] int exportCodec() const noexcept { return export_codec_; }
    [[nodiscard]] int exportContainer() const noexcept { return export_container_; }
    [[nodiscard]] int exportResolution() const noexcept { return export_resolution_; }
    [[nodiscard]] int exportFrameRate() const noexcept { return export_frame_rate_; }
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
    [[nodiscard]] std::uint64_t previewRebuildCount() const noexcept {
        return preview_rebuild_count_;
    }
    [[nodiscard]] std::uint64_t scrubFramesSubmitted() const noexcept {
        return scrub_frames_submitted_;
    }
    [[nodiscard]] bool videoSurfaceExposed() const noexcept;
    static EditorController* create(QQmlEngine* engine, QJSEngine* scriptEngine);
    static void setSingletonInstance(EditorController* instance);

    void loadFiles(const QStringList& paths);
    void setVideoWindow(QWindow* window);

public slots:
    void seek(qint64 timelinePosition);
    void scrub(qint64 timelinePosition, bool finalPosition);
    void togglePlayback();
    void stepFrame(int direction);
    void jumpEditPoint(int direction);
    void setInPoint();
    void setOutPoint();
    void clearRange();
    void extractMarkedRange();
    void stop();
    void selectClip(const QString& clipId, int mode = 0);
    void trimClip(const QString& clipId, qint64 sourceIn, qint64 duration);
    void moveClip(const QString& clipId, int insertionIndex);
    void moveClips(const QStringList& clipIds, int insertionIndex);
    void insertAssetAtTime(const QString& assetId, qint64 timelinePosition);
    void splitAtPlayhead();
    void duplicateSelectedClip();
    void deleteSelectedClip();
    void setSelectedClipVolumePercent(int percent);
    void setSelectedClipMuted(bool muted);
    void setSelectedClipFadeInMs(int milliseconds);
    void setSelectedClipFadeOutMs(int milliseconds);
    void setSelectedClipSpeedPercent(int percent);
    void setSelectedClipBrightness(int percent);
    void setSelectedClipContrast(int percent);
    void setSelectedClipSaturation(int percent);
    void setSelectedClipDissolveMs(int milliseconds);
    void trimAllClipEdges(int frontFrames, int backFrames);
    void addCaptionAtPlayhead();
    void addTextOverlay(const QString& text, int durationMs);
    void selectCaption(const QString& captionId);
    void updateSelectedCaption(const QString& text, int durationMs);
    void updateCaptionPosition(const QString& captionId, qreal positionX, qreal positionY);
    void setSelectedCaptionFontSize(int pixels);
    void setSelectedCaptionBackgroundOpacity(int percent);
    void deleteSelectedCaption();
    void moveCaption(const QString& captionId, qint64 timelineIn);
    void trimCaption(const QString& captionId, qint64 timelineIn, qint64 duration);
    void importSrtUrl(const QUrl& url);
    void exportSrtUrl(const QUrl& url);
    void undo();
    void redo();
    void saveProject(const QString& path);
    void loadProject(const QString& path);
    void loadUrls(const QList<QUrl>& urls);
    void saveProjectUrl(const QUrl& url);
    void loadProjectUrl(const QUrl& url);
    void exportTimelineUrl(const QUrl& url);
    void cancelExport();
    void setExportQuality(int quality);
    void setExportCodec(int codec);
    void setExportContainer(int container);
    void setExportResolution(int resolution);
    void setExportFrameRate(int frameRate);
    void setStampEnabled(bool enabled);
    void setStampWorker(const QString& worker);
    void setStampInformation(const QString& information);
    void setStampBarPercent(int percent);
    void setStampOpacity(int percent);
    void setStampMode(int mode);
    [[nodiscard]] QString exportExtension() const;
    [[nodiscard]] QString timeText(qint64 timelinePosition) const;
    [[nodiscard]] qint64 frameNumberAt(qint64 timelinePosition) const;
    [[nodiscard]] qint64 frameCountBetween(qint64 first, qint64 second) const;
    [[nodiscard]] bool outputExists(const QUrl& url) const;
    [[nodiscard]] QUrl uniqueOutputUrl(const QUrl& url) const;
    void attachVideoItem(QObject* item);
    void refreshVideoWindowHandle();
    void openLogFolder();

signals:
    void timelineChanged();
    void playheadChanged();
    void rangeChanged();
    void playingChanged();
    void previewBusyChanged();
    void previewFailedChanged();
    void statusChanged();
    void selectedClipChanged();
    void captionSelectionChanged();
    void graphicsChanged();
    void historyChanged();
    void importingChanged();
    void mediaImportFinished(bool success);
    void exportingChanged();
    void exportProgressChanged();
    void exportSettingsChanged();
    void exportFinished(bool success, QUrl outputUrl);

private:
    struct PendingImport final {
        ffgui::MediaAsset asset;
        std::string clip_id;
        QString thumbnail_atlas;
    };

    void publishTimeline(bool resetPlayhead = false);
    void setStatus(QString status);
    void queuePreviewOperation(bool restorePosition);
    void startPreviewOperation();
    void submitCachedScrubFrame(qint64 timelinePosition);
    void startExportProcess(ffgui::ExportVideoEncoder encoder);
    void startExportValidation();
    void finishExport(bool success);
    [[nodiscard]] std::string makeUniqueClipId(const std::string& prefix);
    void setSingleSelection(QString clipId);
#ifdef FFGUI_HAS_GES
    struct PreviewOperationResult final {
        std::uint64_t generation{};
        bool rebuilt{};
        bool success{};
        QString error;
    };
#endif

    ffgui::TimelineModel timeline_;
    std::vector<ffgui::TimelineSpan> preview_snapshot_;
    std::uint64_t preview_revision_{};
    std::uint64_t preview_generation_{};
    std::optional<std::uint64_t> preview_applied_generation_;
    std::uint64_t preview_rebuild_count_{};
    std::uint64_t video_frames_presented_{};
    std::uint64_t video_frames_delivered_{};
    qint64 playhead_ns_{};
    qint64 in_point_ns_{-1};
    qint64 out_point_ns_{-1};
    bool playing_{};
    bool preview_busy_{};
    bool preview_failed_{};
    QString status_{"미디어를 추가하세요"};
    QString selected_clip_id_;
    QStringList selected_clip_ids_;
    QString selection_anchor_id_;
    std::uint64_t generated_clip_id_{};
    std::uint64_t generated_asset_id_{};
    std::uint64_t generated_caption_id_{};
    QString selected_caption_id_;
    bool stamp_enabled_{};
    QString stamp_worker_;
    QString stamp_information_;
    int stamp_bar_percent_{9};
    int stamp_opacity_{90};
    int stamp_mode_{};
    QObject* video_item_{};
    QWindow* video_window_{};
    bool use_d3d_scene_graph_{};
    bool in_process_preview_{};
    bool importing_{};
    QFutureWatcher<std::vector<PendingImport>> import_watcher_;
    QTimer preview_update_timer_;
#ifdef FFGUI_HAS_GES
    QFutureWatcher<PreviewOperationResult> preview_watcher_;
    std::optional<qint64> pending_preview_seek_;
    bool preview_operation_pending_{};
    bool preview_should_play_{};
    bool preview_stop_requested_{};
    mutable std::mutex pending_video_frame_mutex_;
    std::optional<ffgui::PreviewVideoFrame> pending_video_frame_;
    bool video_frame_delivery_queued_{};
#endif
    QHash<QString, QString> thumbnail_atlases_;
    QHash<QString, QImage> thumbnail_images_;
    std::uint64_t scrub_frame_serial_{1ULL << 63};
    std::uint64_t scrub_frames_submitted_{};
    mutable std::optional<QVariantList> clips_cache_;
    mutable std::optional<QVariantList> media_assets_cache_;
    mutable std::optional<QVariantList> captions_cache_;
    mutable QHash<QString, QVariantList> waveform_cache_;
    QProcess export_process_;
    QProcess export_validation_process_;
    std::optional<ffgui::ExportRequest> export_request_;
    QByteArray export_stderr_;
    bool exporting_{};
    bool export_cpu_fallback_{};
    bool export_cancelled_{};
    bool export_stream_copy_active_{};
    bool last_export_stream_copy_{};
    bool last_export_matched_preview_{};
    qreal export_progress_{};
    QString export_stage_;
    QString export_output_name_;
    QString export_log_path_;
    std::unique_ptr<QFile> export_log_file_;
    ffgui::TimeNs export_duration_ns_{};
    int export_quality_{1};
    int export_codec_{};
    int export_container_{};
    int export_resolution_{};
    int export_frame_rate_{};
    QString export_concat_path_;
    QString export_subtitle_path_;
    static EditorController* singleton_instance_;
#ifdef FFGUI_HAS_GES
    std::unique_ptr<ffgui::GesSequencePlayer> player_;
#endif
};
