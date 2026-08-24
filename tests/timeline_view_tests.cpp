#include "timeline_view.hpp"

#include <QGuiApplication>
#include <QHoverEvent>
#include <QMouseEvent>
#include <QSGNode>
#include <QSGSimpleRectNode>
#include <QVariantMap>

#include <chrono>
#include <cstdlib>
#include <iostream>

namespace {

class TestTimelineView final : public TimelineView {
public:
    using TimelineView::TimelineView;

    QSGNode* render(QSGNode* oldNode) { return updatePaintNode(oldNode, nullptr); }
    void press(QPointF position) {
        QMouseEvent event(
            QEvent::MouseButtonPress, position, position, position,
            Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
        mousePressEvent(&event);
    }
    void move(QPointF position) {
        QMouseEvent event(
            QEvent::MouseMove, position, position, position,
            Qt::NoButton, Qt::LeftButton, Qt::NoModifier);
        mouseMoveEvent(&event);
    }
    void release(QPointF position) {
        QMouseEvent event(
            QEvent::MouseButtonRelease, position, position, position,
            Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
        mouseReleaseEvent(&event);
    }
    void hover(QPointF position, QPointF oldPosition = {}) {
        QHoverEvent event(
            QEvent::HoverMove, position, position, oldPosition, Qt::NoModifier);
        hoverMoveEvent(&event);
    }
    void leave(QPointF position) {
        QHoverEvent event(
            QEvent::HoverLeave, position, position, position, Qt::NoModifier);
        hoverLeaveEvent(&event);
    }
};

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main(int argc, char* argv[]) {
    QGuiApplication application(argc, argv);
    TestTimelineView timeline;
    timeline.setWidth(1920);
    timeline.setHeight(220);

    constexpr qint64 clipDuration = 1'000'000'000;
    constexpr int clipCount = 1000;
    QVariantList clips;
    clips.reserve(clipCount);
    for (int index = 0; index < clipCount; ++index) {
        QVariantMap clip;
        clip.insert("id", QStringLiteral("clip-%1").arg(index));
        clip.insert("timelineInNs", static_cast<qint64>(index) * clipDuration);
        clip.insert("sourceInNs", 0);
        clip.insert("durationNs", clipDuration);
        clip.insert("assetDurationNs", clipDuration);
        clips.push_back(clip);
    }
    timeline.setClips(clips);
    timeline.setDurationNs(static_cast<qint64>(clipCount) * clipDuration);
    require(timeline.timelineTimeAt(12) == 0, "left track edge must map to sequence start");
    require(
        timeline.timelineTimeAt(1908) == static_cast<qint64>(clipCount) * clipDuration,
        "right track edge must map to sequence end for media drops");
    timeline.setZoomLevel(4.0);
    timeline.fitToTimeline();
    require(timeline.zoomLevel() == 1.0 && timeline.viewportStartNs() == 0,
            "fit-to-timeline must restore the complete sequence viewport");

    int seekEvents = 0;
    bool finalSeek = false;
    int selectionEvents = 0;
    int skimEvents = 0;
    int skimCommitEvents = 0;
    bool skimActive = false;
    qint64 skimTime = -1;
    QObject::connect(&timeline, &TimelineView::seekRequested,
        [&](qint64, bool finalPosition) {
            ++seekEvents;
            finalSeek = finalPosition;
        });
    QObject::connect(&timeline, &TimelineView::clipSelected,
        [&](const QString&, int) { ++selectionEvents; });
    QObject::connect(&timeline, &TimelineView::skimRequested,
        [&](qint64 position, bool active) {
            ++skimEvents;
            skimTime = position;
            skimActive = active;
        });
    QObject::connect(&timeline, &TimelineView::skimCommitted,
        [&](qint64 position) {
            ++skimCommitEvents;
            skimTime = position;
        });
    timeline.hover(QPointF{500, 80});
    require(timeline.skimmerActive() && skimActive && skimEvents == 1,
            "timeline hover must activate the independent skimmer");
    require(skimTime == timeline.timelineTimeAt(500),
            "skimmer time must follow the hovered timeline coordinate");
    timeline.press(QPointF{300, 10});
    timeline.move(QPointF{420, 10});
    timeline.release(QPointF{420, 10});
    require(seekEvents == 3 && finalSeek,
            "ruler drag must scrub continuously and finish with an exact seek");
    timeline.press(QPointF{300, 80});
    timeline.release(QPointF{300, 80});
    require(selectionEvents == 1,
            "clip body click must select instead of entering a separate scrub tool");
    require(seekEvents == 3 && skimCommitEvents == 1,
            "clip body click must commit the skimmer without using drag-scrub seeks");
    timeline.leave(QPointF{300, 80});
    require(!timeline.skimmerActive() && !skimActive && skimEvents == 2,
            "leaving the timeline must clear the skimmer and restore the program frame");

    auto* root = timeline.render(nullptr);
    require(root != nullptr, "timeline must create a scene graph root");
    auto* contentRoot = root->firstChild();
    require(contentRoot != nullptr, "timeline must create a static content layer");
    auto* staticGeometry = contentRoot->firstChild();
    require(staticGeometry != nullptr, "1000 clips must create static geometry");

    using Clock = std::chrono::steady_clock;
    constexpr int frameCount = 600;
    const auto started = Clock::now();
    for (int frame = 1; frame <= frameCount; ++frame) {
        timeline.setPlayheadNs(static_cast<qint64>(frame) * clipDuration / 60);
        root = timeline.render(root);
        require(
            root->firstChild()->firstChild() == staticGeometry,
            "playhead updates must reuse static clip geometry");
    }
    const auto elapsed = std::chrono::duration<double, std::milli>(
        Clock::now() - started).count();
    const auto average = elapsed / frameCount;
    std::cout << "1000-clip playhead update average: " << average << " ms\n";
    require(average < 16.67, "playhead updates must stay within a 60 FPS frame budget");

    const auto* const geometryBeforeHover = root->firstChild()->firstChild();
    require(geometryBeforeHover == staticGeometry,
            "playhead updates must keep the original clip geometry node");
    timeline.hover(QPointF{500, 80});
    root = timeline.render(root);
    require(root->firstChild()->firstChild() == geometryBeforeHover,
            "hover must not rebuild clip geometry");
    auto* hoverRoot = root->firstChild()->nextSibling()->nextSibling()->nextSibling();
    require(hoverRoot != nullptr && hoverRoot->childCount() == 4,
            "hover overlay must keep four edge nodes");
    auto* topEdge = static_cast<QSGSimpleRectNode*>(hoverRoot->firstChild());
    require(topEdge != nullptr && topEdge->rect().width() > 0,
            "hovered clip must show an outline without rebuilding clips");
    timeline.leave(QPointF{500, 80});
    root = timeline.render(root);
    require(root->firstChild()->firstChild() == geometryBeforeHover,
            "hover leave must keep clip geometry");
    topEdge = static_cast<QSGSimpleRectNode*>(hoverRoot->firstChild());
    require(topEdge != nullptr && topEdge->rect().width() <= 0,
            "leaving must hide the hover outline");
    std::cout << "PASS: hover overlay reuses the static timeline geometry\n";

    timeline.setInPointNs(2 * clipDuration);
    timeline.setOutPointNs(5 * clipDuration);
    root = timeline.render(root);
    int rangeLayerChildren = 0;
    for (auto* child = root->firstChild()->firstChild(); child != nullptr;
         child = child->nextSibling()) {
        ++rangeLayerChildren;
    }
    require(rangeLayerChildren >= 4,
            "marked range must add a fill and two visible edge nodes to the timeline");

    delete root;
    return 0;
}
