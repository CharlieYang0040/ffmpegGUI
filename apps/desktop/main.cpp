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
        const auto expectedDuration = controller.durationNs();
        controller.saveProject(roundtripProject);
        if (!QFileInfo::exists(roundtripProject)) {
            return EXIT_FAILURE;
        }
        controller.loadProject(roundtripProject);
        return controller.durationNs() == expectedDuration && expectedDuration > 0
            ? EXIT_SUCCESS
            : EXIT_FAILURE;
    }
    if (!exportSmokeOutput.isEmpty()) {
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
        QTimer::singleShot(100, &controller, &EditorController::togglePlayback);
        QTimer::singleShot(5000, &application, [&application, &controller] {
            application.exit(controller.playheadNs() >= 500'000'000 ? EXIT_SUCCESS : EXIT_FAILURE);
        });
    }
    return application.exec();
}
