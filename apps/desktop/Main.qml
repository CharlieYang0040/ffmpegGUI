import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import FFGuiNext

ApplicationWindow {
    id: root
    visible: true
    width: 1440
    height: 900
    minimumWidth: 1100
    minimumHeight: 700
    title: "ffmpegGUI Next"
    color: "#111419"

    palette.window: "#111419"
    palette.windowText: "#e8edf2"
    palette.base: "#171b21"
    palette.text: "#e8edf2"
    palette.button: "#222831"
    palette.buttonText: "#e8edf2"
    palette.highlight: "#5b8cff"

    Shortcut { sequence: StandardKey.Undo; enabled: EditorController.canUndo; onActivated: EditorController.undo() }
    Shortcut { sequence: StandardKey.Redo; enabled: EditorController.canRedo; onActivated: EditorController.redo() }

    FileDialog {
        id: mediaDialog
        title: "영상 추가"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["영상 파일 (*.mp4 *.mkv *.mov *.avi *.webm)", "모든 파일 (*)"]
        onAccepted: EditorController.loadUrls(selectedFiles)
    }
    FileDialog {
        id: openProjectDialog
        title: "프로젝트 열기"
        fileMode: FileDialog.OpenFile
        nameFilters: ["ffmpegGUI Next 프로젝트 (*.ffnext)"]
        onAccepted: EditorController.loadProjectUrl(selectedFile)
    }
    FileDialog {
        id: saveProjectDialog
        title: "프로젝트 저장"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "ffnext"
        nameFilters: ["ffmpegGUI Next 프로젝트 (*.ffnext)"]
        onAccepted: EditorController.saveProjectUrl(selectedFile)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 1

        ToolBar {
            Layout.fillWidth: true
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                Label { text: "ffmpegGUI"; font.pixelSize: 18; font.bold: true }
                Button { text: "영상 추가"; onClicked: mediaDialog.open() }
                Button { text: "열기"; onClicked: openProjectDialog.open() }
                Button {
                    text: "저장"
                    enabled: EditorController.durationNs > 0
                    onClicked: saveProjectDialog.open()
                }
                Item { Layout.fillWidth: true }
                Button { text: "내보내기"; enabled: false }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            Frame {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 240
                Label { anchors.centerIn: parent; text: "미디어"; color: "#8994a3" }
            }

            Frame {
                SplitView.fillWidth: true
                background: Rectangle { color: "#080a0d" }

                WindowContainer {
                    anchors.fill: parent
                    window: EditorController.videoWindow
                }
            }

            Frame {
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 280
                SplitView.maximumWidth: 380
                Label { anchors.centerIn: parent; text: "출력"; color: "#8994a3" }
            }
        }

        Frame {
            Layout.fillWidth: true
            Layout.preferredHeight: 250
            background: Rectangle { color: "#11161c" }

            ColumnLayout {
                anchors.fill: parent
                spacing: 2

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    Button {
                        text: EditorController.playing ? "Ⅱ" : "▶"
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.togglePlayback()
                    }
                    Button {
                        text: "↶"
                        enabled: EditorController.canUndo
                        onClicked: EditorController.undo()
                    }
                    Button {
                        text: "↷"
                        enabled: EditorController.canRedo
                        onClicked: EditorController.redo()
                    }
                    Button {
                        text: "분할"
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.splitAtPlayhead()
                    }
                    Button {
                        text: "삭제"
                        enabled: EditorController.selectedClipId.length > 0
                        onClicked: EditorController.deleteSelectedClip()
                    }
                    Label {
                        Layout.fillWidth: true
                        text: EditorController.status
                        color: "#8994a3"
                    }
                    Label {
                        text: Math.round(timeline.zoomLevel * 100) + "%"
                        color: "#8994a3"
                    }
                }

                TimelineView {
                    id: timeline
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    durationNs: EditorController.durationNs
                    playheadNs: EditorController.playheadNs
                    clips: EditorController.clips
                    selectedClipId: EditorController.selectedClipId
                    onSeekRequested: position => EditorController.seek(position)
                    onClipSelected: clipId => EditorController.selectClip(clipId)
                    onTrimCommitted: (clipId, sourceIn, duration) =>
                        EditorController.trimClip(clipId, sourceIn, duration)
                    onMoveCommitted: (clipId, insertionIndex) =>
                        EditorController.moveClip(clipId, insertionIndex)
                }
            }
        }
    }
}
