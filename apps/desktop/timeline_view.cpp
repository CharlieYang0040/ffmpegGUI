#include "timeline_view.hpp"

#include <QColor>
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
}

void TimelineView::setClips(QVariantList clips) {
    if (clips_ == clips) {
        return;
    }
    clips_ = std::move(clips);
    emit clipsChanged();
    update();
}

void TimelineView::setDurationNs(qint64 duration) {
    duration = std::max<qint64>(0, duration);
    if (duration_ns_ == duration) {
        return;
    }
    duration_ns_ = duration;
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

void TimelineView::setSelectedClipId(QString clipId) {
    if (selected_clip_id_ == clipId) {
        return;
    }
    selected_clip_id_ = std::move(clipId);
    emit selectedClipIdChanged();
    update();
}

QSGNode* TimelineView::updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) {
    delete oldNode;
    auto* root = new QSGNode();

    const qreal contentWidth = std::max<qreal>(1.0, width() - kHorizontalPadding * 2.0);
    const qreal trackHeight = std::max<qreal>(1.0, height() - kTrackTop - kTrackBottomPadding);
    const auto visibleClips = previewClips();
    qint64 totalDuration = 0;
    for (const auto& value : visibleClips) {
        totalDuration += value.toMap().value("durationNs").toLongLong();
    }
    const auto viewDuration = std::max<qint64>(1, static_cast<qint64>(
        static_cast<qreal>(totalDuration) / zoom_level_));
    const auto viewStart = std::min(viewport_start_ns_, std::max<qint64>(0, totalDuration - viewDuration));
    const auto viewEnd = viewStart + viewDuration;
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
            if (clip.value("id").toString() == selected_clip_id_) {
                color = color.lighter(125);
            }
            color.setAlpha(145);
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
        root->appendChildNode(clipNode);

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
                const auto sourceTime = sourceIn + timelineTime - clipStart;
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
            root->appendChildNode(waveformNode);
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
                    root->appendChildNode(new QSGSimpleRectNode(
                        QRectF(left, kTrackTop, 4.0, trackHeight), QColor("#eef4ff")));
                }
                if (right >= kHorizontalPadding && right <= width() - kHorizontalPadding) {
                    root->appendChildNode(new QSGSimpleRectNode(
                        QRectF(right - 4.0, kTrackTop, 4.0, trackHeight), QColor("#eef4ff")));
                }
                break;
            }
        }

        if (playhead_ns_ >= viewStart && playhead_ns_ <= viewEnd) {
            const auto playheadX = kHorizontalPadding +
                contentWidth * static_cast<qreal>(playhead_ns_ - viewStart) /
                    static_cast<qreal>(viewDuration);
            root->appendChildNode(new QSGSimpleRectNode(
                QRectF(playheadX - 1.0, 8.0, 2.0, height() - 12.0),
                QColor("#f4f7fb")));
        }
    }
    return root;
}

void TimelineView::mousePressEvent(QMouseEvent* event) {
    drag_clip_index_ = clipIndexAt(event->position().x());
    if (drag_clip_index_ < 0) {
        seekAt(event->position().x());
        event->accept();
        return;
    }

    const auto clip = clips_[drag_clip_index_].toMap();
    setSelectedClipId(clip.value("id").toString());
    emit clipSelected(selected_clip_id_);
    drag_origin_x_ = event->position().x();
    drag_delta_ns_ = 0;
    move_target_index_ = drag_clip_index_;

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
    } else if (std::abs(event->position().x() - right) <= kHandleHitWidth) {
        drag_mode_ = DragMode::trim_right;
    } else {
        drag_mode_ = DragMode::move;
    }
    event->accept();
}

void TimelineView::mouseMoveEvent(QMouseEvent* event) {
    if (event->buttons().testFlag(Qt::LeftButton)) {
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
            const auto assetDuration = clip.value("assetDurationNs").toLongLong();
            if (drag_mode_ == DragMode::trim_left) {
                drag_delta_ns_ = std::clamp<qint64>(
                    drag_delta_ns_, -sourceIn, duration - kMinimumClipDuration);
            } else if (drag_mode_ == DragMode::trim_right) {
                drag_delta_ns_ = std::clamp<qint64>(
                    drag_delta_ns_, -(duration - kMinimumClipDuration),
                    assetDuration - sourceIn - duration);
            } else {
                move_target_index_ = clipIndexAt(event->position().x());
            }
            update();
        }
        event->accept();
        return;
    }
    QQuickItem::mouseMoveEvent(event);
}

void TimelineView::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton && drag_clip_index_ >= 0) {
        const auto clip = clips_[drag_clip_index_].toMap();
        const auto clipId = clip.value("id").toString();
        const auto sourceIn = clip.value("sourceInNs").toLongLong();
        const auto duration = clip.value("durationNs").toLongLong();
        if (drag_mode_ == DragMode::trim_left && drag_delta_ns_ != 0) {
            emit trimCommitted(clipId, sourceIn + drag_delta_ns_, duration - drag_delta_ns_);
        } else if (drag_mode_ == DragMode::trim_right && drag_delta_ns_ != 0) {
            emit trimCommitted(clipId, sourceIn, duration + drag_delta_ns_);
        } else if (drag_mode_ == DragMode::move && move_target_index_ != drag_clip_index_) {
            emit moveCommitted(clipId, move_target_index_);
        } else {
            seekAt(event->position().x());
        }
    }
    drag_mode_ = DragMode::none;
    drag_clip_index_ = -1;
    drag_delta_ns_ = 0;
    update();
    event->accept();
}

void TimelineView::seekAt(qreal x) {
    if (duration_ns_ <= 0) {
        return;
    }
    setPlayheadNs(timeAt(x));
    emit seekRequested(playhead_ns_);
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
        const auto moving = result.takeAt(drag_clip_index_);
        result.insert(
            std::clamp(move_target_index_, 0, static_cast<int>(result.size())), moving);
    } else if (drag_mode_ == DragMode::trim_left || drag_mode_ == DragMode::trim_right) {
        auto clip = result[drag_clip_index_].toMap();
        if (drag_mode_ == DragMode::trim_left) {
            clip.insert("sourceInNs", clip.value("sourceInNs").toLongLong() + drag_delta_ns_);
            clip.insert("durationNs", clip.value("durationNs").toLongLong() - drag_delta_ns_);
        } else {
            clip.insert("durationNs", clip.value("durationNs").toLongLong() + drag_delta_ns_);
        }
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
