#pragma once

#include <QQuickItem>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>

class QWheelEvent;

class TimelineView : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QVariantList clips READ clips WRITE setClips NOTIFY clipsChanged)
    Q_PROPERTY(qint64 durationNs READ durationNs WRITE setDurationNs NOTIFY durationNsChanged)
    Q_PROPERTY(qint64 playheadNs READ playheadNs WRITE setPlayheadNs NOTIFY playheadNsChanged)
    Q_PROPERTY(QString selectedClipId READ selectedClipId WRITE setSelectedClipId NOTIFY selectedClipIdChanged)
    Q_PROPERTY(qreal zoomLevel READ zoomLevel WRITE setZoomLevel NOTIFY zoomLevelChanged)
    Q_PROPERTY(qint64 viewportStartNs READ viewportStartNs NOTIFY viewportChanged)
    Q_PROPERTY(qint64 viewportDurationNs READ visibleDurationNs NOTIFY viewportChanged)

public:
    explicit TimelineView(QQuickItem* parent = nullptr);

    [[nodiscard]] QVariantList clips() const { return clips_; }
    void setClips(QVariantList clips);

    [[nodiscard]] qint64 durationNs() const noexcept { return duration_ns_; }
    void setDurationNs(qint64 duration);

    [[nodiscard]] qint64 playheadNs() const noexcept { return playhead_ns_; }
    void setPlayheadNs(qint64 position);

    [[nodiscard]] QString selectedClipId() const { return selected_clip_id_; }
    void setSelectedClipId(QString clipId);

    [[nodiscard]] qreal zoomLevel() const noexcept { return zoom_level_; }
    void setZoomLevel(qreal zoom);
    [[nodiscard]] qint64 viewportStartNs() const noexcept { return viewport_start_ns_; }
    [[nodiscard]] qint64 visibleDurationNs() const;

signals:
    void clipsChanged();
    void durationNsChanged();
    void playheadNsChanged();
    void selectedClipIdChanged();
    void zoomLevelChanged();
    void viewportChanged();
    void seekRequested(qint64 timelineTime);
    void clipSelected(QString clipId);
    void trimCommitted(QString clipId, qint64 sourceIn, qint64 duration);
    void moveCommitted(QString clipId, int insertionIndex);

protected:
    QSGNode* updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) override;
    void geometryChange(const QRectF& newGeometry, const QRectF& oldGeometry) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;

private:
    void seekAt(qreal x);
    [[nodiscard]] QVariantList previewClips() const;
    [[nodiscard]] int clipIndexAt(qreal x) const;
    [[nodiscard]] qint64 timeAt(qreal x) const;
    void clampViewport();

    enum class DragMode { none, trim_left, trim_right, move };

    QVariantList clips_;
    qint64 duration_ns_{};
    qint64 playhead_ns_{};
    QString selected_clip_id_;
    DragMode drag_mode_{DragMode::none};
    int drag_clip_index_{-1};
    qreal drag_origin_x_{};
    qint64 drag_delta_ns_{};
    int move_target_index_{};
    qreal zoom_level_{1.0};
    qint64 viewport_start_ns_{};
    bool timeline_geometry_dirty_{true};
    qint64 painted_view_start_ns_{};
    qint64 painted_view_duration_ns_{1};
};
