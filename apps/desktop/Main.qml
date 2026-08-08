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

    component AppButton: Button {
        id: control
        property bool danger: false
        property bool compact: false
        hoverEnabled: true
        implicitHeight: compact ? 30 : 34
        leftPadding: compact ? 10 : 14
        rightPadding: compact ? 10 : 14
        contentItem: Label {
            text: control.text
            color: !control.enabled ? "#657080"
                  : control.danger ? (control.hovered ? "#ffffff" : "#ffb7b7")
                  : "#e8edf2"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 13
            font.bold: control.down || control.highlighted
        }
        background: Rectangle {
            radius: 6
            color: !control.enabled ? "#171c22"
                 : control.down ? (control.danger ? "#9e3038" : "#365f9f")
                 : control.hovered ? (control.danger ? "#6f2a31" : "#303b49")
                 : control.highlighted ? "#294e82" : "#202731"
            border.width: control.activeFocus ? 2 : 1
            border.color: control.activeFocus ? "#75a7ff"
                        : control.hovered ? (control.danger ? "#c94a55" : "#56677d")
                        : "#343e4b"
            Behavior on color { ColorAnimation { duration: 90 } }
            Behavior on border.color { ColorAnimation { duration: 90 } }
        }
    }

    component ToolDivider: Rectangle {
        implicitWidth: 1
        implicitHeight: 22
        color: "#35404d"
    }

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
    Shortcut { sequence: "M"; enabled: EditorController.selectedClipIds.length > 0; onActivated: EditorController.setSelectedClipMuted(!EditorController.selectedClipMuted) }
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
    FileDialog {
        id: importSrtDialog
        title: "SRT 자막 가져오기"
        fileMode: FileDialog.OpenFile
        nameFilters: ["SRT 자막 (*.srt)"]
        onAccepted: EditorController.importSrtUrl(selectedFile)
    }
    FileDialog {
        id: exportSrtDialog
        title: "SRT 자막 내보내기"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "srt"
        nameFilters: ["SRT 자막 (*.srt)"]
        onAccepted: EditorController.exportSrtUrl(selectedFile)
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
                AppButton {
                    text: EditorController.importing ? "분석 중…" : "영상 추가"
                    enabled: !EditorController.importing
                    onClicked: mediaDialog.open()
                }
                AppButton { text: "열기"; onClicked: openProjectDialog.open() }
                AppButton {
                    text: "저장"
                    enabled: EditorController.durationNs > 0
                    onClicked: saveProjectDialog.open()
                }
                Item { Layout.fillWidth: true }
                AppButton {
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
                        AppButton {
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
                                AppButton {
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
                SplitView.minimumWidth: 420
                padding: 0
                background: Rectangle { color: "#080a0d" }

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36
                        color: "#151a20"
                        border.color: "#272f39"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 8
                            Rectangle {
                                implicitWidth: 8
                                implicitHeight: 8
                                radius: 4
                                color: EditorController.previewFailed ? "#ef5964"
                                     : EditorController.previewBusy ? "#f5b942"
                                     : EditorController.playing ? "#52d273" : "#647183"
                                SequentialAnimation on opacity {
                                    running: EditorController.previewBusy
                                    loops: Animation.Infinite
                                    NumberAnimation { to: 0.35; duration: 450 }
                                    NumberAnimation { to: 1.0; duration: 450 }
                                }
                            }
                            Label {
                                text: EditorController.previewFailed ? "미리보기 오류"
                                    : EditorController.previewBusy ? "미리보기 준비 중"
                                    : EditorController.playing ? "재생 중" : "프로그램 모니터"
                                color: "#c7d0db"
                                font.pixelSize: 12
                                font.bold: EditorController.previewBusy || EditorController.playing
                            }
                            Item { Layout.fillWidth: true }
                            Label {
                                text: root.durationText(EditorController.playheadNs)
                                      + " / " + root.durationText(EditorController.durationNs)
                                color: "#8e9aaa"
                                font.family: "Consolas"
                                font.pixelSize: 12
                            }
                        }
                    }

                    Item {
                        id: previewSurface
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        Loader {
                            anchors.fill: parent
                            active: EditorController.gpuSceneGraphPreview
                            sourceComponent: D3D11VideoItem {
                                id: experimentalVideoPreview
                                Component.onCompleted:
                                    EditorController.attachVideoItem(experimentalVideoPreview)
                            }
                        }
                        WindowContainer {
                            id: nativePreviewContainer
                            anchors.fill: parent
                            visible: !EditorController.gpuSceneGraphPreview
                            window: EditorController.videoWindow
                            Component.onCompleted: Qt.callLater(
                                EditorController.refreshVideoWindowHandle)
                        }
                        Label {
                            anchors.centerIn: parent
                            visible: EditorController.durationNs === 0
                            text: EditorController.importing ? "미디어 분석 중…" : "미디어를 추가하세요"
                            color: "#718094"
                            font.pixelSize: 15
                        }
                    }
                }
            }

            Frame {
                SplitView.preferredWidth: 320
                SplitView.minimumWidth: 280
                SplitView.maximumWidth: 380
                ScrollView {
                    id: inspectorScroll
                    anchors.fill: parent
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                    ColumnLayout {
                        x: 20
                        y: 20
                        width: Math.max(0, inspectorScroll.availableWidth - 40)
                        spacing: 12
                    Label { text: "출력"; font.pixelSize: 18; font.bold: true }
                    Label { text: "H.264 · MP4"; color: "#8994a3" }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: "NVENC를 먼저 사용하고, 지원되지 않으면 CPU로 자동 전환합니다."
                        color: "#8994a3"
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: "#303844"
                    }
                    Label {
                        text: EditorController.selectedClipIds.length > 1
                              ? "오디오 · " + EditorController.selectedClipIds.length + "개 클립"
                              : "클립 오디오"
                        font.bold: true
                        visible: EditorController.selectedClipIds.length > 0
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        visible: EditorController.selectedClipIds.length > 0
                        columnSpacing: 8
                        rowSpacing: 8

                        Label { text: "볼륨"; color: "#b4bdc8" }
                        SpinBox {
                            Layout.fillWidth: true
                            from: 0
                            to: 400
                            stepSize: 5
                            editable: true
                            value: EditorController.selectedClipVolumePercent
                            textFromValue: function(value) { return value + "%" }
                            valueFromText: function(text) { return parseInt(text) || 0 }
                            onValueModified: EditorController.setSelectedClipVolumePercent(value)
                        }
                        Label { text: "재생 속도"; color: "#b4bdc8" }
                        SpinBox {
                            Layout.fillWidth: true
                            from: 25
                            to: 400
                            stepSize: 5
                            editable: true
                            value: EditorController.selectedClipSpeedPercent
                            textFromValue: function(value) { return value + "%" }
                            valueFromText: function(text) { return parseInt(text) || 100 }
                            onValueModified: EditorController.setSelectedClipSpeedPercent(value)
                        }
                        Label { text: "페이드 인"; color: "#b4bdc8" }
                        SpinBox {
                            Layout.fillWidth: true
                            from: 0
                            to: 60000
                            stepSize: 100
                            editable: true
                            value: EditorController.selectedClipFadeInMs
                            textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                            valueFromText: function(text) { return Math.round((parseFloat(text) || 0) * 1000) }
                            onValueModified: EditorController.setSelectedClipFadeInMs(value)
                        }
                        Label { text: "페이드 아웃"; color: "#b4bdc8" }
                        SpinBox {
                            Layout.fillWidth: true
                            from: 0
                            to: 60000
                            stepSize: 100
                            editable: true
                            value: EditorController.selectedClipFadeOutMs
                            textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                            valueFromText: function(text) { return Math.round((parseFloat(text) || 0) * 1000) }
                            onValueModified: EditorController.setSelectedClipFadeOutMs(value)
                        }
                    }
                    AppButton {
                        Layout.fillWidth: true
                        visible: EditorController.selectedClipIds.length > 0
                        text: EditorController.selectedClipMuted ? "음소거 해제 (M)" : "음소거 (M)"
                        highlighted: EditorController.selectedClipMuted
                        onClicked: EditorController.setSelectedClipMuted(!EditorController.selectedClipMuted)
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: "#303844"
                    }
                    ProgressBar {
                        Layout.fillWidth: true
                        visible: EditorController.exporting
                        from: 0
                        to: 1
                        value: EditorController.exportProgress
                    }
                    AppButton {
                        Layout.fillWidth: true
                        text: EditorController.exporting ? "취소" : "영상 내보내기"
                        enabled: EditorController.exporting || EditorController.durationNs > 0
                        onClicked: EditorController.exporting
                            ? EditorController.cancelExport()
                            : exportDialog.open()
                    }
                        Item { Layout.preferredHeight: 20 }
                    }
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
                    Layout.preferredHeight: 40
                    Layout.leftMargin: 6
                    Layout.rightMargin: 8
                    spacing: 5
                    AppButton {
                        text: EditorController.playing ? "Ⅱ  일시정지" : "▶  재생"
                        enabled: EditorController.durationNs > 0
                        highlighted: EditorController.playing
                        onClicked: EditorController.togglePlayback()
                        ToolTip.visible: hovered
                        ToolTip.text: "전체 타임라인 재생/일시정지  Space"
                    }
                    AppButton {
                        text: "‹"
                        compact: true
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.stepFrame(-1)
                        ToolTip.visible: hovered
                        ToolTip.text: "이전 원본 프레임  ←"
                    }
                    AppButton {
                        text: "›"
                        compact: true
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.stepFrame(1)
                        ToolTip.visible: hovered
                        ToolTip.text: "다음 원본 프레임  →"
                    }
                    ToolDivider { }
                    AppButton {
                        text: "↶"
                        compact: true
                        enabled: EditorController.canUndo
                        onClicked: EditorController.undo()
                        ToolTip.visible: hovered
                        ToolTip.text: "실행 취소  Ctrl+Z"
                    }
                    AppButton {
                        text: "↷"
                        compact: true
                        enabled: EditorController.canRedo
                        onClicked: EditorController.redo()
                        ToolTip.visible: hovered
                        ToolTip.text: "다시 실행  Ctrl+Y"
                    }
                    ToolDivider { }
                    AppButton {
                        text: "✂  분할"
                        enabled: EditorController.durationNs > 0
                        onClicked: EditorController.splitAtPlayhead()
                        ToolTip.visible: hovered
                        ToolTip.text: "재생 헤드에서 분할  Ctrl+K"
                    }
                    AppButton {
                        text: "복제"
                        enabled: EditorController.selectedClipIds.length > 0
                        onClicked: EditorController.duplicateSelectedClip()
                        ToolTip.visible: hovered
                        ToolTip.text: "선택 클립 복제  Ctrl+D"
                    }
                    AppButton {
                        text: "삭제"
                        danger: true
                        enabled: EditorController.selectedClipIds.length > 0
                        onClicked: EditorController.deleteSelectedClip()
                        ToolTip.visible: hovered
                        ToolTip.text: "선택 클립 리플 삭제  Delete"
                    }
                    ToolDivider { }
                    AppButton {
                        text: "[  인"
                        compact: true
                        enabled: EditorController.durationNs > 0
                        highlighted: EditorController.inPointNs >= 0
                        onClicked: EditorController.setInPoint()
                        ToolTip.visible: hovered
                        ToolTip.text: "구간 시작 표시  I"
                    }
                    AppButton {
                        text: "아웃  ]"
                        compact: true
                        enabled: EditorController.durationNs > 0
                        highlighted: EditorController.outPointNs >= 0
                        onClicked: EditorController.setOutPoint()
                        ToolTip.visible: hovered
                        ToolTip.text: "구간 끝 표시  O"
                    }
                    AppButton {
                        text: "구간 리플 삭제"
                        danger: true
                        enabled: EditorController.inPointNs >= 0
                                 && EditorController.outPointNs > EditorController.inPointNs
                        onClicked: EditorController.extractMarkedRange()
                        ToolTip.visible: hovered
                        ToolTip.text: "인/아웃 구간을 삭제하고 빈자리 닫기  Shift+Delete"
                    }
                    Label {
                        Layout.fillWidth: true
                        text: EditorController.status
                        elide: Text.ElideRight
                        color: EditorController.previewFailed ? "#ff7780"
                             : EditorController.previewBusy ? "#f0bd58" : "#8994a3"
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
