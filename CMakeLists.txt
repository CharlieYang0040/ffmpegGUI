cmake_minimum_required(VERSION 3.28)

project(
    ffmpegGUINext
    VERSION 0.1.0
    DESCRIPTION "Native magnetic cut editor for Windows"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(FFGUI_BUILD_DESKTOP "Build the Qt Quick desktop application when Qt is available" ON)
option(FFGUI_ENABLE_GES "Build the GStreamer Editing Services adapter when available" ON)

include(CTest)

add_library(ffgui_core STATIC
    src/core/ffprobe_parser.cpp
    src/core/media_asset.cpp
    src/core/timeline_model.cpp
    src/export/ffmpeg_export_plan.cpp
)
add_library(ffgui::core ALIAS ffgui_core)

target_include_directories(ffgui_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_compile_features(ffgui_core PUBLIC cxx_std_23)

if(MSVC)
    target_compile_options(ffgui_core PRIVATE /W4 /permissive- /EHsc /utf-8)
else()
    target_compile_options(ffgui_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
endif()

set(FFGUI_GES_AVAILABLE OFF)
if(FFGUI_ENABLE_GES)
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        pkg_check_modules(GES QUIET IMPORTED_TARGET
            gstreamer-1.0>=1.28
            gstreamer-video-1.0>=1.28
            gstreamer-app-1.0>=1.28
            gstreamer-d3d11-1.0>=1.28
            gst-editing-services-1.0>=1.28
        )
    endif()
    if(GES_FOUND)
        add_library(ffgui_ges STATIC
            src/integration/ges/ges_sequence_player.cpp
        )
        add_library(ffgui::ges ALIAS ffgui_ges)
        target_include_directories(ffgui_ges PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
        target_link_libraries(ffgui_ges PUBLIC ffgui::core PkgConfig::GES)
        target_compile_features(ffgui_ges PUBLIC cxx_std_23)
        if(MSVC)
            target_compile_options(ffgui_ges PRIVATE /W4 /permissive- /EHsc /utf-8)
        else()
            target_compile_options(ffgui_ges PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
        endif()
        set(FFGUI_GES_AVAILABLE ON)
        message(STATUS "GStreamer Editing Services enabled")

        add_executable(ffgui_ges_smoke tools/ges_smoke.cpp)
        target_link_libraries(ffgui_ges_smoke PRIVATE ffgui::ges)
        if(MSVC)
            target_compile_options(ffgui_ges_smoke PRIVATE /W4 /permissive- /EHsc /utf-8)
        endif()
    else()
        message(STATUS "GStreamer Editing Services 1.28+ was not found; adapter disabled")
    endif()
endif()

if(BUILD_TESTING)
    add_executable(ffgui_core_tests tests/core_tests.cpp)
    target_link_libraries(ffgui_core_tests PRIVATE ffgui::core)
    if(MSVC)
        target_compile_options(ffgui_core_tests PRIVATE /W4 /permissive- /EHsc /utf-8)
    else()
        target_compile_options(ffgui_core_tests PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
    endif()
    add_test(NAME core COMMAND ffgui_core_tests)

    add_executable(ffgui_core_benchmark tools/core_benchmark.cpp)
    target_link_libraries(ffgui_core_benchmark PRIVATE ffgui::core)
    if(MSVC)
        target_compile_options(ffgui_core_benchmark PRIVATE /W4 /permissive- /EHsc /utf-8)
    endif()
endif()

if(FFGUI_BUILD_DESKTOP)
    find_package(Qt6 6.8 QUIET COMPONENTS Concurrent Quick QuickControls2)
    if(Qt6_FOUND)
        qt_standard_project_setup(REQUIRES 6.8)
        qt_add_executable(ffmpegGUI-next
            apps/desktop/main.cpp
        )
        qt_add_qml_module(ffmpegGUI-next
            URI FFGuiNext
            VERSION 1.0
            QML_FILES apps/desktop/Main.qml
            SOURCES
                apps/desktop/editor_controller.cpp
                apps/desktop/editor_controller.hpp
                apps/desktop/d3d11_video_item.cpp
                apps/desktop/d3d11_video_item.hpp
                apps/desktop/ffprobe_analyzer.cpp
                apps/desktop/ffprobe_analyzer.hpp
                apps/desktop/timeline_view.cpp
                apps/desktop/timeline_view.hpp
        )

        if(BUILD_TESTING)
            add_executable(ffgui_timeline_view_tests
                tests/timeline_view_tests.cpp
                apps/desktop/timeline_view.cpp
                apps/desktop/timeline_view.hpp
            )
            target_include_directories(ffgui_timeline_view_tests PRIVATE apps/desktop)
            target_link_libraries(ffgui_timeline_view_tests PRIVATE Qt6::Quick)
            if(MSVC)
                target_compile_options(
                    ffgui_timeline_view_tests PRIVATE /W4 /permissive- /EHsc /utf-8)
            endif()
            add_test(NAME timeline_view COMMAND ffgui_timeline_view_tests)
            set_tests_properties(timeline_view PROPERTIES
                ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
                ENVIRONMENT_MODIFICATION
                    "PATH=path_list_prepend:$<TARGET_FILE_DIR:Qt6::Core>"
            )
        endif()
        target_link_libraries(ffmpegGUI-next PRIVATE
            ffgui::core
            Qt6::Quick
            Qt6::QuickControls2
            Qt6::Concurrent
        )
        target_include_directories(ffmpegGUI-next PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/apps/desktop")
        if(FFGUI_GES_AVAILABLE)
            target_link_libraries(ffmpegGUI-next PRIVATE ffgui::ges)
            target_compile_definitions(ffmpegGUI-next PRIVATE FFGUI_HAS_GES=1)
        endif()
        set_target_properties(ffmpegGUI-next PROPERTIES
            WIN32_EXECUTABLE TRUE
            MACOSX_BUNDLE TRUE
        )
    else()
        message(STATUS "Qt 6.8+ was not found; building the native core and tests only")
    endif()
endif()
