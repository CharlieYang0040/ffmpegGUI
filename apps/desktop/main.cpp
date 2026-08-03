#include "timeline_view.hpp"
#include "editor_controller.hpp"

#include <QGuiApplication>
#include <QEventLoop>
#include <QFileInfo>
#include <QDir>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QStandardPaths>
#include <QTimer>
#include <QUrl>
#include <qqml.h>

namespace {

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
        if (arguments[index] == "--export-smoke" && index + 1 < arguments.size()) {
            exportSmokeOutput = arguments[++index];
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
    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &application,
        [] { QCoreApplication::exit(EXIT_FAILURE); },
        Qt::QueuedConnection);
    engine.loadFromModule("FFGuiNext", "Main");
    if (!mediaFiles.isEmpty()) {
        controller.loadFiles(mediaFiles);
    }
    if (!exportProjectSmoke.isEmpty()) {
        controller.loadProject(exportProjectSmoke);
        if (controller.durationNs() <= 0) return EXIT_FAILURE;
    }
    if ((!roundtripProject.isEmpty() || !exportSmokeOutput.isEmpty() || playbackSmoke) &&
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
    if (!roundtripProject.isEmpty()) {
        const auto importedClips = controller.clips();
        if (importedClips.isEmpty()) return EXIT_FAILURE;
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
        QTimer::singleShot(100, &previewRefreshLoop, &QEventLoop::quit);
        previewRefreshLoop.exec();
        if (controller.previewRebuildCount() == 0 || controller.previewRebuildCount() > 2) {
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
        const auto expectedDuration = controller.durationNs();
        const auto expectedClipCount = controller.clips().size();
        controller.saveProject(roundtripProject);
        if (!QFileInfo::exists(roundtripProject)) {
            return EXIT_FAILURE;
        }
        controller.loadProject(roundtripProject);
        const auto loadedAudio = controller.clips().front().toMap();
        return controller.durationNs() == expectedDuration && expectedDuration > 0 &&
               controller.clips().size() == expectedClipCount &&
               loadedAudio.value("audioGain").toDouble() == 1.25 &&
               loadedAudio.value("audioFadeInNs").toLongLong() == 200'000'000 &&
               loadedAudio.value("audioFadeOutNs").toLongLong() == 300'000'000 &&
               controller.captions().size() == 1 &&
               controller.captions().front().toMap().value("text").toString() ==
                   QStringLiteral("회귀 테스트 자막") &&
               expectedClipCount == importedClipCount + 4
            ? EXIT_SUCCESS
            : EXIT_FAILURE;
    }
    if (!exportSmokeOutput.isEmpty()) {
        const auto exportClips = controller.clips();
        if (exportClips.isEmpty()) return EXIT_FAILURE;
        controller.selectClip(exportClips.front().toMap().value("id").toString());
        controller.setSelectedClipVolumePercent(80);
        controller.setSelectedClipFadeInMs(150);
        controller.setSelectedClipFadeOutMs(250);
        controller.seek(500'000'000);
        controller.addCaptionAtPlayhead();
        controller.updateSelectedCaption(QStringLiteral("출력 자막"), 1200);
        QEventLoop audioPreviewRefreshLoop;
        QTimer::singleShot(100, &audioPreviewRefreshLoop, &QEventLoop::quit);
        audioPreviewRefreshLoop.exec();
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
        controller.seek(500'000'000);
        controller.addCaptionAtPlayhead();
        controller.updateSelectedCaption(QStringLiteral("미리보기 자막"), 1200);
        QTimer::singleShot(150, &controller, &EditorController::togglePlayback);
        QTimer::singleShot(5000, &application, [&application, &controller] {
            if (controller.playheadNs() < 500'000'000) application.exit(10);
            else if (controller.gpuSceneGraphPreview() && controller.videoFramesReceived() < 10) application.exit(11);
            else if (controller.gpuSceneGraphPreview() && controller.videoFramesDelivered() < 10) application.exit(12);
            else if (controller.gpuSceneGraphPreview() && controller.videoFramesPresented() < 10) application.exit(13);
            else application.exit(EXIT_SUCCESS);
        });
    }
    return application.exec();
}
