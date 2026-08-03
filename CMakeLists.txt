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

include(CTest)

add_library(ffgui_core STATIC
    src/core/media_asset.cpp
    src/core/timeline_model.cpp
)
add_library(ffgui::core ALIAS ffgui_core)

target_include_directories(ffgui_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_compile_features(ffgui_core PUBLIC cxx_std_23)

if(MSVC)
    target_compile_options(ffgui_core PRIVATE /W4 /permissive- /EHsc /utf-8)
else()
    target_compile_options(ffgui_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
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
endif()

if(FFGUI_BUILD_DESKTOP)
    find_package(Qt6 6.8 QUIET COMPONENTS Quick QuickControls2)
    if(Qt6_FOUND)
        qt_standard_project_setup(REQUIRES 6.8)
        qt_add_executable(ffmpegGUI-next apps/desktop/main.cpp)
        qt_add_qml_module(ffmpegGUI-next
            URI FFGuiNext
            VERSION 1.0
            QML_FILES apps/desktop/Main.qml
        )
        target_link_libraries(ffmpegGUI-next PRIVATE
            ffgui::core
            Qt6::Quick
            Qt6::QuickControls2
        )
        set_target_properties(ffmpegGUI-next PROPERTIES
            WIN32_EXECUTABLE TRUE
            MACOSX_BUNDLE TRUE
        )
    else()
        message(STATUS "Qt 6.8+ was not found; building the native core and tests only")
    endif()
endif()
