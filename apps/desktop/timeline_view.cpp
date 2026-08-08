#include "timeline_view.hpp"

#include <QColor>
#include <QCursor>
#include <QDebug>
#include <QElapsedTimer>
#include <QHoverEvent>
#include <QMouseEvent>
#include <QSGGeometryNode>
#include <QSGSimpleRectNode>
#include <QSGVertexColorMaterial>
#include <QVariantMap>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <vector>

namespace {

constexpr qreal kHorizontalPadding = 12.0;
constexpr qreal kTrackTop = 30.0;
constexpr qreal kTrackBottomPadding = 14.0;
constexpr qreal kHandleHitWidth = 9.0;
constexpr qint64 kMinimumClipDuration = 1'000'000;

void setVertex(
    QSGGeometry::ColoredPoint2D& vertex,
    qreal x,
    qreal y,
    const QColor& color) {
    vertex.set(
        static_cast<float>(x),
        static_cast<float>(y),
        static_cast<uchar>(color.red()),
        static_cast<uchar>(color.green()),
        static_cast<uchar>(color.blue()),
        static_cast<uchar>(color.alpha()));
}

}  // namespace

TimelineView::TimelineView(QQuickItem* parent) : QQuickItem(parent) {
    setFlag(ItemHasContents, true);
    setAcceptedMouseButtons(Qt::LeftButton);
    setAcceptHoverEvents(true);
}

qint64 TimelineView::timelineTimeAt(qreal x) const {
    return timeAt(x);
}

void TimelineView::setInteractionMode(int mode) {
    mode = std::clamp(mode, 0, 1);
    if (interaction_mode_ == mode) return;
    interaction_mode_ = mode;
    drag_mode_ = DragMode::none;
    drag_clip_index_ = -1;
    setCursor(QCursor(mode == 1 ? Qt::PointingHandCursor : Qt::ArrowCursor));
    emit interactionModeChanged();
}

void TimelineView::setClips(QVariantList clips) {
    // QML only publishes this property when the timeline revision changes. A deep QVariant
    // comparison walks every clip and every waveform sample and can freeze the UI on large edits.
    clips_ = std::move(clips);
    timeline_geometry_dirty_ = true;
    emit clipsChanged();
    update();
}

void TimelineView::setDurationNs(qint64 duration) {
    duration = std::max<qint64>(0, duration);
    if (duration_ns_ == duration) {
        return;
    }
    duration_ns_ = duration;
    timeline_geometry_dirty_ = true;
    playhead_ns_ = std::min(playhead_ns_, duration_ns_);
    emit durationNsChanged();
    emit playheadNsChanged();
    clampViewport();
    emit viewportChanged();
    update();
}

void TimelineView::setZoomLevel(qreal zoom) {
    zoom = std::clamp(zoom, 1.0, 64.0);
    if (qFuzzyCompare(zoom_level_, zoom)) {
        return;
    }
    zoom_level_ = zoom;
    timeline_geometry_dirty_ = true;
    clampViewport();
    emit zoomLevelChanged();
    emit viewportChanged();
    update();
}

void TimelineView::setPlayheadNs(qint64 position) {
    position = std::clamp<qint64>(position, 0, duration_ns_);
    if (playhead_ns_ == position) {
        return;
    }
    playhead_ns_ = position;
    emit playheadNsChanged();
    update();
}

void TimelineView::setInPointNs(qint64 position) {
    if (in_point_ns_ == position) return;
    in_point_ns_ = position;
    timeline_geometry_dirty_ = true;
    emit rangeChanged();
    update();
}

void TimelineView::setOutPointNs(qint64 position) {
    if (out_point_ns_ == position) return;
    out_point_ns_ = position;
    timeline_geometry_dirty_ = true;
    emit rangeChanged();
    update();
}

void TimelineView::setSelectedClipId(QString clipId) {
    if (selected_clip_id_ == clipId) {
        return;
    }
    selected_clip_id_ = std::move(clipId);
    timeline_geometry_dirty_ = true;
    emit selectedClipIdChanged();
    update();
}

void TimelineView::setSelectedClipIds(QStringList clipIds) {
    if (selected_clip_ids_ == clipIds) return;
    selected_clip_ids_ = std::move(clipIds);
    timeline_geometry_dirty_ = true;
    emit selectedClipIdsChanged();
    update();
}

QSGNode* TimelineView::updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) {
    const bool rebuildingGeometry = timeline_geometry_dirty_;
    QElapsedTimer geometryTimer;
    if (rebuildingGeometry) geometryTimer.start();
    auto* root = oldNode != nullptr ? oldNode : new QSGNode();
    auto* contentRoot = root->firstChild();
    if (contentRoot == nullptr) {
        contentRoot = new QSGNode();
        root->appendChildNode(contentRoot);
    }
    auto* playheadNode = static_cast<QSGSimpleRectNode*>(contentRoot->nextSibling());
    if (playheadNode == nullptr) {
        playheadNode = new QSGSimpleRectNode(QRectF{}, QColor("#f4f7fb"));
        root->appendChildNode(playheadNode);
    }

    const qreal contentWidth = std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0);
    if (timeline_geometry_dirty_) {
        while (auto* child = contentRoot->firstChild()) {
            contentRoot->removeChildNode(child);
            delete child;
        }

        const qreal trackHeight = std::max<qreal>(1.0, height() - kTrackTop - kTrackBottomPadding);
        const auto visibleClips = previewClips();
        qint64 totalDuration = 0;
        for (const auto& value : visibleClips) {
            totalDuration += value.toMap().value("durationNs").toLongLong();
        }
        const auto viewDuration = std::max<qint64>(1, static_cast<qint64>(
            static_cast<qreal>(totalDuration) / zoom_level_));
        const auto viewStart = std::min(
            viewport_start_ns_, std::max<qint64>(0, totalDuration - viewDuration));
        const auto viewEnd = viewStart + viewDuration;
        painted_view_start_ns_ = viewStart;
        painted_view_duration_ns_ = viewDuration;

        if (in_point_ns_ >= 0 && out_point_ns_ > in_point_ns_ &&
            out_point_ns_ > viewStart && in_point_ns_ < viewEnd) {
            const auto rangeLeft = kHorizontalPadding + contentWidth *
                static_cast<qreal>(std::max(in_point_ns_, viewStart) - viewStart) /
                static_cast<qreal>(viewDuration);
            const auto rangeRight = kHorizontalPadding + contentWidth *
                static_cast<qreal>(std::min(out_point_ns_, viewEnd) - viewStart) /
                static_cast<qreal>(viewDuration);
            QColor rangeColor("#5b8cff");
            rangeColor.setAlpha(48);
            contentRoot->appendChildNode(new QSGSimpleRectNode(
                QRectF(rangeLeft, 8.0, std::max<qreal>(1.0, rangeRight - rangeLeft),
                       height() - 18.0),
                rangeColor));
            const QColor edgeColor("#78a5ff");
            contentRoot->appendChildNode(new QSGSimpleRectNode(
                QRectF(rangeLeft, 8.0, 2.0, height() - 18.0), edgeColor));
            contentRoot->appendChildNode(new QSGSimpleRectNode(
                QRectF(rangeRight - 2.0, 8.0, 2.0, height() - 18.0), edgeColor));
        }

        int drawableCount = 0;
        for (const auto& value : visibleClips) {
            const auto clip = value.toMap();
            const auto start = clip.value("timelineInNs").toLongLong();
            const auto end = start + clip.value("durationNs").toLongLong();
            drawableCount += end > viewStart && start < viewEnd ? 1 : 0;
        }
        if (totalDuration > 0 && drawableCount > 0) {
        auto* geometry = new QSGGeometry(
            QSGGeometry::defaultAttributes_ColoredPoint2D(),
            drawableCount * 6);
        geometry->setDrawingMode(QSGGeometry::DrawTriangles);
        auto* vertices = geometry->vertexDataAsColoredPoint2D();

        int vertexIndex = 0;
        for (int index = 0; index < visibleClips.size(); ++index) {
            const auto clip = visibleClips[index].toMap();
            const auto start = clip.value("timelineInNs").toLongLong();
            const auto duration = clip.value("durationNs").toLongLong();
            if (start + duration <= viewStart || start >= viewEnd) {
                continue;
            }
            const auto left = kHorizontalPadding +
                contentWidth * static_cast<qreal>(std::max(start, viewStart) - viewStart) /
                    static_cast<qreal>(viewDuration);
            const auto right = kHorizontalPadding +
                contentWidth * static_cast<qreal>(std::min(start + duration, viewEnd) - viewStart) /
                    static_cast<qreal>(viewDuration);
            QColor color(clip.value("color", index % 2 == 0 ? "#315a94" : "#3f6b9f").toString());
            if (index == hover_clip_index_) {
                color = color.lighter(118);
            }
            if (selected_clip_ids_.contains(clip.value("id").toString())) {
                color = color.lighter(125);
            }
            color.setAlpha(index == hover_clip_index_ ? 205 : 165);
            const auto x1 = left + 1.0;
            const auto x2 = std::max(x1 + 1.0, right - 1.0);
            const auto y1 = kTrackTop;
            const auto y2 = kTrackTop + trackHeight;
            setVertex(vertices[vertexIndex++], x1, y1, color);
            setVertex(vertices[vertexIndex++], x2, y1, color);
            setVertex(vertices[vertexIndex++], x1, y2, color);
            setVertex(vertices[vertexIndex++], x1, y2, color);
            setVertex(vertices[vertexIndex++], x2, y1, color);
            setVertex(vertices[vertexIndex++], x2, y2, color);
        }

        auto* clipNode = new QSGGeometryNode();
        clipNode->setGeometry(geometry);
        clipNode->setFlag(QSGNode::OwnsGeometry);
        clipNode->setMaterial(new QSGVertexColorMaterial());
        clipNode->setFlag(QSGNode::OwnsMaterial);
        contentRoot->appendChildNode(clipNode);

        std::vector<QPointF> waveformLines;
        const auto waveformCenter = kTrackTop + trackHeight * 0.62;
        const auto waveformAmplitude = trackHeight * 0.28;
        for (const auto& value : visibleClips) {
            const auto clip = value.toMap();
            const auto waveform = clip.value("waveform").toList();
            const auto assetDuration = clip.value("assetDurationNs").toLongLong();
            const auto clipStart = clip.value("timelineInNs").toLongLong();
            const auto clipDuration = clip.value("durationNs").toLongLong();
            const auto sourceIn = clip.value("sourceInNs").toLongLong();
            const auto playbackRate = clip.value("playbackRate", 1.0).toDouble();
            const auto visibleStart = std::max(clipStart, viewStart);
            const auto visibleEnd = std::min(clipStart + clipDuration, viewEnd);
            if (waveform.isEmpty() || assetDuration <= 0 || visibleStart >= visibleEnd) {
                continue;
            }
            const auto left = kHorizontalPadding + contentWidth *
                static_cast<qreal>(visibleStart - viewStart) / static_cast<qreal>(viewDuration);
            const auto right = kHorizontalPadding + contentWidth *
                static_cast<qreal>(visibleEnd - viewStart) / static_cast<qreal>(viewDuration);
            const auto sampleCount = std::max(2, static_cast<int>((right - left) / 4.0));
            for (int sample = 0; sample < sampleCount; ++sample) {
                const auto ratio = static_cast<qreal>(sample) /
                    static_cast<qreal>(sampleCount - 1);
                const auto timelineTime = visibleStart + static_cast<qint64>(
                    ratio * static_cast<qreal>(visibleEnd - visibleStart));
                const auto sourceTime = sourceIn + static_cast<qint64>(std::llround(
                    static_cast<double>(timelineTime - clipStart) * playbackRate));
                const auto waveformIndex = std::clamp(
                    static_cast<int>(static_cast<qreal>(sourceTime) /
                        static_cast<qreal>(assetDuration) * waveform.size()),
                    0,
                    static_cast<int>(waveform.size()) - 1);
                const auto amplitude = std::clamp(
                    waveform[waveformIndex].toReal(), 0.0, 1.0) * waveformAmplitude;
                const auto x = left + ratio * (right - left);
                waveformLines.emplace_back(x, waveformCenter - amplitude);
                waveformLines.emplace_back(x, waveformCenter + amplitude);
            }
        }
        if (!waveformLines.empty()) {
            auto* waveformGeometry = new QSGGeometry(
                QSGGeometry::defaultAttributes_ColoredPoint2D(),
                static_cast<int>(waveformLines.size()));
            waveformGeometry->setDrawingMode(QSGGeometry::DrawLines);
            auto* waveformVertices = waveformGeometry->vertexDataAsColoredPoint2D();
            const QColor waveformColor("#c8d8ee");
            for (std::size_t index = 0; index < waveformLines.size(); ++index) {
                setVertex(
                    waveformVertices[index],
                    waveformLines[index].x(),
                    waveformLines[index].y(),
                    waveformColor);
            }
            auto* waveformNode = new QSGGeometryNode();
            waveformNode->setGeometry(waveformGeometry);
            waveformNode->setFlag(QSGNode::OwnsGeometry);
            waveformNode->setMaterial(new QSGVertexColorMaterial());
            waveformNode->setFlag(QSGNode::OwnsMaterial);
            contentRoot->appendChildNode(waveformNode);
        }

        for (const auto& value : visibleClips) {
            const auto clip = value.toMap();
            const auto start = clip.value("timelineInNs").toLongLong();
            const auto clipDuration = clip.value("durationNs").toLongLong();
            if (clip.value("id").toString() == selected_clip_id_) {
                const auto left = kHorizontalPadding +
                    contentWidth * static_cast<qreal>(start - viewStart) / static_cast<qreal>(viewDuration);
                const auto right = kHorizontalPadding +
                    contentWidth * static_cast<qreal>(start + clipDuration - viewStart) /
                        static_cast<qreal>(viewDuration);
                if (left >= kHorizontalPadding && left <= width() - kHorizontalPadding) {
                    contentRoot->appendChildNode(new QSGSimpleRectNode(
                        QRectF(left, kTrackTop, 4.0, trackHeight), QColor("#eef4ff")));
                }
                if (right >= kHorizontalPadding && right <= width() - kHorizontalPadding) {
                    contentRoot->appendChildNode(new QSGSimpleRectNode(
                        QRectF(right - 4.0, kTrackTop, 4.0, trackHeight), QColor("#eef4ff")));
                }
                break;
            }
        }

        }
        timeline_geometry_dirty_ = false;
    }

    if (rebuildingGeometry && geometryTimer.elapsed() >= 50) {
        qWarning().noquote() << "timeline Scene Graph rebuild was slow"
                             << "elapsed_ms=" << geometryTimer.elapsed()
                             << "clips=" << clips_.size()
                             << "zoom=" << zoom_level_;
    }

    const auto paintedViewEnd = painted_view_start_ns_ + painted_view_duration_ns_;
    if (duration_ns_ > 0 && playhead_ns_ >= painted_view_start_ns_ &&
        playhead_ns_ <= paintedViewEnd) {
        const auto playheadX = kHorizontalPadding +
            contentWidth * static_cast<qreal>(playhead_ns_ - painted_view_start_ns_) /
                static_cast<qreal>(painted_view_duration_ns_);
        playheadNode->setRect(QRectF(playheadX - 1.0, 8.0, 2.0, height() - 12.0));
    } else {
        playheadNode->setRect(QRectF{});
    }
    return root;
}

void TimelineView::geometryChange(const QRectF& newGeometry, const QRectF& oldGeometry) {
    timeline_geometry_dirty_ = true;
    QQuickItem::geometryChange(newGeometry, oldGeometry);
}

void TimelineView::mousePressEvent(QMouseEvent* event) {
    if (interaction_mode_ == 1) {
        drag_mode_ = DragMode::none;
        drag_clip_index_ = -1;
        interaction_active_ = true;
        interaction_kind_ = QStringLiteral("탐색");
        interaction_x_ = event->position().x();
        interaction_time_ns_ = timeAt(interaction_x_);
        emit interactionFeedbackChanged();
        seekAt(event->position().x(), false);
        setCursor(QCursor(Qt::ClosedHandCursor));
        event->accept();
        return;
    }
    drag_clip_index_ = clipIndexAt(event->position().x());
    if (drag_clip_index_ < 0) {
        seekAt(event->position().x());
        event->accept();
        return;
    }

    const auto clip = clips_[drag_clip_index_].toMap();
    const auto clipId = clip.value("id").toString();
    const auto modifiers = event->modifiers();
    const int selectionMode = modifiers.testFlag(Qt::ControlModifier)
        ? 1
        : (modifiers.testFlag(Qt::ShiftModifier) ? 2 : 0);
    const bool preserveGroup = selectionMode == 0 &&
        selected_clip_ids_.size() > 1 && selected_clip_ids_.contains(clipId);
    if (selectionMode == 0 && !preserveGroup) {
        setSelectedClipId(clipId);
        setSelectedClipIds(QStringList{clipId});
    }
    if (!preserveGroup) emit clipSelected(clipId, selectionMode);
    drag_origin_x_ = event->position().x();
    drag_delta_ns_ = 0;
    move_target_index_ = insertionIndexAt(event->position().x());

    const auto contentWidth = std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0);
    const auto start = clip.value("timelineInNs").toLongLong();
    const auto duration = clip.value("durationNs").toLongLong();
    const auto left = kHorizontalPadding +
        contentWidth * static_cast<qreal>(start - viewport_start_ns_) /
            static_cast<qreal>(visibleDurationNs());
    const auto right = kHorizontalPadding +
        contentWidth * static_cast<qreal>(start + duration - viewport_start_ns_) /
            static_cast<qreal>(visibleDurationNs());
    if (std::abs(event->position().x() - left) <= kHandleHitWidth) {
        drag_mode_ = DragMode::trim_left;
        interaction_kind_ = QStringLiteral("시작 트림");
        interaction_time_ns_ = start;
        setCursor(QCursor(Qt::SizeHorCursor));
    } else if (std::abs(event->position().x() - right) <= kHandleHitWidth) {
        drag_mode_ = DragMode::trim_right;
        interaction_kind_ = QStringLiteral("끝 트림");
        interaction_time_ns_ = start + duration;
        setCursor(QCursor(Qt::SizeHorCursor));
    } else {
        drag_mode_ = DragMode::move;
        interaction_kind_ = QStringLiteral("클립 이동");
        interaction_time_ns_ = start;
        setCursor(QCursor(Qt::ClosedHandCursor));
    }
    interaction_active_ = drag_mode_ != DragMode::none;
    interaction_x_ = event->position().x();
    emit interactionFeedbackChanged();
    if (selectionMode != 0) drag_mode_ = DragMode::none;
    event->accept();
}

void TimelineView::hoverMoveEvent(QHoverEvent* event) {
    if (interaction_mode_ == 1) {
        if (hover_clip_index_ >= 0) {
            hover_clip_index_ = -1;
            timeline_geometry_dirty_ = true;
            update();
        }
        setCursor(QCursor(Qt::PointingHandCursor));
        event->accept();
        return;
    }
    const auto index = clipIndexAt(event->position().x());
    if (hover_clip_index_ != index) {
        hover_clip_index_ = index;
        timeline_geometry_dirty_ = true;
        update();
    }
    if (index < 0) {
        setCursor(QCursor(Qt::ArrowCursor));
        event->accept();
        return;
    }

    const auto clip = clips_[index].toMap();
    const auto contentWidth = std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0);
    const auto start = clip.value("timelineInNs").toLongLong();
    const auto duration = clip.value("durationNs").toLongLong();
    const auto left = kHorizontalPadding + contentWidth *
        static_cast<qreal>(start - viewport_start_ns_) /
        static_cast<qreal>(visibleDurationNs());
    const auto right = kHorizontalPadding + contentWidth *
        static_cast<qreal>(start + duration - viewport_start_ns_) /
        static_cast<qreal>(visibleDurationNs());
    setCursor(QCursor(
        std::abs(event->position().x() - left) <= kHandleHitWidth ||
            std::abs(event->position().x() - right) <= kHandleHitWidth
        ? Qt::SizeHorCursor
        : Qt::OpenHandCursor));
    event->accept();
}

void TimelineView::hoverLeaveEvent(QHoverEvent* event) {
    if (hover_clip_index_ >= 0) {
        hover_clip_index_ = -1;
        timeline_geometry_dirty_ = true;
        update();
    }
    setCursor(QCursor(Qt::ArrowCursor));
    event->accept();
}

void TimelineView::mouseMoveEvent(QMouseEvent* event) {
    if (event->buttons().testFlag(Qt::LeftButton)) {
        if (interaction_mode_ == 1) {
            interaction_x_ = event->position().x();
            interaction_time_ns_ = timeAt(interaction_x_);
            emit interactionFeedbackChanged();
            seekAt(event->position().x(), false);
            event->accept();
            return;
        }
        if (drag_mode_ == DragMode::none || drag_clip_index_ < 0) {
            seekAt(event->position().x());
        } else {
            const auto contentWidth = std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0);
            drag_delta_ns_ = static_cast<qint64>(
                (event->position().x() - drag_origin_x_) /
                contentWidth * static_cast<qreal>(visibleDurationNs()));
            const auto clip = clips_[drag_clip_index_].toMap();
            const auto sourceIn = clip.value("sourceInNs").toLongLong();
            const auto duration = clip.value("durationNs").toLongLong();
            const auto sourceDuration = clip.value(
                "sourceDurationNs", clip.value("durationNs")).toLongLong();
            const auto assetDuration = clip.value("assetDurationNs").toLongLong();
            const auto playbackRate = clip.value("playbackRate", 1.0).toDouble();
            if (drag_mode_ == DragMode::trim_left) {
                drag_delta_ns_ = std::clamp<qint64>(
                    drag_delta_ns_,
                    -static_cast<qint64>(std::llround(sourceIn / playbackRate)),
                    duration - kMinimumClipDuration);
            } else if (drag_mode_ == DragMode::trim_right) {
                drag_delta_ns_ = std::clamp<qint64>(
                    drag_delta_ns_, -(duration - kMinimumClipDuration),
                    static_cast<qint64>(std::llround(
                        (assetDuration - sourceIn - sourceDuration) / playbackRate)));
            } else {
                move_target_index_ = insertionIndexAt(event->position().x());
            }
            interaction_x_ = event->position().x();
            if (drag_mode_ == DragMode::trim_left || drag_mode_ == DragMode::trim_right) {
                interaction_time_ns_ = clip.value("timelineInNs").toLongLong() +
                    (drag_mode_ == DragMode::trim_right ? duration : 0) + drag_delta_ns_;
            } else {
                interaction_time_ns_ = timeAt(interaction_x_);
            }
            emit interactionFeedbackChanged();
            timeline_geometry_dirty_ = true;
            update();
        }
        event->accept();
        return;
    }
    QQuickItem::mouseMoveEvent(event);
}

void TimelineView::mouseReleaseEvent(QMouseEvent* event) {
    if (interaction_mode_ == 1) {
        seekAt(event->position().x(), true);
        interaction_active_ = false;
        emit interactionFeedbackChanged();
        setCursor(QCursor(Qt::PointingHandCursor));
        event->accept();
        return;
    }
    if (event->button() == Qt::LeftButton && drag_clip_index_ >= 0) {
        const auto clip = clips_[drag_clip_index_].toMap();
        const auto clipId = clip.value("id").toString();
        const auto sourceIn = clip.value("sourceInNs").toLongLong();
        const auto sourceDuration = clip.value(
            "sourceDurationNs", clip.value("durationNs")).toLongLong();
        const auto playbackRate = clip.value("playbackRate", 1.0).toDouble();
        const auto sourceDelta = static_cast<qint64>(std::llround(
            static_cast<double>(drag_delta_ns_) * playbackRate));
        if (drag_mode_ == DragMode::trim_left && drag_delta_ns_ != 0) {
            emit trimCommitted(clipId, sourceIn + sourceDelta, sourceDuration - sourceDelta);
        } else if (drag_mode_ == DragMode::trim_right && drag_delta_ns_ != 0) {
            emit trimCommitted(clipId, sourceIn, sourceDuration + sourceDelta);
        } else if (drag_mode_ == DragMode::move && drag_delta_ns_ != 0 &&
                   move_target_index_ >= 0) {
            const auto movingIds = selected_clip_ids_.contains(clipId)
                ? selected_clip_ids_
                : QStringList{clipId};
            emit moveCommitted(movingIds, move_target_index_);
        } else {
            seekAt(event->position().x());
        }
    }
    drag_mode_ = DragMode::none;
    drag_clip_index_ = -1;
    drag_delta_ns_ = 0;
    interaction_active_ = false;
    emit interactionFeedbackChanged();
    setCursor(QCursor(hover_clip_index_ >= 0 ? Qt::OpenHandCursor : Qt::ArrowCursor));
    timeline_geometry_dirty_ = true;
    update();
    event->accept();
}

void TimelineView::seekAt(qreal x, bool finalPosition) {
    if (duration_ns_ <= 0) {
        return;
    }
    setPlayheadNs(timeAt(x));
    emit seekRequested(playhead_ns_, finalPosition);
}

void TimelineView::wheelEvent(QWheelEvent* event) {
    if (duration_ns_ <= 0) {
        event->ignore();
        return;
    }
    const auto steps = static_cast<qreal>(event->angleDelta().y()) / 120.0;
    if (event->modifiers().testFlag(Qt::ControlModifier)) {
        const auto anchor = timeAt(event->position().x());
        const auto ratio = std::clamp(
            (event->position().x() - kHorizontalPadding) /
                std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0),
            0.0,
            1.0);
        setZoomLevel(zoom_level_ * std::pow(1.25, steps));
        viewport_start_ns_ = anchor - static_cast<qint64>(ratio * visibleDurationNs());
    } else {
        viewport_start_ns_ -= static_cast<qint64>(steps * visibleDurationNs() * 0.12);
    }
    clampViewport();
    timeline_geometry_dirty_ = true;
    emit viewportChanged();
    update();
    event->accept();
}

QVariantList TimelineView::previewClips() const {
    QVariantList result = clips_;
    if (drag_clip_index_ < 0 || drag_clip_index_ >= result.size()) {
        return result;
    }
    if (drag_mode_ == DragMode::move) {
        QVariantList moving;
        for (auto index = result.size() - 1; index >= 0; --index) {
            const auto id = result[index].toMap().value("id").toString();
            if (selected_clip_ids_.contains(id)) moving.prepend(result.takeAt(index));
        }
        const auto insertionIndex = std::clamp(
            move_target_index_, 0, static_cast<int>(result.size()));
        for (auto index = 0; index < moving.size(); ++index) {
            result.insert(insertionIndex + index, moving[index]);
        }
    } else if (drag_mode_ == DragMode::trim_left || drag_mode_ == DragMode::trim_right) {
        auto clip = result[drag_clip_index_].toMap();
        const auto playbackRate = clip.value("playbackRate", 1.0).toDouble();
        const auto sourceDelta = static_cast<qint64>(std::llround(
            static_cast<double>(drag_delta_ns_) * playbackRate));
        auto sourceDuration = clip.value(
            "sourceDurationNs", clip.value("durationNs")).toLongLong();
        if (drag_mode_ == DragMode::trim_left) {
            clip.insert("sourceInNs", clip.value("sourceInNs").toLongLong() + sourceDelta);
            sourceDuration -= sourceDelta;
        } else {
            sourceDuration += sourceDelta;
        }
        clip.insert("sourceDurationNs", sourceDuration);
        clip.insert("durationNs", static_cast<qint64>(std::llround(
            static_cast<double>(sourceDuration) / playbackRate)));
        result[drag_clip_index_] = clip;
    }
    qint64 cursor = 0;
    for (int index = 0; index < result.size(); ++index) {
        auto clip = result[index].toMap();
        clip.insert("timelineInNs", cursor);
        cursor += clip.value("durationNs").toLongLong();
        result[index] = clip;
    }
    return result;
}

int TimelineView::clipIndexAt(qreal x) const {
    if (duration_ns_ <= 0 || clips_.isEmpty()) {
        return -1;
    }
    const auto timelinePosition = timeAt(x);
    for (int index = 0; index < clips_.size(); ++index) {
        const auto clip = clips_[index].toMap();
        const auto start = clip.value("timelineInNs").toLongLong();
        const auto end = start + clip.value("durationNs").toLongLong();
        if (timelinePosition >= start && timelinePosition < end) {
            return index;
        }
    }
    return clips_.size() - 1;
}

int TimelineView::insertionIndexAt(qreal x) const {
    const auto timelineTime = timeAt(x);
    int remainingIndex = 0;
    for (const auto& value : clips_) {
        const auto clip = value.toMap();
        if (selected_clip_ids_.contains(clip.value("id").toString())) continue;
        const auto start = clip.value("timelineInNs").toLongLong();
        const auto midpoint = start + clip.value("durationNs").toLongLong() / 2;
        if (timelineTime < midpoint) return remainingIndex;
        ++remainingIndex;
    }
    return remainingIndex;
}

qint64 TimelineView::visibleDurationNs() const {
    if (duration_ns_ <= 0) {
        return 1;
    }
    return std::max<qint64>(1, static_cast<qint64>(duration_ns_ / zoom_level_));
}

qint64 TimelineView::timeAt(qreal x) const {
    const auto contentWidth = std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0);
    const auto ratio = std::clamp((x - kHorizontalPadding) / contentWidth, 0.0, 1.0);
    return std::clamp<qint64>(
        viewport_start_ns_ + static_cast<qint64>(ratio * visibleDurationNs()),
        0,
        duration_ns_);
}

void TimelineView::clampViewport() {
    viewport_start_ns_ = std::clamp<qint64>(
        viewport_start_ns_, 0, std::max<qint64>(0, duration_ns_ - visibleDurationNs()));
}
