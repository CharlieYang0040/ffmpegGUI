#pragma once

#include "core/timeline_model.hpp"

#ifdef FFGUI_HAS_GES
#include "integration/ges/ges_sequence_player.hpp"
#endif

#include <QObject>
#include <QFutureWatcher>
#include <QHash>
#include <QStringList>
#include <QVariantList>
#include <QWindow>
#include <QUrl>
#include <QtQml/qqmlregistration.h>

#include <memory>

class QQmlEngine;
class QJSEngine;

class EditorController final : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(QVariantList clips READ clips NOTIFY timelineChanged)
    Q_PROPERTY(qint64 durationNs READ durationNs NOTIFY timelineChanged)
    Q_PROPERTY(qint64 playheadNs READ playheadNs NOTIFY playheadChanged)
    Q_PROPERTY(bool playing READ playing NOTIFY playingChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QString selectedClipId READ selectedClipId NOTIFY selectedClipChanged)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY historyChanged)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY historyChanged)
    Q_PROPERTY(QWindow* videoWindow READ videoWindow CONSTANT)
    Q_PROPERTY(bool importing READ importing NOTIFY importingChanged)

public:
    explicit EditorController(QObject* parent);
    ~EditorController() override;

    [[nodiscard]] QVariantList clips() const;
    [[nodiscard]] qint64 durationNs() const noexcept;
    [[nodiscard]] qint64 playheadNs() const noexcept { return playhead_ns_; }
    [[nodiscard]] bool playing() const noexcept { return playing_; }
    [[nodiscard]] QString status() const { return status_; }
    [[nodiscard]] QString selectedClipId() const { return selected_clip_id_; }
    [[nodiscard]] bool canUndo() const noexcept { return timeline_.can_undo(); }
    [[nodiscard]] bool canRedo() const noexcept { return timeline_.can_redo(); }
    [[nodiscard]] QWindow* videoWindow() const noexcept { return video_window_; }
    [[nodiscard]] bool importing() const noexcept { return importing_; }
    static EditorController* create(QQmlEngine* engine, QJSEngine* scriptEngine);
    static void setSingletonInstance(EditorController* instance);

    void setVideoWindow(QWindow* window);
    void loadFiles(const QStringList& paths);

public slots:
    void seek(qint64 timelinePosition);
    void togglePlayback();
    void stop();
    void selectClip(const QString& clipId);
    void trimClip(const QString& clipId, qint64 sourceIn, qint64 duration);
    void moveClip(const QString& clipId, int insertionIndex);
    void splitAtPlayhead();
    void deleteSelectedClip();
    void undo();
    void redo();
    void saveProject(const QString& path);
    void loadProject(const QString& path);
    void loadUrls(const QList<QUrl>& urls);
    void saveProjectUrl(const QUrl& url);
    void loadProjectUrl(const QUrl& url);

signals:
    void timelineChanged();
    void playheadChanged();
    void playingChanged();
    void statusChanged();
    void selectedClipChanged();
    void historyChanged();
    void importingChanged();
    void mediaImportFinished(bool success);

private:
    struct PendingImport final {
        ffgui::MediaAsset asset;
        std::string clip_id;
        QString thumbnail_atlas;
    };

    void publishTimeline(bool resetPlayhead = false);
    void setStatus(QString status);

    ffgui::TimelineModel timeline_;
    qint64 playhead_ns_{};
    bool playing_{};
    QString status_{"미디어를 추가하세요"};
    QString selected_clip_id_;
    std::uint64_t generated_clip_id_{};
    std::uint64_t generated_asset_id_{};
    QWindow* video_window_{};
    bool importing_{};
    QFutureWatcher<std::vector<PendingImport>> import_watcher_;
    QHash<QString, QString> thumbnail_atlases_;
    static EditorController* singleton_instance_;
#ifdef FFGUI_HAS_GES
    std::unique_ptr<ffgui::GesSequencePlayer> player_;
#endif
};
