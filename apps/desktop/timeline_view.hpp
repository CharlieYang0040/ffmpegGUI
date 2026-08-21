#pragma once

#include <QQuickItem>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>

class QWheelEvent;
class QHoverEvent;

class TimelineView : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QVariantList clips READ clips WRITE setClips NOTIFY clipsChanged)
    Q_PROPERTY(qint64 durationNs READ durationNs WRITE setDurationNs NOTIFY durationNsChanged)
    Q_PROPERTY(qint64 playheadNs READ playheadNs WRITE setPlayheadNs NOTIFY playheadNsChanged)
    Q_PROPERTY(bool skimmingEnabled READ skimmingEnabled WRITE setSkimmingEnabled NOTIFY skimmingEnabledChanged)
    Q_PROPERTY(bool skimmerActive READ skimmerActive NOTIFY skimmerChanged)
    Q_PROPERTY(qint64 skimmerNs READ skimmerNs NOTIFY skimmerChanged)
    Q_PROPERTY(qint64 inPointNs READ inPointNs WRITE setInPointNs NOTIFY rangeChanged)
    Q_PROPERTY(qint64 outPointNs READ outPointNs WRITE setOutPointNs NOTIFY rangeChanged)
    Q_PROPERTY(QString selectedClipId READ selectedClipId WRITE setSelectedClipId NOTIFY selectedClipIdChanged)
    Q_PROPERTY(QStringList selectedClipIds READ selectedClipIds WRITE setSelectedClipIds NOTIFY selectedClipIdsChanged)
    Q_PROPERTY(qreal zoomLevel READ zoomLevel WRITE setZoomLevel NOTIFY zoomLevelChanged)
    Q_PROPERTY(qint64 viewportStartNs READ viewportStartNs NOTIFY viewportChanged)
    Q_PROPERTY(qint64 viewportDurationNs READ visibleDurationNs NOTIFY viewportChanged)
    Q_PROPERTY(bool interactionActive READ interactionActive NOTIFY interactionFeedbackChanged)
    Q_PROPERTY(QString interactionKind READ interactionKind NOTIFY interactionFeedbackChanged)
    Q_PROPERTY(qint64 interactionTimeNs READ interactionTimeNs NOTIFY interactionFeedbackChanged)
    Q_PROPERTY(qint64 interactionDeltaNs READ interactionDeltaNs NOTIFY interactionFeedbackChanged)
    Q_PROPERTY(qreal interactionX READ interactionX NOTIFY interactionFeedbackChanged)

public:
    explicit TimelineView(QQuickItem* parent = nullptr);

    [[nodiscard]] QVariantList clips() const { return clips_; }
    void setClips(QVariantList clips);

    [[nodiscard]] qint64 durationNs() const noexcept { return duration_ns_; }
    void setDurationNs(qint64 duration);

    [[nodiscard]] qint64 playheadNs() const noexcept { return playhead_ns_; }
    void setPlayheadNs(qint64 position);
    [[nodiscard]] bool skimmingEnabled() const noexcept { return skimming_enabled_; }
    void setSkimmingEnabled(bool enabled);
    [[nodiscard]] bool skimmerActive() const noexcept { return skimmer_active_; }
    [[nodiscard]] qint64 skimmerNs() const noexcept { return skimmer_ns_; }
    [[nodiscard]] qint64 inPointNs() const noexcept { return in_point_ns_; }
    void setInPointNs(qint64 position);
    [[nodiscard]] qint64 outPointNs() const noexcept { return out_point_ns_; }
    void setOutPointNs(qint64 position);

    [[nodiscard]] QString selectedClipId() const { return selected_clip_id_; }
    void setSelectedClipId(QString clipId);
    [[nodiscard]] QStringList selectedClipIds() const { return selected_clip_ids_; }
    void setSelectedClipIds(QStringList clipIds);

    [[nodiscard]] qreal zoomLevel() const noexcept { return zoom_level_; }
    void setZoomLevel(qreal zoom);
    [[nodiscard]] qint64 viewportStartNs() const noexcept { return viewport_start_ns_; }
    [[nodiscard]] qint64 visibleDurationNs() const;
    [[nodiscard]] bool interactionActive() const noexcept { return interaction_active_; }
    [[nodiscard]] QString interactionKind() const { return interaction_kind_; }
    [[nodiscard]] qint64 interactionTimeNs() const noexcept { return interaction_time_ns_; }
    [[nodiscard]] qint64 interactionDeltaNs() const noexcept { return drag_delta_ns_; }
    [[nodiscard]] qreal interactionX() const noexcept { return interaction_x_; }
    Q_INVOKABLE qint64 timelineTimeAt(qreal x) const;
    Q_INVOKABLE void fitToTimeline();

signals:
    void clipsChanged();
    void durationNsChanged();
    void playheadNsChanged();
    void skimmingEnabledChanged();
    void skimmerChanged();
    void rangeChanged();
    void selectedClipIdChanged();
    void selectedClipIdsChanged();
    void zoomLevelChanged();
    void viewportChanged();
    void seekRequested(qint64 timelineTime, bool finalPosition);
    void skimRequested(qint64 timelineTime, bool active);
    void skimCommitted(qint64 timelineTime);
    void clipSelected(QString clipId, int selectionMode);
    void trimCommitted(QString clipId, qint64 sourceIn, qint64 duration);
    void moveCommitted(QStringList clipIds, int insertionIndex);
    void interactionFeedbackChanged();

protected:
    QSGNode* updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) override;
    void geometryChange(const QRectF& newGeometry, const QRectF& oldGeometry) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void hoverMoveEvent(QHoverEvent* event) override;
    void hoverLeaveEvent(QHoverEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;

private:
    void seekAt(qreal x, bool finalPosition = true);
    [[nodiscard]] QVariantList previewClips() const;
    [[nodiscard]] int clipIndexAt(qreal x) const;
    [[nodiscard]] int insertionIndexAt(qreal x) const;
    [[nodiscard]] qint64 timeAt(qreal x) const;
    void clampViewport();

    enum class DragMode { none, trim_left, trim_right, move, pan, scrub };

    QVariantList clips_;
    qint64 duration_ns_{};
    qint64 playhead_ns_{};
    bool skimming_enabled_{true};
    bool skimmer_active_{};
    qint64 skimmer_ns_{};
    qint64 in_point_ns_{-1};
    qint64 out_point_ns_{-1};
    QString selected_clip_id_;
    QStringList selected_clip_ids_;
    DragMode drag_mode_{DragMode::none};
    int drag_clip_index_{-1};
    qreal drag_origin_x_{};
    qint64 pan_origin_viewport_ns_{};
    qint64 drag_delta_ns_{};
    int move_target_index_{-1};
    int hover_clip_index_{-1};
    qreal zoom_level_{1.0};
    qint64 viewport_start_ns_{};
    bool timeline_geometry_dirty_{true};
    qint64 painted_view_start_ns_{};
    qint64 painted_view_duration_ns_{1};
    bool interaction_active_{};
    QString interaction_kind_;
    qint64 interaction_time_ns_{};
    qreal interaction_x_{};
};
