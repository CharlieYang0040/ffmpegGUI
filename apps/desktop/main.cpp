#include "timeline_view.hpp"
#include "editor_controller.hpp"

#include <QGuiApplication>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QDir>
#include <QDateTime>
#include <QMutex>
#include <QMutexLocker>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QStandardPaths>
#include <QTimer>
#include <QUrl>
#include <qqml.h>

#include <cmath>
#include <atomic>
#include <chrono>
#include <memory>
#include <thread>

namespace {

std::unique_ptr<QFile> applicationLog;
QMutex applicationLogMutex;
QtMessageHandler previousMessageHandler{};

void writeApplicationLog(
    QtMsgType type,
    const QMessageLogContext& context,
    const QString& message) {
    const char* level = "INFO";
    if (type == QtWarningMsg) level = "WARN";
    else if (type == QtCriticalMsg) level = "ERROR";
    else if (type == QtFatalMsg) level = "FATAL";
    else if (type == QtDebugMsg) level = "DEBUG";
    const auto category = context.category != nullptr ? context.category : "default";
    const auto line = QStringLiteral("%1 [%2] %3 · %4\n")
        .arg(QDateTime::currentDateTime().toString(Qt::ISODateWithMs))
        .arg(QString::fromLatin1(level))
        .arg(QString::fromLatin1(category))
        .arg(message)
        .toUtf8();
    {
        QMutexLocker lock(&applicationLogMutex);
        if (applicationLog && applicationLog->isOpen()) {
            applicationLog->write(line);
            applicationLog->flush();
        }
    }
    if (previousMessageHandler != nullptr) previousMessageHandler(type, context, message);
}

QString initializeApplicationLog() {
    const auto directory = QDir(
        QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation));
    QDir().mkpath(directory.filePath("logs"));
    const auto path = directory.filePath("logs/editor.log");
    const QFileInfo existing(path);
    if (existing.isFile() && existing.size() > 10 * 1024 * 1024) {
        const auto previous = directory.filePath("logs/editor.previous.log");
        QFile::remove(previous);
        QFile::rename(path, previous);
    }
    applicationLog = std::make_unique<QFile>(path);
    if (!applicationLog->open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text)) {
        applicationLog.reset();
        return {};
    }
    previousMessageHandler = qInstallMessageHandler(writeApplicationLog);
    return path;
}

qint64 monotonicMilliseconds() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

void configureBundledGStreamer() {
    const auto applicationDir = QCoreApplication::applicationDirPath();
    const auto pluginDir = QDir(applicationDir).filePath("lib/gstreamer-1.0");
    if (!QFileInfo(pluginDir).isDir()) {
        return;
    }
    const auto scanner = QDir(applicationDir).filePath(
        "libexec/gstreamer-1.0/gst-plugin-scanner.exe");
    const auto gioModules = QDir(applicationDir).filePath("lib/gio/modules");
    const auto cacheDir = QStandardPaths::writableLocation(QStandardPaths::CacheLocation);
    QDir().mkpath(cacheDir);
    qputenv("GST_PLUGIN_SYSTEM_PATH_1_0", pluginDir.toUtf8());
    qputenv("GST_PLUGIN_PATH_1_0", pluginDir.toUtf8());
    qputenv("GST_PLUGIN_SCANNER", scanner.toUtf8());
    qputenv("GST_REGISTRY_1_0", QDir(cacheDir).filePath("registry-x86_64.bin").toUtf8());
    qputenv("GIO_MODULE_DIR", gioModules.toUtf8());
}

}  // namespace

int main(int argc, char* argv[]) {
    QGuiApplication application(argc, argv);
    application.setApplicationName("ffmpegGUI Next");
    application.setOrganizationName("CharlieYang0040");
    const auto logPath = initializeApplicationLog();
    qInfo().noquote() << "application started; log=" << logPath;
    std::atomic<qint64> uiHeartbeat{monotonicMilliseconds()};
    QTimer uiHeartbeatTimer;
    uiHeartbeatTimer.setInterval(250);
    QObject::connect(&uiHeartbeatTimer, &QTimer::timeout, &application, [&uiHeartbeat] {
        uiHeartbeat.store(monotonicMilliseconds(), std::memory_order_relaxed);
    });
    uiHeartbeatTimer.start();
    std::jthread uiWatchdog([&uiHeartbeat](std::stop_token stopToken) {
        bool reported = false;
        while (!stopToken.stop_requested()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            const auto delay = monotonicMilliseconds() -
                uiHeartbeat.load(std::memory_order_relaxed);
            if (delay >= 2'000 && !reported) {
                qWarning().noquote() << "UI event loop stalled for at least" << delay << "ms";
                reported = true;
            } else if (delay < 750 && reported) {
                qInfo().noquote() << "UI event loop recovered";
                reported = false;
            }
        }
    });
    configureBundledGStreamer();
    QQuickStyle::setStyle("Basic");
    QWindow videoWindow;
    EditorController controller(nullptr);
    controller.setVideoWindow(&videoWindow);
    EditorController::setSingletonInstance(&controller);

    QStringList mediaFiles;
    QString roundtripProject;
    QString exportSmokeOutput;
    QString exportProjectSmoke;
    QString exportProjectOutput;
    bool playbackSmoke = false;
    bool loopSmoke = false;
    bool offscreenPresentationSmoke = false;
    bool hevcExportSmoke = false;
    bool gifExportSmoke = false;
    bool floatExportSmoke = false;
    bool floatVideoSmoke = false;
    QString exrSelectionSmokeProject;
    const auto arguments = application.arguments();
    for (int index = 1; index < arguments.size(); ++index) {
        if (arguments[index] == "--project-roundtrip" && index + 1 < arguments.size()) {
            roundtripProject = arguments[++index];
            continue;
        }
        if (arguments[index] == "--playback-smoke") {
            playbackSmoke = true;
            continue;
        }
        if (arguments[index] == "--loop-smoke") {
            loopSmoke = true;
            continue;
        }
        if (arguments[index] == "--offscreen-presentation-smoke") {
            offscreenPresentationSmoke = true;
            continue;
        }
        if (arguments[index] == "--export-smoke" && index + 1 < arguments.size()) {
            exportSmokeOutput = arguments[++index];
            continue;
        }
        if (arguments[index] == "--export-hevc-smoke" && index + 1 < arguments.size()) {
            exportSmokeOutput = arguments[++index];
            hevcExportSmoke = true;
            continue;
        }
        if (arguments[index] == "--export-gif-smoke" && index + 1 < arguments.size()) {
            exportSmokeOutput = arguments[++index];
            gifExportSmoke = true;
            continue;
        }
        if (arguments[index] == "--float-export-smoke" && index + 1 < arguments.size()) {
            exportSmokeOutput = arguments[++index];
            floatExportSmoke = true;
            continue;
        }
        if (arguments[index] == "--float-video-smoke") {
            floatVideoSmoke = true;
            continue;
        }
        if (arguments[index] == "--exr-selection-smoke" && index + 1 < arguments.size()) {
            exrSelectionSmokeProject = arguments[++index];
            continue;
        }
        if (arguments[index] == "--export-project-smoke" && index + 2 < arguments.size()) {
            exportProjectSmoke = arguments[++index];
            exportProjectOutput = arguments[++index];
            continue;
        }
        mediaFiles.push_back(arguments[index]);
    }

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(
        QStringLiteral("OffscreenPresentationSmoke"), offscreenPresentationSmoke);
    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &application,
        [] { QCoreApplication::exit(EXIT_FAILURE); },
        Qt::QueuedConnection);
    engine.loadFromModule("FFGuiNext", "Main");
    QTimer presentationPulse;
    if (offscreenPresentationSmoke && !engine.rootObjects().isEmpty()) {
        if (auto* rootWindow = qobject_cast<QQuickWindow*>(engine.rootObjects().front())) {
            presentationPulse.setInterval(250);
            QObject::connect(&presentationPulse, &QTimer::timeout, rootWindow, [rootWindow] {
                rootWindow->requestUpdate();
                static_cast<void>(rootWindow->grabWindow());
            });
            presentationPulse.start();
        }
    }
    if (!mediaFiles.isEmpty()) {
        controller.loadFiles(mediaFiles);
    }
    if (!exportProjectSmoke.isEmpty()) {
        controller.loadProject(exportProjectSmoke);
        if (controller.durationNs() <= 0) return EXIT_FAILURE;
    }
    if ((!roundtripProject.isEmpty() || !exportSmokeOutput.isEmpty() || playbackSmoke ||
         floatVideoSmoke || !exrSelectionSmokeProject.isEmpty()) &&
        controller.importing()) {
        QEventLoop importLoop;
        QTimer importTimeout;
        importTimeout.setSingleShot(true);
        QObject::connect(
            &controller, &EditorController::mediaImportFinished, &importLoop, &QEventLoop::quit);
        QObject::connect(&importTimeout, &QTimer::timeout, &importLoop, &QEventLoop::quit);
        importTimeout.start(120'000);
        importLoop.exec();
        if (controller.importing() || controller.durationNs() <= 0) {
            return EXIT_FAILURE;
        }
    }
    if (!exrSelectionSmokeProject.isEmpty()) {
        const auto assetsBefore = controller.mediaAssets();
        const auto clipsBefore = controller.clips();
        if (assetsBefore.size() != 1 || clipsBefore.size() != 1) return EXIT_FAILURE;
        const auto before = assetsBefore.front().toMap();
        const auto partOptions = before.value("exrPartOptions").toList();
        if (partOptions.isEmpty()) return EXIT_FAILURE;
        const auto part = partOptions.front().toMap().value("value").toString();
        const auto assetId = before.value("id").toString();
        QEventLoop selectionLoop;
        QTimer selectionTimeout;
        selectionTimeout.setSingleShot(true);
        QObject::connect(
            &controller, &EditorController::mediaImportFinished,
            &selectionLoop, &QEventLoop::quit);
        QObject::connect(&selectionTimeout, &QTimer::timeout, &selectionLoop, &QEventLoop::quit);
        controller.updateExrSelection(assetId, part, {}, {});
        selectionTimeout.start(120'000);
        if (controller.importing()) selectionLoop.exec();
        if (controller.importing()) return EXIT_FAILURE;
        const auto assetsAfter = controller.mediaAssets();
        const auto clipsAfter = controller.clips();
        if (assetsAfter.size() != 1 || clipsAfter.size() != 1 ||
            assetsAfter.front().toMap().value("id").toString() != assetId ||
            clipsAfter.front().toMap().value("id") != clipsBefore.front().toMap().value("id") ||
            assetsAfter.front().toMap().value("exrPart").toString() != part) {
            return EXIT_FAILURE;
        }
        controller.saveProject(exrSelectionSmokeProject);
        controller.loadProject(exrSelectionSmokeProject);
        const auto reloaded = controller.mediaAssets();
        return reloaded.size() == 1 &&
                !reloaded.front().toMap().value("exrPartOptions").toList().isEmpty() &&
                reloaded.front().toMap().value("exrPart").toString() == part
            ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    if (floatVideoSmoke) {
        const auto clips = controller.clips();
        const auto assets = controller.mediaAssets();
        for (const auto& asset : assets) {
            controller.setAssetInputColorSpace(
                asset.toMap().value("id").toString(), QStringLiteral("Camera Rec.709"));
        }
        if (clips.isEmpty() || assets.size() != clips.size()) return EXIT_FAILURE;
        const auto firstClipDuration = clips.front().toMap().value("durationNs").toLongLong();
        controller.selectClip(clips.front().toMap().value("id").toString());
        controller.addGradeNode(0);
        const auto nodes = controller.selectedGradeNodes();
        if (nodes.isEmpty()) return EXIT_FAILURE;
        controller.setGradeParameter(
            nodes.front().toMap().value("id").toString(), QStringLiteral("exposure"), 0.25);
        controller.setColorPipelineMode(1);
        const auto deliveredBefore = controller.videoFramesDelivered();
        const auto processedBefore = controller.floatVideoFramesProcessed();
        QEventLoop previewLoop;
        QTimer previewPoll;
        QTimer previewTimeout;
        previewPoll.setInterval(10);
        previewTimeout.setSingleShot(true);
        QObject::connect(&previewPoll, &QTimer::timeout, &previewLoop, [&] {
            if (!controller.previewBusy() &&
                controller.sourceColorLutBindings() == static_cast<std::uint64_t>(clips.size())) {
                previewLoop.quit();
            }
        });
        QObject::connect(&previewTimeout, &QTimer::timeout, &previewLoop, &QEventLoop::quit);
        previewPoll.start();
        previewTimeout.start(15'000);
        previewLoop.exec();
        if (controller.previewBusy() ||
            controller.sourceColorLutBindings() != static_cast<std::uint64_t>(clips.size())) {
            qCritical().noquote() << "managed source LUT preparation failed"
                                  << "busy=" << controller.previewBusy()
                                  << "bindings=" << controller.sourceColorLutBindings()
                                  << "expected=" << clips.size();
            return EXIT_FAILURE;
        }
        controller.seek(0);
        controller.togglePlayback();
        QEventLoop playbackLoop;
        QTimer playbackPoll;
        QTimer playbackTimeout;
        playbackPoll.setInterval(10);
        playbackTimeout.setSingleShot(true);
        QObject::connect(&playbackPoll, &QTimer::timeout, &playbackLoop, [&] {
            if (controller.videoFramesDelivered() > deliveredBefore + 2 &&
                controller.playheadNs() > 100'000'000) playbackLoop.quit();
        });
        QObject::connect(&playbackTimeout, &QTimer::timeout, &playbackLoop, &QEventLoop::quit);
        playbackPoll.start();
        playbackTimeout.start(15'000);
        playbackLoop.exec();
        const auto passed = controller.videoFramesDelivered() > deliveredBefore &&
            controller.floatVideoFramesProcessed() == processedBefore &&
            controller.sourceColorLutBindings() == static_cast<std::uint64_t>(clips.size()) &&
            controller.sourceGpuColorLutBindings() == static_cast<std::uint64_t>(clips.size()) &&
            controller.playheadNs() > 100'000'000 &&
            controller.playheadNs() < firstClipDuration && controller.playing();
        qInfo().noquote() << "managed source LUT smoke counters"
                          << "delivered_delta="
                          << controller.videoFramesDelivered() - deliveredBefore
                          << "post_composite_float_delta="
                          << controller.floatVideoFramesProcessed() - processedBefore
                          << "bindings=" << controller.sourceColorLutBindings()
                          << "gpu_bindings=" << controller.sourceGpuColorLutBindings()
                          << "playhead_ns=" << controller.playheadNs()
                          << "passed=" << passed;
        controller.togglePlayback();
        return passed ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    if (!roundtripProject.isEmpty()) {
        const auto importedClips = controller.clips();
        if (importedClips.isEmpty()) return EXIT_FAILURE;
        if (controller.frameNumberAt(0) != 0 ||
            controller.frameNumberAt(controller.durationNs()) <= 0 ||
            controller.frameCountBetween(0, controller.durationNs()) <= 0 ||
            controller.timeText(1'234'000'000) != QStringLiteral("00:00:01.234")) {
            return EXIT_FAILURE;
        }
        const auto importedClipCount = importedClips.size();
        const auto first = importedClips.front().toMap();
        const auto firstId = first.value("id").toString();
        const auto sourceIn = first.value("sourceInNs").toLongLong();
        const auto clipDuration = first.value("durationNs").toLongLong();
        if (clipDuration <= 100'000'000) return EXIT_FAILURE;
        controller.selectClip(firstId);
        controller.trimClip(
            firstId,
            sourceIn + 17'000'000,
            clipDuration - 34'000'000);
        const auto trimmed = controller.clips().front().toMap();
        controller.seek(trimmed.value("durationNs").toLongLong() / 2);
        controller.splitAtPlayhead();
        controller.duplicateSelectedClip();
        controller.undo();
        controller.redo();
        const auto importedAssets = controller.mediaAssets();
        if (importedAssets.isEmpty()) return EXIT_FAILURE;
        controller.insertAssetAtTime(
            importedAssets.front().toMap().value("id").toString(),
            100'000'000);
        const auto beforeMultiDelete = controller.clips();
        if (beforeMultiDelete.size() < 2) return EXIT_FAILURE;
        controller.selectClip(beforeMultiDelete.front().toMap().value("id").toString());
        controller.selectClip(beforeMultiDelete.back().toMap().value("id").toString(), 1);
        if (controller.selectedClipIds().size() != 2) return EXIT_FAILURE;
        controller.deleteSelectedClip();
        if (controller.clips().size() != beforeMultiDelete.size() - 2) return EXIT_FAILURE;
        controller.undo();
        if (controller.clips().size() != beforeMultiDelete.size()) return EXIT_FAILURE;
        const auto beforeMultiDuplicate = controller.clips();
        controller.selectClip(beforeMultiDuplicate.front().toMap().value("id").toString());
        controller.selectClip(beforeMultiDuplicate.back().toMap().value("id").toString(), 1);
        controller.duplicateSelectedClip();
        if (controller.clips().size() != beforeMultiDuplicate.size() + 2 ||
            controller.selectedClipIds().size() != 2) {
            return EXIT_FAILURE;
        }
        controller.undo();
        if (controller.clips().size() != beforeMultiDuplicate.size()) return EXIT_FAILURE;
        const auto beforeGroupMove = controller.clips();
        const auto moveFirst = beforeGroupMove[0].toMap().value("id").toString();
        const auto moveSecond = beforeGroupMove[1].toMap().value("id").toString();
        controller.selectClip(moveFirst);
        controller.selectClip(moveSecond, 1);
        controller.moveClips(controller.selectedClipIds(), beforeGroupMove.size() - 2);
        const auto afterGroupMove = controller.clips();
        if (afterGroupMove[afterGroupMove.size() - 2].toMap().value("id").toString() != moveFirst ||
            afterGroupMove.back().toMap().value("id").toString() != moveSecond) {
            return EXIT_FAILURE;
        }
        controller.undo();
        QEventLoop previewRefreshLoop;
        QTimer previewRefreshTimeout;
        previewRefreshTimeout.setSingleShot(true);
        QObject::connect(
            &controller,
            &EditorController::previewBusyChanged,
            &previewRefreshLoop,
            [&controller, &previewRefreshLoop] {
                if (!controller.previewBusy() && controller.previewRebuildCount() > 0) {
                    previewRefreshLoop.quit();
                }
            });
        QObject::connect(
            &previewRefreshTimeout, &QTimer::timeout, &previewRefreshLoop, &QEventLoop::quit);
        previewRefreshTimeout.start(15'000);
        previewRefreshLoop.exec();
        if (controller.previewBusy() || controller.previewRebuildCount() == 0 ||
            controller.previewRebuildCount() > 2) {
            return EXIT_FAILURE;
        }
        const auto beforeRangeDeleteDuration = controller.durationNs();
        controller.seek(100'000'000);
        controller.setInPoint();
        controller.seek(600'000'000);
        controller.setOutPoint();
        if (controller.inPointNs() < 0 || controller.outPointNs() <= controller.inPointNs()) {
            return EXIT_FAILURE;
        }
        controller.extractMarkedRange();
        if (controller.durationNs() >= beforeRangeDeleteDuration) return EXIT_FAILURE;
        controller.undo();
        if (controller.durationNs() != beforeRangeDeleteDuration) return EXIT_FAILURE;
        const auto audioClipId = controller.clips().front().toMap().value("id").toString();
        controller.selectClip(audioClipId);
        controller.setSelectedClipVolumePercent(125);
        controller.setSelectedClipFadeInMs(200);
        controller.setSelectedClipFadeOutMs(300);
        const auto audioClip = controller.clips().front().toMap();
        if (audioClip.value("audioGain").toDouble() != 1.25 ||
            audioClip.value("audioFadeInNs").toLongLong() != 200'000'000 ||
            audioClip.value("audioFadeOutNs").toLongLong() != 300'000'000) {
            return EXIT_FAILURE;
        }
        controller.seek(700'000'000);
        controller.addCaptionAtPlayhead();
        if (controller.captions().size() != 1) return EXIT_FAILURE;
        controller.updateSelectedCaption(QStringLiteral("회귀 테스트 자막"), 900);
        if (controller.captions().front().toMap().value("text").toString() !=
            QStringLiteral("회귀 테스트 자막")) {
            return EXIT_FAILURE;
        }
        const auto captionId = controller.selectedCaptionId();
        controller.moveCaption(captionId, 1'100'000'000);
        controller.trimCaption(captionId, 1'200'000'000, 700'000'000);
        auto editedCaption = controller.captions().front().toMap();
        if (editedCaption.value("timelineInNs").toLongLong() != 1'200'000'000 ||
            editedCaption.value("durationNs").toLongLong() != 700'000'000) {
            return EXIT_FAILURE;
        }
        controller.undo();
        if (controller.captions().front().toMap().value("timelineInNs").toLongLong() !=
            1'100'000'000) {
            return EXIT_FAILURE;
        }
        controller.redo();
        const auto srtRoundtrip = roundtripProject + ".srt";
        QFile::remove(srtRoundtrip);
        controller.exportSrtUrl(QUrl::fromLocalFile(srtRoundtrip));
        if (!QFileInfo(srtRoundtrip).isFile()) return EXIT_FAILURE;
        controller.deleteSelectedCaption();
        if (!controller.captions().isEmpty()) return EXIT_FAILURE;
        controller.importSrtUrl(QUrl::fromLocalFile(srtRoundtrip));
        QFile::remove(srtRoundtrip);
        if (controller.captions().size() != 1 ||
            controller.captions().front().toMap().value("text").toString() !=
                QStringLiteral("회귀 테스트 자막")) {
            return EXIT_FAILURE;
        }
        const auto graphicId = controller.selectedCaptionId();
        controller.updateCaptionPosition(graphicId, 0.25, 0.35);
        controller.setSelectedCaptionFontSize(52);
        controller.setSelectedCaptionBackgroundOpacity(65);
        controller.setStampWorker(QStringLiteral("테스트 작업자"));
        controller.setStampInformation(QStringLiteral("검수본 v2"));
        controller.setStampBarPercent(10);
        controller.setStampOpacity(75);
        controller.setStampMode(1);
        controller.setStampEnabled(true);
        controller.setExportContainer(3);
        controller.setGifResolution(2);
        controller.setGifFrameRate(3);
        controller.setGifColors(2);
        controller.setGifDither(1);
        controller.setGifLoop(false);
        controller.selectClip(audioClipId);
        const auto beforeSpeedDuration = controller.durationNs();
        controller.setSelectedClipSpeedPercent(150);
        if (controller.durationNs() >= beforeSpeedDuration ||
            std::abs(controller.clips().front().toMap().value("playbackRate").toDouble() - 1.5) >
                0.0001) {
            return EXIT_FAILURE;
        }
        controller.undo();
        if (controller.durationNs() != beforeSpeedDuration) return EXIT_FAILURE;
        controller.redo();
        const auto dissolveClips = controller.clips();
        if (dissolveClips.size() < 3) return EXIT_FAILURE;
        const auto dissolveClipIndex = 2;
        const auto dissolveClipId = dissolveClips.at(dissolveClipIndex).toMap().value("id").toString();
        controller.selectClip(dissolveClipId);
        controller.setSelectedClipDissolveMs(300);
        if (controller.clips().at(dissolveClipIndex).toMap().value("transitionInNs").toLongLong() !=
            300'000'000) {
            return EXIT_FAILURE;
        }
        controller.selectClip(audioClipId);
        controller.setSelectedClipBrightness(10);
        controller.setSelectedClipContrast(115);
        controller.setSelectedClipSaturation(85);
        controller.addGradeNode(0);
        const auto gradeNodes = controller.selectedGradeNodes();
        if (gradeNodes.size() != 1) return EXIT_FAILURE;
        const auto gradeId = gradeNodes.front().toMap().value("id").toString();
        controller.setGradeParameter(gradeId, QStringLiteral("exposure"), 1.25);
        controller.setGradeNodeMix(gradeId, 80);
        if (importedAssets.front().toMap().value("kind").toString() == "imageSequence") {
            const auto submittedBefore = controller.scrubFramesSubmitted();
            controller.scrub(0, true);
            QEventLoop floatPreviewLoop;
            QTimer floatPreviewPoll;
            QTimer floatPreviewTimeout;
            floatPreviewPoll.setInterval(10);
            floatPreviewTimeout.setSingleShot(true);
            QObject::connect(&floatPreviewPoll, &QTimer::timeout, &floatPreviewLoop, [&] {
                if (controller.scrubFramesSubmitted() > submittedBefore) floatPreviewLoop.quit();
            });
            QObject::connect(&floatPreviewTimeout, &QTimer::timeout,
                             &floatPreviewLoop, &QEventLoop::quit);
            floatPreviewPoll.start();
            floatPreviewTimeout.start(5'000);
            floatPreviewLoop.exec();
            if (controller.scrubFramesSubmitted() <= submittedBefore ||
                !controller.status().contains(QStringLiteral("float 프레임"))) {
                return EXIT_FAILURE;
            }
            const auto playbackFramesBefore = controller.scrubFramesSubmitted();
            const auto playbackPositionBefore = controller.playheadNs();
            controller.togglePlayback();
            QEventLoop floatPlaybackLoop;
            QTimer floatPlaybackPoll;
            QTimer floatPlaybackTimeout;
            floatPlaybackPoll.setInterval(10);
            floatPlaybackTimeout.setSingleShot(true);
            QObject::connect(&floatPlaybackPoll, &QTimer::timeout, &floatPlaybackLoop, [&] {
                if (controller.playheadNs() > playbackPositionBefore + 100'000'000 &&
                    controller.scrubFramesSubmitted() > playbackFramesBefore) {
                    floatPlaybackLoop.quit();
                }
            });
            QObject::connect(&floatPlaybackTimeout, &QTimer::timeout,
                             &floatPlaybackLoop, &QEventLoop::quit);
            floatPlaybackPoll.start();
            floatPlaybackTimeout.start(5'000);
            floatPlaybackLoop.exec();
            if (!controller.playing() ||
                controller.playheadNs() <= playbackPositionBefore + 100'000'000 ||
                controller.scrubFramesSubmitted() <= playbackFramesBefore) {
                return EXIT_FAILURE;
            }
            controller.togglePlayback();
            if (controller.playing()) return EXIT_FAILURE;
        }
        const auto expectedDuration = controller.durationNs();
        const auto expectedClipCount = controller.clips().size();
        controller.saveProject(roundtripProject);
        if (!QFileInfo::exists(roundtripProject)) {
            return EXIT_FAILURE;
        }
        controller.loadProject(roundtripProject);
        const auto loadedAudio = controller.clips().front().toMap();
        const auto loadedDissolve = controller.clips().at(dissolveClipIndex).toMap();
        controller.selectClip(audioClipId);
        const auto loadedGradeNodes = controller.selectedGradeNodes();
        const auto loadedGrade = loadedGradeNodes.isEmpty()
            ? QVariantMap{} : loadedGradeNodes.front().toMap();
        const auto loadedGradeParameters = loadedGrade.value("parameters").toMap();
        return controller.durationNs() == expectedDuration && expectedDuration > 0 &&
               controller.clips().size() == expectedClipCount &&
               loadedAudio.value("audioGain").toDouble() == 1.25 &&
               loadedAudio.value("audioFadeInNs").toLongLong() == 200'000'000 &&
               loadedAudio.value("audioFadeOutNs").toLongLong() == 300'000'000 &&
               std::abs(loadedAudio.value("playbackRate").toDouble() - 1.5) < 0.0001 &&
               std::abs(loadedAudio.value("brightness").toDouble() - 0.1) < 0.0001 &&
               std::abs(loadedAudio.value("contrast").toDouble() - 1.15) < 0.0001 &&
               std::abs(loadedAudio.value("saturation").toDouble() - 0.85) < 0.0001 &&
               loadedDissolve.value("transitionInNs").toLongLong() == 300'000'000 &&
               controller.captions().size() == 1 &&
               controller.captions().front().toMap().value("text").toString() ==
                   QStringLiteral("회귀 테스트 자막") &&
               std::abs(controller.captions().front().toMap().value("positionX").toDouble() -
                        0.25) < 0.0001 &&
               std::abs(controller.captions().front().toMap().value("positionY").toDouble() -
                        0.35) < 0.0001 &&
               controller.captions().front().toMap().value("fontSize").toInt() == 52 &&
               controller.captions().front().toMap().value("backgroundOpacity").toInt() == 65 &&
               controller.stampEnabled() && controller.stampBarPercent() == 10 &&
               controller.stampOpacity() == 75 && controller.stampMode() == 1 &&
               controller.stampWorker() == QStringLiteral("테스트 작업자") &&
               controller.stampInformation() == QStringLiteral("검수본 v2") &&
               controller.exportContainer() == 3 && controller.gifPreset() == 3 &&
               controller.gifResolution() == 2 && controller.gifFrameRate() == 3 &&
               controller.gifColors() == 2 && controller.gifDither() == 1 &&
               !controller.gifLoop() &&
               loadedGradeNodes.size() == 1 && loadedGrade.value("mixPercent").toInt() == 80 &&
               std::abs(loadedGradeParameters.value("exposure").toDouble() - 1.25) < 0.0001 &&
               expectedClipCount == importedClipCount + 4
            ? EXIT_SUCCESS
            : EXIT_FAILURE;
    }
    if (floatExportSmoke) {
        const auto exportClips = controller.clips();
        if (exportClips.isEmpty() ||
            controller.mediaAssets().front().toMap().value("kind").toString() !=
                QStringLiteral("imageSequence")) {
            return EXIT_FAILURE;
        }
        controller.selectClip(exportClips.front().toMap().value("id").toString());
        controller.addGradeNode(0);
        const auto nodes = controller.selectedGradeNodes();
        if (nodes.isEmpty()) return EXIT_FAILURE;
        controller.setGradeParameter(
            nodes.front().toMap().value("id").toString(), QStringLiteral("exposure"), 0.25);
        const auto smokeSuffix = QFileInfo(exportSmokeOutput).suffix().toLower();
        if (smokeSuffix == QStringLiteral("gif")) controller.setExportContainer(3);
        else if (smokeSuffix == QStringLiteral("mov")) controller.setExportContainer(2);
        else if (smokeSuffix == QStringLiteral("mkv")) controller.setExportContainer(1);
        bool exportSucceeded = false;
        QEventLoop exportLoop;
        QTimer exportTimeout;
        exportTimeout.setSingleShot(true);
        QObject::connect(
            &controller, &EditorController::exportFinished, &exportLoop,
            [&exportSucceeded, &exportLoop](bool success, const QUrl&) {
                exportSucceeded = success;
                exportLoop.quit();
            });
        QObject::connect(&exportTimeout, &QTimer::timeout, &exportLoop, &QEventLoop::quit);
        controller.exportTimelineUrl(QUrl::fromLocalFile(exportSmokeOutput));
        exportTimeout.start(120'000);
        exportLoop.exec();
        return exportSucceeded && QFileInfo(exportSmokeOutput).isFile() &&
                QFileInfo(exportSmokeOutput).size() > 0
            ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    if (!exportSmokeOutput.isEmpty()) {
        if (gifExportSmoke) {
            controller.setExportContainer(3);
            controller.setGifPreset(0);
        } else if (hevcExportSmoke) {
            controller.setExportCodec(1);
            controller.setExportContainer(1);
            controller.setExportQuality(2);
        }
        const auto exportClips = controller.clips();
        if (exportClips.isEmpty()) return EXIT_FAILURE;
        controller.selectClip(exportClips.front().toMap().value("id").toString());
        controller.setSelectedClipVolumePercent(80);
        controller.setSelectedClipFadeInMs(150);
        controller.setSelectedClipFadeOutMs(250);
        controller.setSelectedClipBrightness(10);
        controller.setSelectedClipContrast(115);
        controller.setSelectedClipSaturation(85);
        if (exportClips.size() < 2) return EXIT_FAILURE;
        controller.selectClip(exportClips.at(1).toMap().value("id").toString());
        controller.setSelectedClipDissolveMs(300);
        controller.selectClip(exportClips.front().toMap().value("id").toString());
        if (!gifExportSmoke) {
            controller.setExportResolution(3);
            controller.setExportFrameRate(3);
        }
        controller.seek(500'000'000);
        controller.addCaptionAtPlayhead();
        controller.updateSelectedCaption(QStringLiteral("출력 자막"), 1200);
        controller.updateCaptionPosition(controller.selectedCaptionId(), 0.3, 0.4);
        controller.setSelectedCaptionFontSize(48);
        controller.setSelectedCaptionBackgroundOpacity(60);
        controller.setStampWorker(QStringLiteral("자동 회귀"));
        controller.setStampInformation(QStringLiteral("출력 검증본"));
        controller.setStampOpacity(75);
        controller.setStampMode(1);
        controller.setStampEnabled(true);
        // Export immediately after structural revisions. The output must capture the newest
        // model snapshot even while the debounced preview rebuild is still pending.
        controller.splitAtPlayhead();
        controller.undo();
        controller.redo();
        bool exportSucceeded = false;
        QEventLoop exportLoop;
        QTimer exportTimeout;
        exportTimeout.setSingleShot(true);
        QObject::connect(
            &controller,
            &EditorController::exportFinished,
            &exportLoop,
            [&exportSucceeded, &exportLoop](bool success, const QUrl&) {
                exportSucceeded = success;
                exportLoop.quit();
            });
        QObject::connect(&exportTimeout, &QTimer::timeout, &exportLoop, &QEventLoop::quit);
        controller.exportTimelineUrl(QUrl::fromLocalFile(exportSmokeOutput));
        exportTimeout.start(120'000);
        exportLoop.exec();
        return exportSucceeded && controller.lastExportMatchedPreview() &&
               QFileInfo(exportSmokeOutput).isFile()
            ? EXIT_SUCCESS
            : EXIT_FAILURE;
    }
    if (!exportProjectOutput.isEmpty()) {
        controller.setExportContainer(0);
        controller.setExportCodec(2);
        bool exportSucceeded = false;
        QEventLoop exportLoop;
        QTimer exportTimeout;
        exportTimeout.setSingleShot(true);
        QObject::connect(
            &controller,
            &EditorController::exportFinished,
            &exportLoop,
            [&exportSucceeded, &exportLoop](bool success, const QUrl&) {
                exportSucceeded = success;
                exportLoop.quit();
            });
        QObject::connect(&exportTimeout, &QTimer::timeout, &exportLoop, &QEventLoop::quit);
        controller.exportTimelineUrl(QUrl::fromLocalFile(exportProjectOutput));
        exportTimeout.start(120'000);
        exportLoop.exec();
        return exportSucceeded && controller.lastExportUsedStreamCopy() &&
               controller.lastExportMatchedPreview() &&
               QFileInfo(exportProjectOutput).isFile()
            ? EXIT_SUCCESS
            : EXIT_FAILURE;
    }
    if (playbackSmoke) {
        const auto playbackClips = controller.clips();
        if (playbackClips.isEmpty()) return EXIT_FAILURE;
        controller.selectClip(playbackClips.front().toMap().value("id").toString());
        controller.setSelectedClipVolumePercent(75);
        controller.setSelectedClipFadeInMs(200);
        controller.setSelectedClipFadeOutMs(300);
        controller.setSelectedClipSpeedPercent(150);
        controller.setSelectedClipBrightness(10);
        controller.setSelectedClipContrast(115);
        controller.setSelectedClipSaturation(85);
        if (playbackClips.size() < 2) return EXIT_FAILURE;
        controller.selectClip(playbackClips.at(1).toMap().value("id").toString());
        controller.setSelectedClipDissolveMs(300);
        controller.selectClip(playbackClips.front().toMap().value("id").toString());
        controller.seek(500'000'000);
        controller.addCaptionAtPlayhead();
        controller.updateSelectedCaption(QStringLiteral("미리보기 자막"), 1200);
        QTimer::singleShot(700, &controller, [&controller] { controller.scrub(250'000'000, false); });
        QTimer::singleShot(730, &controller, [&controller] { controller.scrub(900'000'000, false); });
        QTimer::singleShot(760, &controller, [&controller] { controller.scrub(1'400'000'000, false); });
        QTimer::singleShot(850, &controller, [&controller] { controller.scrub(500'000'000, true); });
        QTimer::singleShot(1100, &controller, &EditorController::togglePlayback);
        QTimer::singleShot(
            loopSmoke ? 9000 : 5000,
            &application,
            [&application, &controller, offscreenPresentationSmoke, loopSmoke] {
                qInfo().noquote() << "playback smoke counters"
                                  << "received=" << controller.videoFramesReceived()
                                  << "delivered=" << controller.videoFramesDelivered()
                                  << "presented=" << controller.videoFramesPresented()
                                  << "scrub_cached=" << controller.scrubFramesSubmitted()
                                  << "surface_exposed=" << controller.videoSurfaceExposed()
                                  << "playhead_ns=" << controller.playheadNs()
                                  << "failed=" << controller.previewFailed();
                if (controller.previewFailed()) application.exit(14);
                else if (loopSmoke &&
                         (!controller.playing() || controller.playheadNs() >= controller.durationNs())) {
                    application.exit(17);
                }
                else if (controller.playheadNs() <= 750'000'000) application.exit(10);
                else if (controller.inProcessPreview() && controller.videoFramesReceived() < 10) application.exit(11);
                else if (controller.inProcessPreview() && controller.videoFramesDelivered() < 10) application.exit(12);
                else if (controller.scrubFramesSubmitted() < 4) application.exit(16);
                else if (offscreenPresentationSmoke && !controller.videoSurfaceExposed()) application.exit(15);
                else if (controller.inProcessPreview() && controller.videoSurfaceExposed() &&
                         controller.videoFramesPresented() < 10) application.exit(13);
                else application.exit(EXIT_SUCCESS);
            });
    }
    return application.exec();
}
