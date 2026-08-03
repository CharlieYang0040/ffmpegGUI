#include "timeline_view.hpp"
#include "editor_controller.hpp"

#include <QGuiApplication>
#include <QFileInfo>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QUrl>
#include <qqml.h>

int main(int argc, char* argv[]) {
    QGuiApplication application(argc, argv);
    application.setApplicationName("ffmpegGUI Next");
    application.setOrganizationName("CharlieYang0040");
    QQuickStyle::setStyle("Basic");
    QWindow videoWindow;
    EditorController controller(nullptr);
    controller.setVideoWindow(&videoWindow);
    EditorController::setSingletonInstance(&controller);

    QStringList mediaFiles;
    QString roundtripProject;
    const auto arguments = application.arguments();
    for (int index = 1; index < arguments.size(); ++index) {
        if (arguments[index] == "--project-roundtrip" && index + 1 < arguments.size()) {
            roundtripProject = arguments[++index];
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
    return application.exec();
}
