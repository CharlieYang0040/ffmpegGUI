#pragma once

#include "core/timeline_model.hpp"
#include "core/color_pipeline.hpp"
#include "color/scope_analyzer.hpp"
#include "export/ffmpeg_export_plan.hpp"
#include "media/oiio_frame_source.hpp"
#include "render/timeline_frame_server.hpp"

#ifdef FFGUI_HAS_GES
#include "integration/ges/ges_sequence_player.hpp"
#endif

#include <QObject>
#include <QFutureWatcher>
#include <QHash>
#include <QImage>
#include <QElapsedTimer>
#include <QProcess>
#include <QStringList>
#include <QTimer>
#include <QVariantList>
#include <QUrl>
#include <QWindow>
#include <QtQml/qqmlregistration.h>

#include <memory>
#include <atomic>
#include <mutex>
#include <optional>
#include <utility>

class QQmlEngine;
class QJSEngine;
class QFile;

class EditorController final : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(QVariantList clips READ clips NOTIFY clipsChanged)
    Q_PROPERTY(QVariantList mediaAssets READ mediaAssets NOTIFY mediaAssetsChanged)
    Q_PROPERTY(QVariantList captions READ captions NOTIFY captionsChanged)
    Q_PROPERTY(qint64 durationNs READ durationNs NOTIFY timelineChanged)
    Q_PROPERTY(qint64 playheadNs READ playheadNs NOTIFY playheadChanged)
    Q_PROPERTY(qint64 inPointNs READ inPointNs NOTIFY rangeChanged)
    Q_PROPERTY(qint64 outPointNs READ outPointNs NOTIFY rangeChanged)
    Q_PROPERTY(QString selectedSourceAssetId READ selectedSourceAssetId NOTIFY sourceViewerChanged)
    Q_PROPERTY(QString sourceAssetName READ sourceAssetName NOTIFY sourceViewerChanged)
    Q_PROPERTY(qint64 sourceDurationNs READ sourceDurationNs NOTIFY sourceViewerChanged)
    Q_PROPERTY(qint64 sourcePositionNs READ sourcePositionNs NOTIFY sourceViewerChanged)
    Q_PROPERTY(qint64 sourceInNs READ sourceInNs NOTIFY sourceViewerChanged)
    Q_PROPERTY(qint64 sourceOutNs READ sourceOutNs NOTIFY sourceViewerChanged)
    Q_PROPERTY(bool sourceViewerOpen READ sourceViewerOpen NOTIFY sourceViewerChanged)
    Q_PROPERTY(bool sourcePlaying READ sourcePlaying NOTIFY sourceViewerChanged)
    Q_PROPERTY(bool playing READ playing NOTIFY playingChanged)
    Q_PROPERTY(qreal shuttleRate READ shuttleRate NOTIFY shuttleRateChanged)
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
    Q_PROPERTY(bool gpuSceneGraphPreview READ gpuSceneGraphPreview NOTIFY previewPathChanged)
    Q_PROPERTY(bool cpuPreviewFallback READ cpuPreviewFallback NOTIFY previewPathChanged)
    Q_PROPERTY(bool inProcessPreview READ inProcessPreview CONSTANT)
    Q_PROPERTY(bool exporting READ exporting NOTIFY exportingChanged)
    Q_PROPERTY(qreal exportProgress READ exportProgress NOTIFY exportProgressChanged)
    Q_PROPERTY(QString exportStage READ exportStage NOTIFY exportProgressChanged)
    Q_PROPERTY(QString exportOutputName READ exportOutputName NOTIFY exportProgressChanged)
    Q_PROPERTY(QString outputDirectory READ outputDirectory NOTIFY exportSettingsChanged)
    Q_PROPERTY(QString nextOutputName READ nextOutputName NOTIFY exportSettingsChanged)
    Q_PROPERTY(bool outputDirectoryValid READ outputDirectoryValid NOTIFY exportSettingsChanged)
    Q_PROPERTY(QString outputDirectoryError READ outputDirectoryError NOTIFY exportSettingsChanged)
    Q_PROPERTY(QString exportElapsedText READ exportElapsedText NOTIFY exportProgressChanged)
    Q_PROPERTY(QString exportRemainingText READ exportRemainingText NOTIFY exportProgressChanged)
    Q_PROPERTY(int missingFrameCount READ missingFrameCount NOTIFY timelineChanged)
    Q_PROPERTY(int colorPipelineMode READ colorPipelineMode WRITE setColorPipelineMode NOTIFY colorPipelineChanged)
    Q_PROPERTY(QStringList inputColorSpaceOptions READ inputColorSpaceOptions NOTIFY colorPipelineChanged)
    Q_PROPERTY(QString customOcioPath READ customOcioPath NOTIFY colorPipelineChanged)
    Q_PROPERTY(bool hdrMonitoring READ hdrMonitoring WRITE setHdrMonitoring NOTIFY colorPipelineChanged)
    Q_PROPERTY(int hdrPeakNits READ hdrPeakNits WRITE setHdrPeakNits NOTIFY colorPipelineChanged)
    Q_PROPERTY(int sdrWhiteNits READ sdrWhiteNits WRITE setSdrWhiteNits NOTIFY colorPipelineChanged)
    Q_PROPERTY(int maxCll READ maxCll WRITE setMaxCll NOTIFY colorPipelineChanged)
    Q_PROPERTY(int maxFall READ maxFall WRITE setMaxFall NOTIFY colorPipelineChanged)
    Q_PROPERTY(QString hdrDisplayStatus READ hdrDisplayStatus NOTIFY colorPipelineChanged)
    Q_PROPERTY(QString monitorIccPath READ monitorIccPath NOTIFY colorPipelineChanged)
    Q_PROPERTY(QString colorPipelineSummary READ colorPipelineSummary NOTIFY colorPipelineChanged)
    Q_PROPERTY(QString displayName READ displayName WRITE setDisplayName NOTIFY colorPipelineChanged)
    Q_PROPERTY(QString viewName READ viewName WRITE setViewName NOTIFY colorPipelineChanged)
    Q_PROPERTY(QStringList displayOptions READ displayOptions NOTIFY colorPipelineChanged)
    Q_PROPERTY(QStringList viewOptions READ viewOptions NOTIFY colorPipelineChanged)
    Q_PROPERTY(bool displayTransformBypassed READ displayTransformBypassed WRITE setDisplayTransformBypassed NOTIFY colorPipelineChanged)
    Q_PROPERTY(bool previewCompareEnabled READ previewCompareEnabled WRITE setPreviewCompareEnabled NOTIFY colorPipelineChanged)
    Q_PROPERTY(int lookExportCubeSize READ lookExportCubeSize WRITE setLookExportCubeSize NOTIFY lookExportChanged)
    Q_PROPERTY(int lookExportEncoding READ lookExportEncoding WRITE setLookExportEncoding NOTIFY lookExportChanged)
    Q_PROPERTY(bool lookExportUnrealBundle READ lookExportUnrealBundle WRITE setLookExportUnrealBundle NOTIFY lookExportChanged)
    Q_PROPERTY(QString shotStillPath READ shotStillPath NOTIFY shotLibraryChanged)
    Q_PROPERTY(int shotCompareMode READ shotCompareMode WRITE setShotCompareMode NOTIFY shotLibraryChanged)
    Q_PROPERTY(QVariantList selectedGradeNodes READ selectedGradeNodes NOTIFY gradeUiChanged)
    Q_PROPERTY(bool gradeClipboardAvailable READ gradeClipboardAvailable NOTIFY gradeClipboardChanged)
    Q_PROPERTY(bool scopesVisible READ scopesVisible WRITE setScopesVisible NOTIFY scopeSettingsChanged)
    Q_PROPERTY(int scopeMode READ scopeMode WRITE setScopeMode NOTIFY scopeSettingsChanged)
    Q_PROPERTY(int scopeReferenceStage READ scopeReferenceStage WRITE setScopeReferenceStage NOTIFY scopeSettingsChanged)
    Q_PROPERTY(int reviewOverlayMode READ reviewOverlayMode WRITE setReviewOverlayMode NOTIFY scopeSettingsChanged)
    Q_PROPERTY(QString pixelInspectorText READ pixelInspectorText NOTIFY scopeFrameChanged)
    Q_PROPERTY(QString scopeStageHint READ scopeStageHint NOTIFY scopeFrameChanged)
    Q_PROPERTY(qreal outOfGamutPercent READ outOfGamutPercent NOTIFY scopeFrameChanged)
    Q_PROPERTY(quint64 scopeFramesAnalyzed READ scopeFramesAnalyzed NOTIFY scopeFrameChanged)
    Q_PROPERTY(int exportQuality READ exportQuality WRITE setExportQuality NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportCodec READ exportCodec WRITE setExportCodec NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportContainer READ exportContainer WRITE setExportContainer NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportResolution READ exportResolution WRITE setExportResolution NOTIFY exportSettingsChanged)
    Q_PROPERTY(int exportFrameRate READ exportFrameRate WRITE setExportFrameRate NOTIFY exportSettingsChanged)
    Q_PROPERTY(int gifPreset READ gifPreset WRITE setGifPreset NOTIFY exportSettingsChanged)
    Q_PROPERTY(int gifResolution READ gifResolution WRITE setGifResolution NOTIFY exportSettingsChanged)
    Q_PROPERTY(int gifFrameRate READ gifFrameRate WRITE setGifFrameRate NOTIFY exportSettingsChanged)
    Q_PROPERTY(int gifColors READ gifColors WRITE setGifColors NOTIFY exportSettingsChanged)
    Q_PROPERTY(int gifDither READ gifDither WRITE setGifDither NOTIFY exportSettingsChanged)
    Q_PROPERTY(bool gifLoop READ gifLoop WRITE setGifLoop NOTIFY exportSettingsChanged)
    Q_PROPERTY(QString gifEstimatedSizeText READ gifEstimatedSizeText NOTIFY gifEstimateChanged)
    Q_PROPERTY(int gifSizeRisk READ gifSizeRisk NOTIFY gifEstimateChanged)

public:
    explicit EditorController(QObject* parent);
    ~EditorController() override;

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

public:

    [[nodiscard]] QVariantList clips() const;
    [[nodiscard]] QVariantList mediaAssets() const;
    [[nodiscard]] QVariantList captions() const;
    [[nodiscard]] qint64 durationNs() const noexcept;
    [[nodiscard]] qint64 playheadNs() const noexcept { return playhead_ns_; }
    [[nodiscard]] qint64 inPointNs() const noexcept { return in_point_ns_; }
    [[nodiscard]] qint64 outPointNs() const noexcept { return out_point_ns_; }
    [[nodiscard]] QString selectedSourceAssetId() const { return selected_source_asset_id_; }
    [[nodiscard]] QString sourceAssetName() const;
    [[nodiscard]] qint64 sourceDurationNs() const;
    [[nodiscard]] qint64 sourcePositionNs() const noexcept { return source_position_ns_; }
    [[nodiscard]] qint64 sourceInNs() const;
    [[nodiscard]] qint64 sourceOutNs() const;
    [[nodiscard]] bool sourceViewerOpen() const noexcept { return source_viewer_open_; }
    [[nodiscard]] bool sourcePlaying() const noexcept { return source_playing_; }
    [[nodiscard]] bool playing() const noexcept { return playing_; }
    [[nodiscard]] qreal shuttleRate() const noexcept { return shuttle_rate_; }
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
    [[nodiscard]] bool cpuPreviewFallback() const noexcept { return cpu_preview_fallback_; }
    [[nodiscard]] bool inProcessPreview() const noexcept { return in_process_preview_; }
    [[nodiscard]] bool exporting() const noexcept { return exporting_; }
    [[nodiscard]] qreal exportProgress() const noexcept { return export_progress_; }
    [[nodiscard]] QString exportStage() const { return export_stage_; }
    [[nodiscard]] QString exportOutputName() const { return export_output_name_; }
    [[nodiscard]] QString outputDirectory() const { return output_directory_; }
    [[nodiscard]] QString nextOutputName() const;
    [[nodiscard]] bool outputDirectoryValid() const;
    [[nodiscard]] QString outputDirectoryError() const;
    [[nodiscard]] QString exportElapsedText() const;
    [[nodiscard]] QString exportRemainingText() const;
    [[nodiscard]] int missingFrameCount() const;
    [[nodiscard]] int colorPipelineMode() const noexcept {
        return static_cast<int>(color_pipeline_.mode);
    }
    [[nodiscard]] QString customOcioPath() const {
        return QString::fromStdString(color_pipeline_.ocio_config_path);
    }
    [[nodiscard]] bool hdrMonitoring() const noexcept { return color_pipeline_.hdr_monitoring; }
    [[nodiscard]] int hdrPeakNits() const noexcept { return color_pipeline_.hdr_peak_nits; }
    [[nodiscard]] int sdrWhiteNits() const noexcept { return color_pipeline_.sdr_white_nits; }
    [[nodiscard]] int maxCll() const noexcept { return color_pipeline_.max_cll; }
    [[nodiscard]] int maxFall() const noexcept { return color_pipeline_.max_fall; }
    [[nodiscard]] QString hdrDisplayStatus() const { return hdr_display_status_; }
    [[nodiscard]] QString monitorIccPath() const {
        return QString::fromStdString(color_pipeline_.monitor_icc_path);
    }
    [[nodiscard]] QString colorPipelineSummary() const;
    [[nodiscard]] QString displayName() const {
        return QString::fromStdString(color_pipeline_.display);
    }
    [[nodiscard]] QString viewName() const {
        return QString::fromStdString(color_pipeline_.view);
    }
    [[nodiscard]] bool displayTransformBypassed() const noexcept {
        return color_pipeline_.display_transform_bypassed;
    }
    [[nodiscard]] bool previewCompareEnabled() const noexcept { return preview_compare_enabled_; }
    [[nodiscard]] int lookExportCubeSize() const noexcept { return look_export_cube_size_; }
    [[nodiscard]] int lookExportEncoding() const noexcept { return look_export_encoding_; }
    [[nodiscard]] bool lookExportUnrealBundle() const noexcept { return look_export_unreal_bundle_; }
    [[nodiscard]] QString shotStillPath() const { return shot_still_path_; }
    [[nodiscard]] int shotCompareMode() const noexcept { return shot_compare_mode_; }
    [[nodiscard]] QVariantList selectedGradeNodes() const;
    [[nodiscard]] bool gradeClipboardAvailable() const noexcept {
        return grade_node_clipboard_.has_value();
    }
    [[nodiscard]] bool scopesVisible() const noexcept { return scopes_visible_; }
    [[nodiscard]] int scopeMode() const noexcept { return scope_mode_; }
    [[nodiscard]] int scopeReferenceStage() const noexcept { return scope_reference_stage_; }
    [[nodiscard]] int reviewOverlayMode() const noexcept {
        return static_cast<int>(review_overlay_mode_);
    }
    [[nodiscard]] QString pixelInspectorText() const { return pixel_inspector_text_; }
    [[nodiscard]] QString scopeStageHint() const;
    [[nodiscard]] qreal outOfGamutPercent() const noexcept { return out_of_gamut_percent_; }
    [[nodiscard]] quint64 scopeFramesAnalyzed() const noexcept { return scope_frames_analyzed_; }
    [[nodiscard]] int exportQuality() const noexcept { return export_quality_; }
    [[nodiscard]] int exportCodec() const noexcept { return export_codec_; }
    [[nodiscard]] int exportContainer() const noexcept { return export_container_; }
    [[nodiscard]] int exportResolution() const noexcept { return export_resolution_; }
    [[nodiscard]] int exportFrameRate() const noexcept { return export_frame_rate_; }
    [[nodiscard]] int gifPreset() const noexcept { return gif_preset_; }
    [[nodiscard]] int gifResolution() const noexcept { return gif_resolution_; }
    [[nodiscard]] int gifFrameRate() const noexcept { return gif_frame_rate_; }
    [[nodiscard]] int gifColors() const noexcept { return gif_colors_; }
    [[nodiscard]] int gifDither() const noexcept { return gif_dither_; }
    [[nodiscard]] bool gifLoop() const noexcept { return gif_loop_; }
    [[nodiscard]] QString gifEstimatedSizeText() const;
    [[nodiscard]] int gifSizeRisk() const noexcept;
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
    [[nodiscard]] std::uint64_t audioBuffersReceived() const noexcept;
    [[nodiscard]] std::uint64_t videoFramesReceived() const noexcept;
    [[nodiscard]] std::uint64_t previewRebuildCount() const noexcept {
        return preview_rebuild_count_;
    }
    [[nodiscard]] std::uint64_t previewColorUpdateCount() const noexcept {
        return preview_color_update_count_;
    }
    [[nodiscard]] std::uint64_t scrubFramesSubmitted() const noexcept {
        return scrub_frames_submitted_;
    }
    [[nodiscard]] std::uint64_t floatVideoFramesProcessed() const noexcept {
        return float_video_frames_processed_;
    }
    [[nodiscard]] std::uint64_t sourceColorLutBindings() const noexcept;
    [[nodiscard]] std::uint64_t sourceGpuColorLutBindings() const noexcept;
    [[nodiscard]] bool directD3dCompositorEnabled() const noexcept;
    [[nodiscard]] std::uint64_t d3dCompositorInstances() const noexcept;
    [[nodiscard]] std::uint64_t d3dDownloadInstances() const noexcept;
    [[nodiscard]] std::uint64_t systemCompositorInstances() const noexcept;
    [[nodiscard]] bool videoSurfaceExposed() const noexcept;
    static EditorController* create(QQmlEngine* engine, QJSEngine* scriptEngine);
    static void setSingletonInstance(EditorController* instance);

    void loadFiles(const QStringList& paths);
    void setVideoWindow(QWindow* window);

public slots:
    void seek(qint64 timelinePosition);
    void scrub(qint64 timelinePosition, bool finalPosition);
    void skim(qint64 timelinePosition, bool active);
    void skimAsset(const QString& assetId, qint64 sourceTime, bool active);
    void togglePlayback();
    void shuttleForward();
    void shuttleReverse();
    void shuttleStop();
    void seekToStart();
    void seekToEnd();
    void seekTimecode(const QString& value);
    void playAround();
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
    void openSourceAsset(const QString& assetId);
    void closeSourceViewer();
    void seekSource(qint64 sourcePosition);
    void toggleSourcePlayback();
    void setSourceInPoint();
    void setSourceOutPoint();
    void clearSourceRange();
    void appendSelectedSource();
    void insertSelectedSource();
    void overwriteSelectedSource();
    void replaceSelectedClipSource();
    void updateExrSelection(
        const QString& assetId,
        const QString& part,
        const QString& view,
        const QString& layer);
    void setAssetInputColorSpace(const QString& assetId, const QString& colorSpace);
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
    void exportTimeline();
    void setOutputDirectoryUrl(const QUrl& url);
    void openOutputDirectory();
    void copyOutputDirectory();
    void setColorPipelineMode(int mode);
    void setCustomOcioUrl(const QUrl& url);
    void setDisplayName(const QString& name);
    void setViewName(const QString& name);
    void setDisplayTransformBypassed(bool bypassed);
    void setPreviewCompareEnabled(bool enabled);
    void setHdrMonitoring(bool enabled);
    void setHdrPeakNits(int nits);
    void setSdrWhiteNits(int nits);
    void setMaxCll(int nits);
    void setMaxFall(int nits);
    Q_INVOKABLE void attachPreviewWindow(QObject* window);
    Q_INVOKABLE void refreshHdrDisplay();
    void addGradeNode(int type);
    void addGradeLutUrl(const QUrl& url);
    void exportLookUrl(const QUrl& url);
    void setLookExportCubeSize(int size);
    void setLookExportEncoding(int encoding);
    void setLookExportUnrealBundle(bool enabled);
    void captureShotStill();
    void clearShotStill();
    void matchSelectedGradeToStill();
    void setShotCompareMode(int mode);
    void removeGradeNode(const QString& nodeId);
    void moveGradeNode(const QString& nodeId, int direction);
    void copyGradeNode(const QString& nodeId);
    void pasteGradeNode();
    void resetGradeNode(const QString& nodeId);
    void makeGradeNodeShared(const QString& nodeId);
    void unlinkGradeNode(const QString& nodeId);
    void setGradeNodeEnabled(const QString& nodeId, bool enabled);
    void setGradeNodeName(const QString& nodeId, const QString& name);
    void setGradeNodeMix(const QString& nodeId, int percent);
    void setGradeParameter(const QString& nodeId, const QString& parameter, double value);
    void toggleGradeParameterKeyframe(const QString& nodeId, const QString& parameter);
    void setGradeCurveMidpoint(
        const QString& nodeId, const QString& curveName, int adjustmentPercent);
    void setScopesVisible(bool visible);
    void setScopeMode(int mode);
    void setScopeReferenceStage(int stage);
    void setReviewOverlayMode(int mode);
    void inspectPreviewPixel(qreal x, qreal y);
    void attachScopeItem(QObject* item);
    void cancelExport();
    void setExportQuality(int quality);
    void setExportCodec(int codec);
    void setExportContainer(int container);
    void setExportResolution(int resolution);
    void setExportFrameRate(int frameRate);
    void setGifPreset(int preset);
    void setGifResolution(int resolution);
    void setGifFrameRate(int frameRate);
    void setGifColors(int colors);
    void setGifDither(int dither);
    void setGifLoop(bool loop);
    void setStampEnabled(bool enabled);
    void setStampWorker(const QString& worker);
    void setStampInformation(const QString& information);
    void setStampBarPercent(int percent);
    void setStampOpacity(int percent);
    void setStampMode(int mode);
    [[nodiscard]] QString exportExtension() const;
    [[nodiscard]] QStringList inputColorSpaceOptions() const;
    [[nodiscard]] QStringList displayOptions() const;
    [[nodiscard]] QStringList viewOptions() const;
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
    void clipsChanged();
    void mediaAssetsChanged();
    void captionsChanged();
    void playheadChanged();
    void rangeChanged();
    void sourceViewerChanged();
    void playingChanged();
    void shuttleRateChanged();
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
    void colorPipelineChanged();
    void lookExportChanged();
    void shotLibraryChanged();
    void previewPathChanged();
    void scopeSettingsChanged();
    void scopeFrameChanged();
    void gradeClipboardChanged();
    void gradeUiChanged();
    void gifEstimateChanged();
    void exportFinished(bool success, QUrl outputUrl);

private:
    struct PendingImport final {
        ffgui::MediaAsset asset;
        std::string clip_id;
        QString thumbnail_atlas;
        bool replace_existing{};
    };

    void publishTimeline(bool resetPlayhead = false);
    void publishColorPreview();
    void touchCoalescedGradeEdit();
    void endCoalescedGradeEdit();
    void commitGradeNodeEdit(
        const std::string& clip_id, ffgui::GradeGraph graph, const std::string& node_id);
    [[nodiscard]] std::optional<ffgui::TimeNs> selectedClipSourceTime() const;
    void setStatus(QString status);
    void queuePreviewOperation(bool restorePosition);
    void startPreviewOperation();
    void startShuttle(qreal rate);
    void requestAudioSkim(qint64 timelinePosition);
    void startAudioSkim();
    void stopAudioSkim(bool restorePosition);
    void cancelAudioSkim();
    [[nodiscard]] std::optional<qint64> timelineTimeForAssetSource(
        const QString& asset_id, qint64 source_time) const;
    [[nodiscard]] bool transportTextInputFocused() const;
    [[nodiscard]] std::optional<std::pair<qint64, qint64>> selectedSourceRange() const;
    [[nodiscard]] qint64 sourceEditTimelinePosition() const;
    [[nodiscard]] std::optional<ffgui::Clip> makeSelectedSourceClip(const std::string& prefix);
    void updateSourcePreview();
    void stopSourcePlayback();
    void queueLiveSeek(qint64 timelinePosition);
    void pumpLiveSeek();
    void submitCachedScrubFrame(qint64 timelinePosition);
    void submitCachedAssetFrame(
        const QString& asset_id, qint64 source_time, qint64 presentation_time);
    bool submitFloatScrubFrame(qint64 timelinePosition);
    void startFloatScrubFrame(qint64 timelinePosition);
    [[nodiscard]] bool canUseFloatPlayback() const;
    void startFloatPlayback();
    void stopFloatPlayback(bool rewindAtEnd = false);
    void advanceFloatPlayback();
    [[nodiscard]] bool requiresFloatVideoPreview() const;
    void submitFloatVideoFrame(ffgui::PreviewVideoFrame frame);
    void startFloatVideoFrame(ffgui::PreviewVideoFrame frame);
    void submitScopeFrame(ffgui::PreviewVideoFrame frame);
    void startScopeFrame(ffgui::PreviewVideoFrame frame);
    void presentPreviewFrame(ffgui::PreviewVideoFrame frame);
    void recoverCpuPreview();
    void syncOutputSpaceFromDisplayView();
    void applyHdrDisplayPath();
    bool selectHdrDisplayView();
    void restoreSdrDisplayView();
    void storeInspectableFrame(const ffgui::PreviewVideoFrame& frame);
    [[nodiscard]] bool canUseFloatExport() const;
    void startFloatExport();
    void startExportProcess(ffgui::ExportVideoEncoder encoder);
    void startExportValidation();
    void finishExport(bool success);
    [[nodiscard]] QString sequenceName() const;
    [[nodiscard]] QString nextOutputPath() const;
    [[nodiscard]] bool ensureOutputDirectory();
    [[nodiscard]] std::string makeUniqueClipId(const std::string& prefix);
    [[nodiscard]] std::string makeUniqueGradeNodeId();
    [[nodiscard]] std::string makeUniqueSharedGradeId();
    void setSingleSelection(QString clipId);
#ifdef FFGUI_HAS_GES
    struct PreviewOperationResult final {
        std::uint64_t generation{};
        bool rebuilt{};
        bool color_only{};
        bool success{};
        QString error;
    };
    struct LiveSeekResult final {
        bool success{};
        QString error;
    };
    struct FloatScrubResult final {
        std::uint64_t generation{};
        ffgui::PreviewVideoFrame frame;
        QString error;
        int requested_frame{};
        int resolved_frame{};
        qint64 elapsed_ms{};
    };
    struct FloatExportResult final {
        bool success{};
        QByteArray error;
    };
    struct FloatVideoResult final {
        std::uint64_t generation{};
        ffgui::PreviewVideoFrame frame;
        QString error;
        qint64 elapsed_ms{};
    };
    struct ScopeResult final {
        std::shared_ptr<ffgui::ScopeAnalysis> analysis;
        QString error;
    };
#endif

    ffgui::TimelineModel timeline_;
    std::vector<ffgui::TimelineSpan> preview_snapshot_;
    std::uint64_t preview_revision_{};
    std::uint64_t preview_generation_{};
    std::optional<std::uint64_t> preview_applied_generation_;
    std::uint64_t preview_rebuild_count_{};
    std::uint64_t preview_color_update_count_{};
    std::uint64_t video_frames_presented_{};
    std::uint64_t video_frames_delivered_{};
    qint64 playhead_ns_{};
    qint64 in_point_ns_{-1};
    qint64 out_point_ns_{-1};
    bool playing_{};
    qreal shuttle_rate_{};
    std::optional<qint64> transport_range_start_;
    std::optional<qint64> transport_range_end_;
    bool transport_range_loop_{};
    bool transport_boundary_pending_{};
    bool j_key_down_{};
    bool k_key_down_{};
    bool l_key_down_{};
    bool scrubbing_{};
    bool preview_busy_{};
    bool preview_failed_{};
    bool preview_suspended_for_export_{};
    QString status_{"미디어를 추가하세요"};
    QString selected_clip_id_;
    QStringList selected_clip_ids_;
    QString selection_anchor_id_;
    std::uint64_t generated_clip_id_{};
    std::uint64_t generated_asset_id_{};
    std::uint64_t generated_caption_id_{};
    std::uint64_t generated_grade_node_id_{};
    std::optional<ffgui::GradeNode> grade_node_clipboard_;
    QString grade_clipboard_source_clip_id_;
    std::uint64_t generated_shared_grade_id_{};
    QString selected_caption_id_;
    bool stamp_enabled_{};
    QString stamp_worker_;
    QString stamp_information_;
    int stamp_bar_percent_{9};
    int stamp_opacity_{90};
    int stamp_mode_{};
    QObject* video_item_{};
    QObject* scope_item_{};
    QWindow* video_window_{};
    QWindow* preview_quick_window_{};
    QString hdr_display_status_;
    std::string saved_display_before_hdr_;
    std::string saved_view_before_hdr_;
    bool hdr_display_override_{};
    bool use_d3d_scene_graph_{};
    bool cpu_preview_fallback_{};
    bool in_process_preview_{};
    bool scopes_visible_{};
    int scope_mode_{};
    int scope_reference_stage_{2};
    ffgui::ReviewOverlayMode review_overlay_mode_{ffgui::ReviewOverlayMode::off};
    bool preview_compare_enabled_{};
    int look_export_cube_size_{33};
    int look_export_encoding_{2};
    bool look_export_unreal_bundle_{true};
    QString shot_still_path_;
    QString shot_still_clip_id_;
    qint64 shot_still_source_time_{};
    int shot_compare_mode_{};
    std::optional<ffgui::FloatImageFrame> shot_still_frame_;
    QString pixel_inspector_text_;
    qreal out_of_gamut_percent_{};
    bool last_scope_approximate_{};
    std::uint32_t inspect_width_{};
    std::uint32_t inspect_height_{};
    std::uint32_t inspect_stride_{};
    std::shared_ptr<std::vector<std::uint8_t>> inspect_bgra_;
    std::vector<float> inspect_rgba_;
    std::mutex inspect_mutex_;
    std::uint64_t scope_frames_analyzed_{};
    bool importing_{};
    QFutureWatcher<std::vector<PendingImport>> import_watcher_;
    QTimer preview_update_timer_;
    QTimer grade_coalesce_timer_;
    QTimer model_update_timer_;
    QTimer selection_update_timer_;
    QTimer float_playback_timer_;
    QTimer audio_skim_debounce_timer_;
    QTimer audio_skim_stop_timer_;
    QTimer source_playback_timer_;
    QElapsedTimer source_playback_clock_;
    qint64 source_playback_origin_ns_{};
    int source_audio_tick_{};
    std::optional<qint64> pending_audio_skim_ns_;
    bool audio_skim_hover_active_{};
    bool audio_skimming_{};
    QString selected_source_asset_id_;
    QHash<QString, QPair<qint64, qint64>> source_ranges_;
    qint64 source_position_ns_{};
    bool source_viewer_open_{};
    bool source_playing_{};
    std::optional<qint64> skim_target_ns_;
    QElapsedTimer float_playback_clock_;
    qint64 float_playback_origin_ns_{};
    bool float_playback_running_{};
#ifdef FFGUI_HAS_GES
    QFutureWatcher<PreviewOperationResult> preview_watcher_;
    QFutureWatcher<LiveSeekResult> live_seek_watcher_;
    std::optional<qint64> pending_preview_seek_;
    std::optional<qint64> pending_live_seek_;
    bool preview_operation_pending_{};
    bool preview_color_only_pending_{};
    bool preview_should_play_{};
    bool preview_stop_requested_{};
    mutable std::mutex pending_video_frame_mutex_;
    std::optional<ffgui::PreviewVideoFrame> pending_video_frame_;
    bool video_frame_delivery_queued_{};
    mutable std::mutex pending_scope_frame_mutex_;
    std::optional<ffgui::PreviewVideoFrame> pending_scope_frame_;
    bool scope_frame_delivery_queued_{};
    ffgui::TimelineFrameServer timeline_frame_server_{512ULL * 1024ULL * 1024ULL};
    QFutureWatcher<FloatScrubResult> float_scrub_watcher_;
    bool float_scrub_active_{};
    std::optional<qint64> pending_float_scrub_ns_;
    std::uint64_t float_scrub_generation_{};
    QFutureWatcher<FloatExportResult> float_export_watcher_;
    std::shared_ptr<std::atomic_bool> float_export_cancel_;
    bool float_export_active_{};
    QFutureWatcher<FloatVideoResult> float_video_watcher_;
    bool float_video_active_{};
    std::uint64_t float_video_frames_processed_{};
    std::optional<ffgui::PreviewVideoFrame> pending_float_video_frame_;
    QFutureWatcher<ScopeResult> scope_watcher_;
    bool scope_active_{};
    std::optional<ffgui::PreviewVideoFrame> pending_scope_analysis_frame_;
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
    QString output_directory_;
    QString current_project_path_;
    QString export_log_path_;
    std::unique_ptr<QFile> export_log_file_;
    ffgui::TimeNs export_duration_ns_{};
    QElapsedTimer export_elapsed_timer_;
    int export_quality_{1};
    int export_codec_{};
    int export_container_{};
    int export_resolution_{};
    int export_frame_rate_{};
    int gif_preset_{1};
    int gif_resolution_{1};
    int gif_frame_rate_{1};
    int gif_colors_{1};
    int gif_dither_{};
    bool gif_loop_{true};
    QString export_concat_path_;
    QString export_subtitle_path_;
    QStringList export_color_lut_paths_;
    ffgui::ColorPipelineSettings color_pipeline_;
    static EditorController* singleton_instance_;
#ifdef FFGUI_HAS_GES
    std::unique_ptr<ffgui::GesSequencePlayer> player_;
#endif
};
