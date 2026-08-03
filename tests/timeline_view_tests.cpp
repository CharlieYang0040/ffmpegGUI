#include "timeline_view.hpp"

#include <QGuiApplication>
#include <QSGNode>
#include <QVariantMap>

#include <chrono>
#include <cstdlib>
#include <iostream>

namespace {

class TestTimelineView final : public TimelineView {
public:
    using TimelineView::TimelineView;

    QSGNode* render(QSGNode* oldNode) { return updatePaintNode(oldNode, nullptr); }
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
        clip.insert("color", index % 2 == 0 ? "#315a94" : "#3b6599");
        clips.push_back(clip);
    }
    timeline.setClips(clips);
    timeline.setDurationNs(static_cast<qint64>(clipCount) * clipDuration);
    require(timeline.timelineTimeAt(12) == 0, "left track edge must map to sequence start");
    require(
        timeline.timelineTimeAt(1908) == static_cast<qint64>(clipCount) * clipDuration,
        "right track edge must map to sequence end for media drops");

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
