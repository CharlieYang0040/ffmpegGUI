pragma ComponentBehavior: Bound

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

    function durationText(nanoseconds) {
        const totalSeconds = Math.max(0, Math.floor(nanoseconds / 1000000000))
        const minutes = Math.floor(totalSeconds / 60)
        const seconds = totalSeconds % 60
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    palette.window: "#111419"
    palette.windowText: "#e8edf2"
    palette.base: "#171b21"
    palette.text: "#e8edf2"
    palette.button: "#222831"
    palette.buttonText: "#e8edf2"
    palette.highlight: "#5b8cff"

    Shortcut { sequences: [StandardKey.Undo]; enabled: EditorController.canUndo; onActivated: EditorController.undo() }
    Shortcut { sequences: [StandardKey.Redo]; enabled: EditorController.canRedo; onActivated: EditorController.redo() }
    Shortcut { sequence: "Space"; onActivated: EditorController.togglePlayback() }
    Shortcut { sequence: "Left"; autoRepeat: true; onActivated: EditorController.stepFrame(-1) }
    Shortcut { sequence: "Right"; autoRepeat: true; onActivated: EditorController.stepFrame(1) }
    Shortcut { sequence: "Up"; autoRepeat: true; onActivated: EditorController.jumpEditPoint(-1) }
    Shortcut { sequence: "Down"; autoRepeat: true; onActivated: EditorController.jumpEditPoint(1) }
    Shortcut { sequence: "Ctrl+K"; onActivated: EditorController.splitAtPlayhead() }
    Shortcut { sequence: "I"; onActivated: EditorController.setInPoint() }
    Shortcut { sequence: "O"; onActivated: EditorController.setOutPoint() }
    Shortcut { sequence: "Shift+Delete"; enabled: EditorController.inPointNs >= 0 && EditorController.outPointNs > EditorController.inPointNs; onActivated: EditorController.extractMarkedRange() }
    Shortcut { sequence: "Ctrl+Shift+X"; onActivated: EditorController.clearRange() }
    Shortcut { sequence: "Ctrl+D"; enabled: EditorController.selectedClipIds.length > 0; onActivated: EditorController.duplicateSelectedClip() }
    Shortcut { sequence: "Delete"; enabled: EditorController.selectedClipIds.length > 0; onActivated: EditorController.deleteSelectedClip() }

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
    FileDialog {
        id: exportDialog
        title: "영상 내보내기"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "mp4"
        nameFilters: ["MP4 영상 (*.mp4)"]
        onAccepted: {
            if (EditorController.outputExists(selectedFile)) {
                overwriteDialog.suggestedUrl = EditorController.uniqueOutputUrl(selectedFile)
                overwriteDialog.open()
            } else {
                EditorController.exportTimelineUrl(selectedFile)
            }
        }
    }
    Dialog {
        id: overwriteDialog
        property url suggestedUrl
        anchors.centerIn: parent
        modal: true
        title: "같은 이름의 파일이 있습니다"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: EditorController.exportTimelineUrl(suggestedUrl)

        Label {
            width: 420
            wrapMode: Text.WordWrap
            text: "기존 파일은 유지하고 새 번호를 붙여 저장합니다.\n\n"
                  + overwriteDialog.suggestedUrl.toString().split('/').pop()
        }
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
                Button {
                    text: EditorController.importing ? "분석 중…" : "영상 추가"
                    enabled: !EditorController.importing
                    onClicked: mediaDialog.open()
                }
                Button { text: "열기"; onClicked: openProjectDialog.open() }
                Button {
                    text: "저장"
                    enabled: EditorController.durationNs > 0
                    onClicked: saveProjectDialog.open()
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: EditorController.exporting ? "내보내는 중…" : "내보내기"
                    enabled: EditorController.durationNs > 0 && !EditorController.exporting
                    onClicked: exportDialog.open()
                }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            Frame {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 240
                background: Rectangle { color: "#151a20" }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "미디어"; font.pixelSize: 17; font.bold: true }
                        Label {
                            text: EditorController.mediaAssets.length
                            color: "#8994a3"
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "+"
                            implicitWidth: 34
                            onClicked: mediaDialog.open()
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: EditorController.mediaAssets.length === 0
                        text: EditorController.importing ? "미디어 분석 중…" : "영상을 추가하세요"
                        color: "#8994a3"
                        horizontalAlignment: Text.AlignHCenter
                    }

                    ListView {
                        id: mediaBin
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 8
                        model: EditorController.mediaAssets

                        delegate: Rectangle {
                            id: mediaCard
                            required property var modelData
                            property string assetId: modelData.id
                            width: ListView.view.width
                            height: 68
                            radius: 7
                            color: dragHandler.active ? "#2a3545" : "#1d232b"
                            border.color: dragHandler.active ? "#6d9cff" : "#2a323d"

                            Drag.active: dragHandler.active
                            Drag.keys: ["ffgui/media-asset"]
                            Drag.mimeData: {
                                "application/x-ffgui-asset-id": mediaCard.assetId
                            }
                            Drag.hotSpot.x: width / 2
                            Drag.hotSpot.y: height / 2

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 7
                                spacing: 9

                                Image {
                                    Layout.preferredWidth: 76
                                    Layout.fillHeight: true
                                    source: mediaCard.modelData.thumbnailAtlas.length > 0
                                        ? "file:///" + mediaCard.modelData.thumbnailAtlas.replace(/\\/g, "/")
                                        : ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: true
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Label {
                                        Layout.fillWidth: true
                                        text: mediaCard.modelData.name
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        text: root.durationText(mediaCard.modelData.durationNs)
                                              + "  ·  " + mediaCard.modelData.useCount + "회 사용"
                                        color: "#8994a3"
                                        font.pixelSize: 11
                                    }
                                }
                                Button {
                                    text: "+"
                                    implicitWidth: 30
                                    ToolTip.visible: hovered
                                    ToolTip.text: "재생 헤드 위치에 삽입"
                                    onClicked: EditorController.insertAssetAtTime(
                                        mediaCard.assetId, EditorController.playheadNs)
                                }
                            }

                            DragHandler {
                                id: dragHandler
                                target: null
                            }
                            TapHandler {
                                onDoubleTapped: EditorController.insertAssetAtTime(
                                    mediaCard.assetId, EditorController.playheadNs)
                            }
                        }
                    }
                }
            }

            Frame {
                SplitView.fillWidth: true
                background: Rectangle { color: "#080a0d" }

                D3D11VideoItem {
                    id: videoPreview
                    anchors.fill: parent
                    visible: EditorController.gpuSceneGraphPreview
                    Component.onCompleted: EditorController.attachVideoItem(videoPreview)

                    Label {
                        anchors.centerIn: parent
                        visible: !videoPreview.gpuReady
                        text: "GPU 미리보기 초기화 중"
                        color: "#8994a3"
                    }
                }
                WindowContainer {
                    anchors.fill: parent
                    visible: !EditorController.gpuSceneGraphPreview
                    window: EditorController.videoWindow
                }
            }

            Frame {
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 280
                SplitView.maximumWidth: 380
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 12
                    Label { text: "출력"; font.pixelSize: 18; font.bold: true }
                    Label { text: "H.264 · MP4"; color: "#8994a3" }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: "NVENC를 먼저 사용하고, 지원되지 않으면 CPU로 자동 전환합니다."
                        color: "#8994a3"
                    }
                    ProgressBar {
                        Layout.fillWidth: true
                        visible: EditorController.exporting
                        from: 0
                        to: 1
                        value: EditorController.exportProgress
                    }
                    Button {
                        Layout.fillWidth: true
                        text: EditorController.exporting ? "취소" : "영상 내보내기"
                        enabled: EditorController.exporting || EditorController.durationNs > 0
                        onClicked: EditorController.exporting
                            ? EditorController.cancelExport()
                            : exportDialog.open()
                    }
                    Item { Layout.fillHeight: true }
                }
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
                        text: "시작점"
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.setInPoint()
                    }
                    Button {
                        text: "끝점"
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.setOutPoint()
                    }
                    Button {
                        text: "구간 삭제"
                        enabled: EditorController.inPointNs >= 0
                                 && EditorController.outPointNs > EditorController.inPointNs
                        onClicked: EditorController.extractMarkedRange()
                    }
                    Button {
                        text: EditorController.selectedClipIds.length > 1
                              ? EditorController.selectedClipIds.length + "개 삭제"
                              : "삭제"
                        enabled: EditorController.selectedClipIds.length > 0
                        onClicked: EditorController.deleteSelectedClip()
                    }
                    Button {
                        text: EditorController.selectedClipIds.length > 1
                              ? EditorController.selectedClipIds.length + "개 복제"
                              : "복제"
                        enabled: EditorController.selectedClipIds.length > 0
                        onClicked: EditorController.duplicateSelectedClip()
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

                Item {
                    id: timelineLayer
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    Rectangle {
                        anchors.fill: parent
                        color: "#11161c"
                    }

                    Repeater {
                        model: EditorController.clips

                        delegate: Item {
                            id: clipThumbnail
                            required property var modelData
                            readonly property real contentWidth: Math.max(1, timelineLayer.width - 24)
                            readonly property real timelineStart: modelData.timelineInNs
                            readonly property real timelineEnd: timelineStart + modelData.durationNs
                            readonly property bool intersectsViewport:
                                timelineEnd > timeline.viewportStartNs
                                && timelineStart < timeline.viewportStartNs + timeline.viewportDurationNs

                            x: 12 + (timelineStart - timeline.viewportStartNs)
                               / Math.max(1, timeline.viewportDurationNs) * contentWidth
                            y: 30
                            width: modelData.durationNs
                                   / Math.max(1, timeline.viewportDurationNs) * contentWidth
                            height: Math.max(1, timelineLayer.height - 44)
                            visible: modelData.thumbnailAtlas.length > 0 && intersectsViewport
                            clip: true

                            Image {
                                id: atlas
                                anchors.fill: parent
                                source: clipThumbnail.modelData.thumbnailAtlas.length > 0
                                    ? "file:///" + clipThumbnail.modelData.thumbnailAtlas.replace(/\\/g, "/")
                                    : ""
                                fillMode: Image.Stretch
                                asynchronous: true
                                cache: true
                                smooth: true
                                opacity: 0.9
                                sourceClipRect: Qt.rect(
                                    atlas.sourceSize.width * clipThumbnail.modelData.sourceInNs
                                        / Math.max(1, clipThumbnail.modelData.assetDurationNs),
                                    0,
                                    atlas.sourceSize.width * clipThumbnail.modelData.durationNs
                                        / Math.max(1, clipThumbnail.modelData.assetDurationNs),
                                    atlas.sourceSize.height)
                            }
                        }
                    }

                    TimelineView {
                        id: timeline
                        anchors.fill: parent
                        durationNs: EditorController.durationNs
                        playheadNs: EditorController.playheadNs
                        inPointNs: EditorController.inPointNs
                        outPointNs: EditorController.outPointNs
                        clips: EditorController.clips
                        selectedClipId: EditorController.selectedClipId
                        selectedClipIds: EditorController.selectedClipIds
                        onSeekRequested: position => EditorController.seek(position)
                        onClipSelected: (clipId, selectionMode) =>
                            EditorController.selectClip(clipId, selectionMode)
                        onTrimCommitted: (clipId, sourceIn, duration) =>
                            EditorController.trimClip(clipId, sourceIn, duration)
                        onMoveCommitted: (clipIds, insertionIndex) =>
                            EditorController.moveClips(clipIds, insertionIndex)
                    }

                    DropArea {
                        id: mediaDropArea
                        anchors.fill: parent
                        z: 5
                        keys: ["ffgui/media-asset"]
                        property real indicatorX: 0
                        onPositionChanged: drag => indicatorX = drag.x
                        onDropped: drop => {
                            EditorController.insertAssetAtTime(
                                drop.getDataAsString("application/x-ffgui-asset-id"),
                                timeline.timelineTimeAt(drop.x))
                            drop.acceptProposedAction()
                        }

                        Rectangle {
                            visible: mediaDropArea.containsDrag
                            x: Math.max(12, Math.min(parent.width - 12, mediaDropArea.indicatorX)) - 1
                            y: 8
                            width: 2
                            height: parent.height - 18
                            color: "#78a5ff"
                        }
                    }
                }
            }
        }
    }
}
