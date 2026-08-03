#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QUrl>

int main(int argc, char* argv[]) {
    QGuiApplication application(argc, argv);
    application.setApplicationName("ffmpegGUI Next");
    application.setOrganizationName("CharlieYang0040");

    QQmlApplicationEngine engine;
    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &application,
        [] { QCoreApplication::exit(EXIT_FAILURE); },
        Qt::QueuedConnection);
    engine.loadFromModule("FFGuiNext", "Main");
    return application.exec();
}
