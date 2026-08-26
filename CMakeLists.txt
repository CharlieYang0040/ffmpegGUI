cmake_minimum_required(VERSION 3.28)

project(
    ffmpegGUINext
    VERSION 0.1.4
    DESCRIPTION "Native magnetic cut editor for Windows"
    LANGUAGES CXX
)

find_package(OpenColorIO 2.5.2 CONFIG REQUIRED)
find_package(OpenImageIO 3.1 CONFIG REQUIRED)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(FFGUI_BUILD_DESKTOP "Build the Qt Quick desktop application when Qt is available" ON)
option(FFGUI_ENABLE_GES "Build the GStreamer Editing Services adapter when available" ON)

include(CTest)

add_library(ffgui_core STATIC
    src/color/ocio_engine.cpp
    src/color/grade_processor.cpp
    src/color/color_frame_processor.cpp
    src/color/look_export.cpp
    src/color/shot_matching.cpp
    src/color/review_tools.cpp
    src/color/scope_analyzer.cpp
    src/core/color_pipeline.cpp
    src/core/ffprobe_parser.cpp
    src/core/media_asset.cpp
    src/core/media_source.cpp
    src/core/render_preflight.cpp
    src/core/subtitle_srt.cpp
    src/core/timeline_model.cpp
    src/media/oiio_probe.cpp
    src/media/oiio_frame_source.cpp
    src/render/timeline_frame_server.cpp
    src/export/ffmpeg_export_plan.cpp
)
add_library(ffgui::core ALIAS ffgui_core)

target_include_directories(ffgui_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_compile_features(ffgui_core PUBLIC cxx_std_23)
target_link_libraries(ffgui_core PUBLIC OpenColorIO::OpenColorIO OpenImageIO::OpenImageIO)

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
            gstreamer-base-1.0>=1.28
            gstreamer-app-1.0>=1.28
            gstreamer-d3d11-1.0>=1.28
            gst-editing-services-1.0>=1.28
        )
    endif()
    if(GES_FOUND)
        add_library(ffgui_ges STATIC
            src/integration/ges/ges_sequence_player.cpp
            src/integration/ges/gst_color_lut_filter.cpp
            src/integration/ges/gst_d3d11_color_bin.cpp
            src/integration/ges/gst_d3d11_color_lut_filter.cpp
        )
        add_library(ffgui::ges ALIAS ffgui_ges)
        target_include_directories(ffgui_ges PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
        target_link_libraries(ffgui_ges PUBLIC ffgui::core PkgConfig::GES)
        if(WIN32)
            target_link_libraries(ffgui_ges PRIVATE d3dcompiler)
        endif()
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
        add_executable(ffgui_ges_seek_benchmark tools/ges_seek_benchmark.cpp)
        target_link_libraries(ffgui_ges_seek_benchmark PRIVATE ffgui::ges)
        add_executable(ffgui_ges_playback_soak tools/ges_playback_soak.cpp)
        target_link_libraries(ffgui_ges_playback_soak PRIVATE ffgui::ges Psapi)
        if(MSVC)
            target_compile_options(ffgui_ges_smoke PRIVATE /W4 /permissive- /EHsc /utf-8)
            target_compile_options(
                ffgui_ges_seek_benchmark PRIVATE /W4 /permissive- /EHsc /utf-8)
            target_compile_options(
                ffgui_ges_playback_soak PRIVATE /W4 /permissive- /EHsc /utf-8)
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
                apps/desktop/color_scope_item.cpp
                apps/desktop/color_scope_item.hpp
                apps/desktop/ffprobe_analyzer.cpp
                apps/desktop/ffprobe_analyzer.hpp
                apps/desktop/hdr_display.cpp
                apps/desktop/hdr_display.hpp
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
                ENVIRONMENT "QT_QPA_PLATFORM=windows"
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
        if(WIN32)
            target_link_libraries(ffmpegGUI-next PRIVATE dxgi)
        endif()
        if(FFGUI_GES_AVAILABLE)
            target_link_libraries(ffmpegGUI-next PRIVATE ffgui::ges)
            target_compile_definitions(ffmpegGUI-next PRIVATE FFGUI_HAS_GES=1)
        endif()
        set_target_properties(ffmpegGUI-next PROPERTIES
            WIN32_EXECUTABLE TRUE
            MACOSX_BUNDLE TRUE
        )
        if(WIN32 AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/.tools/gstreamer/bin")
            get_filename_component(FFGUI_QT_ROOT "${Qt6_DIR}/../../.." ABSOLUTE)
            add_custom_command(TARGET ffmpegGUI-next POST_BUILD
                COMMAND powershell -NoProfile -ExecutionPolicy Bypass
                    -File "${CMAKE_CURRENT_SOURCE_DIR}/scripts/deploy_dev_runtime.ps1"
                    -Application "$<TARGET_FILE:ffmpegGUI-next>"
                    -Configuration "$<CONFIG>"
                    -QtRoot "${FFGUI_QT_ROOT}"
                    -GStreamerRoot "${CMAKE_CURRENT_SOURCE_DIR}/.tools/gstreamer"
                COMMENT "Deploying Qt and GStreamer runtime for direct desktop launch"
                VERBATIM)
        endif()
    else()
        message(STATUS "Qt 6.8+ was not found; building the native core and tests only")
    endif()
endif()
