pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import FFGuiNext

ApplicationWindow {
    id: root
    visible: true
    x: Screen.width / 2 - width / 2
    y: Screen.height / 2 - height / 2
    opacity: OffscreenPresentationSmoke ? 0.01 : 1.0
    flags: OffscreenPresentationSmoke
           ? Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
           : Qt.Window
    width: 1440
    height: 900
    minimumWidth: 1100
    minimumHeight: 700
    title: "ffmpegGUI Next"
    color: "#111419"
    property bool showOutputNode: true
    property bool showAudioNode: true
    property bool showEffectsNode: false
    property bool showGraphicsNode: true
    property bool showGlobalTrimNode: false
    property bool showOutputSettingsNode: false

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

    component InspectorNode: Rectangle {
        id: node
        property string title
        property string summary
        property bool expanded: false
        signal removeRequested()
        default property alias nodeContent: body.data
        Layout.fillWidth: true
        implicitHeight: 42 + (expanded ? body.implicitHeight + 18 : 0)
        radius: 8
        color: "#171d24"
        border.color: expanded ? "#46566a" : "#303a46"

        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            Rectangle {
                id: header
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                color: headerMouse.containsMouse ? "#222b35" : "transparent"
                radius: 8
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    Label { text: node.expanded ? "▾" : "▸"; color: "#8fa2b8" }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Label { text: node.title; font.bold: true; color: "#e4ebf3" }
                        Label {
                            text: node.summary
                            visible: !node.expanded && text.length > 0
                            color: "#768395"
                            font.pixelSize: 10
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                    AppButton {
                        text: "×"
                        compact: true
                        implicitWidth: 28
                        onClicked: node.removeRequested()
                        ToolTip.visible: hovered
                        ToolTip.text: "패널에서 노드 제거"
                    }
                }
                HoverHandler { id: headerMouse }
                TapHandler { onTapped: node.expanded = !node.expanded }
            }
            ColumnLayout {
                id: body
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 10
                visible: node.expanded
                spacing: 8
            }
        }
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
        defaultSuffix: EditorController.exportExtension()
        nameFilters: EditorController.exportContainer === 1
                     ? ["Matroska 영상 (*.mkv)"]
                     : EditorController.exportContainer === 2
                       ? ["QuickTime 영상 (*.mov)"] : ["MP4 영상 (*.mp4)"]
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

    DropArea {
        id: externalFileDrop
        anchors.fill: parent
        z: 100
        keys: ["text/uri-list"]
        onDropped: drop => {
            if (drop.hasUrls) {
                EditorController.loadUrls(drop.urls)
                drop.acceptProposedAction()
            }
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 10
            visible: externalFileDrop.containsDrag
            color: "#705b8cff"
            border.width: 2
            border.color: "#8eb4ff"
            radius: 10
            Label {
                anchors.centerIn: parent
                text: "놓아서 미디어 추가"
                font.pixelSize: 22
                font.bold: true
            }
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
                AppButton {
                    text: "로그"
                    compact: true
                    onClicked: EditorController.openLogFolder()
                    ToolTip.visible: hovered
                    ToolTip.text: "진단 로그 폴더 열기"
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: EditorController.exporting ? "내보내는 중…" : "내보내기"
                    enabled: EditorController.durationNs > 0 && !EditorController.exporting
                    onClicked: exportDialog.open()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: EditorController.exporting ? 46 : 0
            visible: EditorController.exporting
            color: "#182333"
            border.color: "#304a70"
            clip: true

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 12
                ColumnLayout {
                    Layout.preferredWidth: 260
                    spacing: 1
                    Label { text: EditorController.exportStage; font.bold: true }
                    Label {
                        Layout.fillWidth: true
                        text: EditorController.exportOutputName
                        color: "#9eabbc"
                        elide: Text.ElideMiddle
                    }
                }
                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    value: EditorController.exportProgress
                }
                Label {
                    text: Math.round(EditorController.exportProgress * 100) + "%"
                    font.pixelSize: 14
                    font.bold: true
                    Layout.preferredWidth: 48
                    horizontalAlignment: Text.AlignRight
                }
                AppButton {
                    text: "취소"
                    danger: true
                    compact: true
                    onClicked: EditorController.cancelExport()
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
                                text: EditorController.timeText(EditorController.playheadNs)
                                      + "  ·  F" + EditorController.frameNumberAt(EditorController.playheadNs)
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
                            active: EditorController.inProcessPreview
                            sourceComponent: VideoPreviewItem {
                                id: inProcessVideoPreview
                                Component.onCompleted:
                                    EditorController.attachVideoItem(inProcessVideoPreview)
                            }
                        }
                        WindowContainer {
                            id: nativePreviewContainer
                            anchors.fill: parent
                            visible: !EditorController.inProcessPreview
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

                        Item {
                            id: graphicOverlayLayer
                            anchors.fill: parent
                            z: 20

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                height: parent.height * EditorController.stampBarPercent / 100
                                color: "#e6000000"
                                visible: EditorController.stampEnabled
                                Label {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 14
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: EditorController.stampInformation
                                    color: "white"
                                    font.pixelSize: Math.max(11, parent.height * 0.36)
                                }
                                Label {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 14
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: EditorController.stampWorker.length > 0
                                          ? "작업자  " + EditorController.stampWorker : ""
                                    color: "white"
                                    font.pixelSize: Math.max(11, parent.height * 0.36)
                                }
                            }
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: parent.height * EditorController.stampBarPercent / 100
                                color: "#e6000000"
                                visible: EditorController.stampEnabled
                                Label {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 14
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: EditorController.timeText(EditorController.playheadNs)
                                          + "  ·  F" + EditorController.frameNumberAt(EditorController.playheadNs)
                                    color: "white"
                                    font.family: "Consolas"
                                    font.pixelSize: Math.max(11, parent.height * 0.34)
                                }
                            }

                            Repeater {
                                model: EditorController.captions
                                delegate: Item {
                                    id: overlayTextItem
                                    required property var modelData
                                    visible: EditorController.playheadNs >= modelData.timelineInNs &&
                                             EditorController.playheadNs < modelData.timelineInNs + modelData.durationNs
                                    width: overlayText.implicitWidth + 20
                                    height: overlayText.implicitHeight + 12
                                    x: modelData.positionX * graphicOverlayLayer.width - width / 2
                                    y: modelData.positionY * graphicOverlayLayer.height - height / 2

                                    Rectangle {
                                        anchors.fill: parent
                                        color: EditorController.selectedCaptionId === modelData.id
                                               ? "#5a000000" : "transparent"
                                        border.width: EditorController.selectedCaptionId === modelData.id ? 2 : 0
                                        border.color: "#f0c66a"
                                        radius: 3
                                    }
                                    Label {
                                        id: overlayText
                                        anchors.centerIn: parent
                                        text: modelData.text
                                        color: "white"
                                        font.bold: true
                                        font.pixelSize: Math.max(
                                            12, modelData.fontSize * graphicOverlayLayer.width / 1280)
                                        style: Text.Outline
                                        styleColor: "#d0000000"
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                        drag.target: overlayTextItem
                                        drag.minimumX: -overlayTextItem.width / 2
                                        drag.maximumX: graphicOverlayLayer.width - overlayTextItem.width / 2
                                        drag.minimumY: -overlayTextItem.height / 2
                                        drag.maximumY: graphicOverlayLayer.height - overlayTextItem.height / 2
                                        onPressed: EditorController.selectCaption(modelData.id)
                                        onReleased: EditorController.updateCaptionPosition(
                                            modelData.id,
                                            (overlayTextItem.x + overlayTextItem.width / 2) /
                                                graphicOverlayLayer.width,
                                            (overlayTextItem.y + overlayTextItem.height / 2) /
                                                graphicOverlayLayer.height)
                                    }
                                }
                            }
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
                    Label { text: "작업 노드"; font.pixelSize: 18; font.bold: true }
                    RowLayout {
                        Layout.fillWidth: true
                        ComboBox {
                            id: nodePicker
                            Layout.fillWidth: true
                            model: ["출력", "오디오", "이펙트", "문구·스탬프", "전체 트림", "출력 설정"]
                        }
                        AppButton {
                            text: "+ 추가"
                            compact: true
                            onClicked: {
                                if (nodePicker.currentIndex === 0) root.showOutputNode = true
                                else if (nodePicker.currentIndex === 1) root.showAudioNode = true
                                else if (nodePicker.currentIndex === 2) root.showEffectsNode = true
                                else if (nodePicker.currentIndex === 3) root.showGraphicsNode = true
                                else if (nodePicker.currentIndex === 4) root.showGlobalTrimNode = true
                                else root.showOutputSettingsNode = true
                            }
                        }
                    }

                    InspectorNode {
                        visible: root.showOutputNode
                        title: "출력"
                        summary: EditorController.exporting
                                 ? EditorController.exportStage : "내보내기 실행과 진행 상황"
                        expanded: true
                        onRemoveRequested: root.showOutputNode = false
                        Label {
                            Layout.fillWidth: true
                            visible: EditorController.exporting
                            text: EditorController.exportStage + "  "
                                  + Math.round(EditorController.exportProgress * 100) + "%"
                            color: "#b7c4d4"
                        }
                        ProgressBar {
                            Layout.fillWidth: true
                            visible: EditorController.exporting
                            from: 0; to: 1; value: EditorController.exportProgress
                        }
                        AppButton {
                            Layout.fillWidth: true
                            text: EditorController.exporting ? "취소" : "영상 내보내기"
                            enabled: EditorController.exporting || EditorController.durationNs > 0
                            onClicked: EditorController.exporting
                                ? EditorController.cancelExport() : exportDialog.open()
                        }
                    }

                    InspectorNode {
                        visible: root.showAudioNode
                        title: "오디오"
                        summary: EditorController.selectedClipIds.length > 0
                                 ? EditorController.selectedClipIds.length + "개 클립" : "클립을 선택하세요"
                        expanded: EditorController.selectedClipIds.length > 0
                        onRemoveRequested: root.showAudioNode = false
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            enabled: EditorController.selectedClipIds.length > 0
                            Label { text: "볼륨"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true; from: 0; to: 400; stepSize: 5; editable: true
                                value: EditorController.selectedClipVolumePercent
                                textFromValue: function(value) { return value + "%" }
                                valueFromText: function(text) { return parseInt(text) || 0 }
                                onValueModified: EditorController.setSelectedClipVolumePercent(value)
                            }
                            Label { text: "재생 속도"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true; from: 25; to: 400; stepSize: 5; editable: true
                                value: EditorController.selectedClipSpeedPercent
                                textFromValue: function(value) { return value + "%" }
                                valueFromText: function(text) { return parseInt(text) || 100 }
                                onValueModified: EditorController.setSelectedClipSpeedPercent(value)
                            }
                            Label { text: "페이드 인"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true; from: 0; to: 60000; stepSize: 100; editable: true
                                value: EditorController.selectedClipFadeInMs
                                textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                                valueFromText: function(text) { return Math.round((parseFloat(text) || 0) * 1000) }
                                onValueModified: EditorController.setSelectedClipFadeInMs(value)
                            }
                            Label { text: "페이드 아웃"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true; from: 0; to: 60000; stepSize: 100; editable: true
                                value: EditorController.selectedClipFadeOutMs
                                textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                                valueFromText: function(text) { return Math.round((parseFloat(text) || 0) * 1000) }
                                onValueModified: EditorController.setSelectedClipFadeOutMs(value)
                            }
                        }
                        AppButton {
                            Layout.fillWidth: true
                            enabled: EditorController.selectedClipIds.length > 0
                            text: EditorController.selectedClipMuted ? "음소거 해제 (M)" : "음소거 (M)"
                            highlighted: EditorController.selectedClipMuted
                            onClicked: EditorController.setSelectedClipMuted(!EditorController.selectedClipMuted)
                        }
                    }

                    InspectorNode {
                        visible: root.showEffectsNode
                        title: "이펙트"
                        summary: "디졸브 · Color Grading"
                        expanded: true
                        onRemoveRequested: root.showEffectsNode = false
                        Label { text: "Color Grading"; font.bold: true }
                        GridLayout {
                            Layout.fillWidth: true; columns: 2
                            enabled: EditorController.selectedClipIds.length > 0
                            Label { text: "밝기"; color: "#b4bdc8" }
                            SpinBox { Layout.fillWidth: true; from: -100; to: 100; value: EditorController.selectedClipBrightness; onValueModified: EditorController.setSelectedClipBrightness(value) }
                            Label { text: "대비"; color: "#b4bdc8" }
                            SpinBox { Layout.fillWidth: true; from: 0; to: 200; value: EditorController.selectedClipContrast; onValueModified: EditorController.setSelectedClipContrast(value) }
                            Label { text: "채도"; color: "#b4bdc8" }
                            SpinBox { Layout.fillWidth: true; from: 0; to: 200; value: EditorController.selectedClipSaturation; onValueModified: EditorController.setSelectedClipSaturation(value) }
                        }
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#303844" }
                        Label { text: "클립 사이 전환"; font.bold: true }
                        GridLayout {
                            Layout.fillWidth: true; columns: 2
                            Label { text: "디졸브"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true
                                from: 0; to: 5000; stepSize: 100; editable: true
                                enabled: EditorController.selectedClipIds.length === 1 &&
                                         EditorController.clips.length > 0 &&
                                         EditorController.selectedClipId !== EditorController.clips[0].id
                                value: EditorController.selectedClipDissolveMs
                                textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                                valueFromText: function(text) { return Math.round((parseFloat(text) || 0) * 1000) }
                                onValueModified: EditorController.setSelectedClipDissolveMs(value)
                            }
                        }
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            text: "선택 클립과 바로 앞 클립을 겹쳐 영상·오디오를 함께 전환합니다."
                            color: "#7f8c9c"; font.pixelSize: 11
                        }
                    }

                    InspectorNode {
                        visible: root.showGraphicsNode
                        title: "문구·스탬프"
                        summary: "화면 배치 · 작업 정보"
                        expanded: true
                        onRemoveRequested: root.showGraphicsNode = false

                        Label { text: "자유 문구"; font.bold: true }
                        TextField {
                            id: newOverlayText
                            Layout.fillWidth: true
                            placeholderText: "화면에 넣을 문구"
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            SpinBox {
                                id: newOverlayDuration
                                Layout.fillWidth: true
                                from: 500; to: 60000; stepSize: 500; value: 3000
                                textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                                valueFromText: function(text) { return Math.round((parseFloat(text) || 3) * 1000) }
                            }
                            AppButton {
                                text: "+ 문구"
                                compact: true
                                enabled: EditorController.durationNs > 0 && newOverlayText.text.trim().length > 0
                                onClicked: {
                                    EditorController.addTextOverlay(newOverlayText.text, newOverlayDuration.value)
                                    newOverlayText.clear()
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: EditorController.selectedCaptionId.length > 0
                            Label { text: "선택 문구"; color: "#b4bdc8" }
                            TextField {
                                Layout.fillWidth: true
                                text: EditorController.selectedCaptionText
                                onEditingFinished: EditorController.updateSelectedCaption(
                                    text, selectedOverlayDuration.value)
                            }
                            GridLayout {
                                Layout.fillWidth: true; columns: 2
                                Label { text: "표시 시간"; color: "#b4bdc8" }
                                SpinBox {
                                    id: selectedOverlayDuration
                                    Layout.fillWidth: true
                                    from: 100; to: 60000; stepSize: 100
                                    value: EditorController.selectedCaptionDurationMs
                                    textFromValue: function(value) { return (value / 1000).toFixed(1) + "초" }
                                    valueFromText: function(text) { return Math.round((parseFloat(text) || 1) * 1000) }
                                    onValueModified: EditorController.updateSelectedCaption(
                                        EditorController.selectedCaptionText, value)
                                }
                                Label { text: "글자 크기"; color: "#b4bdc8" }
                                SpinBox {
                                    Layout.fillWidth: true
                                    from: 12; to: 160; stepSize: 2
                                    value: EditorController.selectedCaptionFontSize
                                    onValueModified: EditorController.setSelectedCaptionFontSize(value)
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "프로그램 모니터의 문구를 직접 끌어 위치를 정합니다."
                                wrapMode: Text.WordWrap
                                color: "#7f8c9c"; font.pixelSize: 11
                            }
                            AppButton {
                                Layout.fillWidth: true
                                text: "선택 문구 삭제"
                                onClicked: EditorController.deleteSelectedCaption()
                            }
                        }

                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#303844" }
                        Switch {
                            text: "상·하단 스탬프 표시"
                            checked: EditorController.stampEnabled
                            onToggled: EditorController.setStampEnabled(checked)
                        }
                        GridLayout {
                            Layout.fillWidth: true; columns: 2
                            enabled: EditorController.stampEnabled
                            Label { text: "작업자"; color: "#b4bdc8" }
                            TextField {
                                Layout.fillWidth: true
                                text: EditorController.stampWorker
                                placeholderText: "이름"
                                onEditingFinished: EditorController.setStampWorker(text)
                            }
                            Label { text: "영상 정보"; color: "#b4bdc8" }
                            TextField {
                                Layout.fillWidth: true
                                text: EditorController.stampInformation
                                placeholderText: "프로젝트·버전·샷 정보"
                                onEditingFinished: EditorController.setStampInformation(text)
                            }
                            Label { text: "바 높이"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true
                                from: 4; to: 25; value: EditorController.stampBarPercent
                                textFromValue: function(value) { return value + "%" }
                                valueFromText: function(text) { return parseInt(text) || 9 }
                                onValueModified: EditorController.setStampBarPercent(value)
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "검은 바는 영상 위에 겹쳐지므로 해상도와 화면 비율은 바뀌지 않습니다."
                            wrapMode: Text.WordWrap
                            color: "#7f8c9c"; font.pixelSize: 11
                        }
                    }

                    InspectorNode {
                        visible: root.showGlobalTrimNode
                        title: "전체 트림"
                        summary: "모든 클립의 앞·뒤를 프레임 단위로 정리"
                        expanded: true
                        onRemoveRequested: root.showGlobalTrimNode = false
                        GridLayout {
                            Layout.fillWidth: true; columns: 2
                            Label { text: "앞 프레임"; color: "#b4bdc8" }
                            SpinBox { id: globalFrontFrames; Layout.fillWidth: true; from: 0; to: 999; editable: true }
                            Label { text: "뒤 프레임"; color: "#b4bdc8" }
                            SpinBox { id: globalBackFrames; Layout.fillWidth: true; from: 0; to: 999; editable: true }
                        }
                        AppButton {
                            Layout.fillWidth: true
                            text: "모든 클립에 적용"
                            enabled: globalFrontFrames.value > 0 || globalBackFrames.value > 0
                            onClicked: EditorController.trimAllClipEdges(
                                globalFrontFrames.value, globalBackFrames.value)
                        }
                    }

                    InspectorNode {
                        visible: root.showOutputSettingsNode
                        title: "출력 설정"
                        summary: ["MP4", "MKV", "MOV"][EditorController.exportContainer]
                        expanded: true
                        onRemoveRequested: root.showOutputSettingsNode = false
                        Label { text: "화질"; color: "#b4bdc8" }
                        ComboBox { Layout.fillWidth: true; model: ["고화질", "균형", "용량 절약"]; currentIndex: EditorController.exportQuality; onActivated: EditorController.exportQuality = currentIndex }
                        Label { text: "코덱"; color: "#b4bdc8" }
                        ComboBox { Layout.fillWidth: true; model: ["H.264 · 높은 호환성", "H.265 / HEVC · 작은 용량", "원본 스트림 복사 · 가능할 때"]; currentIndex: EditorController.exportCodec; onActivated: EditorController.exportCodec = currentIndex }
                        Label { text: "파일 형식"; color: "#b4bdc8" }
                        ComboBox { Layout.fillWidth: true; model: ["MP4", "MKV", "MOV"]; currentIndex: EditorController.exportContainer; onActivated: EditorController.exportContainer = currentIndex }
                        Label { text: "해상도"; color: "#b4bdc8" }
                        ComboBox { Layout.fillWidth: true; model: ["원본", "4K · 3840×2160", "FHD · 1920×1080", "HD · 1280×720"]; currentIndex: EditorController.exportResolution; onActivated: EditorController.exportResolution = currentIndex }
                        Label { text: "프레임률"; color: "#b4bdc8" }
                        ComboBox { Layout.fillWidth: true; model: ["원본", "60 fps", "30 fps", "24 fps"]; currentIndex: EditorController.exportFrameRate; onActivated: EditorController.exportFrameRate = currentIndex }
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
                        text: "눈금 드래그 탐색  ·  클립 드래그 이동  ·  Ctrl+휠 확대"
                        color: "#687484"
                        font.pixelSize: 10
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

                    Item {
                        id: timelineThumbnails
                        anchors.fill: parent
                        clip: true
                        readonly property real contentWidth: Math.max(1, width - 24)
                        readonly property var visibleThumbnailClips: EditorController.clips.filter(
                            function(clip) {
                                const clipWidth = timelineThumbnails.contentWidth * clip.durationNs /
                                                  Math.max(1, timeline.viewportDurationNs)
                                return clip.thumbnailAtlas.length > 0 && clipWidth >= 28 &&
                                       clip.timelineInNs + clip.durationNs > timeline.viewportStartNs &&
                                       clip.timelineInNs < timeline.viewportStartNs +
                                                           timeline.viewportDurationNs
                            })
                        Repeater {
                            model: timelineThumbnails.visibleThumbnailClips
                            delegate: Image {
                                required property var modelData
                                x: 12 + timelineThumbnails.contentWidth *
                                   (modelData.timelineInNs - timeline.viewportStartNs) /
                                   Math.max(1, timeline.viewportDurationNs)
                                y: 30
                                width: timelineThumbnails.contentWidth * modelData.durationNs /
                                       Math.max(1, timeline.viewportDurationNs)
                                height: Math.max(1, timelineThumbnails.height - 44)
                                visible: modelData.thumbnailAtlas.length > 0 &&
                                         x + width > 12 && x < timelineThumbnails.width - 12
                                source: modelData.thumbnailAtlas.length > 0
                                    ? "file:///" + modelData.thumbnailAtlas.replace(/\\/g, "/")
                                    : ""
                                sourceClipRect: modelData.assetDurationNs > 0
                                    ? Qt.rect(
                                        1920 * modelData.sourceInNs / modelData.assetDurationNs,
                                        0,
                                        Math.max(1, 1920 * modelData.sourceDurationNs /
                                                     modelData.assetDurationNs),
                                        90)
                                    : Qt.rect(0, 0, 1920, 90)
                                fillMode: Image.Stretch
                                asynchronous: true
                                cache: true
                                opacity: 1.0
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
                        onSeekRequested: (position, finalPosition) =>
                            EditorController.scrub(position, finalPosition)
                        onClipSelected: (clipId, selectionMode) =>
                            EditorController.selectClip(clipId, selectionMode)
                        onTrimCommitted: (clipId, sourceIn, duration) =>
                            EditorController.trimClip(clipId, sourceIn, duration)
                        onMoveCommitted: (clipIds, insertionIndex) =>
                            EditorController.moveClips(clipIds, insertionIndex)
                    }

                    Item {
                        id: timelineRuler
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 29
                        z: 3
                        Repeater {
                            model: 9
                            delegate: Item {
                                required property int index
                                x: 12 + (timelineRuler.width - 24) * index / 8
                                width: 1
                                height: timelineRuler.height
                                readonly property double tickTime: timeline.viewportStartNs +
                                    timeline.viewportDurationNs * index / 8
                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    width: 1
                                    height: index % 2 === 0 ? 8 : 5
                                    color: "#647183"
                                }
                                Label {
                                    visible: index < 8
                                    x: 4
                                    y: 2
                                    text: EditorController.timeText(parent.tickTime)
                                          + "  F" + EditorController.frameNumberAt(parent.tickTime)
                                    color: "#7f8b9a"
                                    font.family: "Consolas"
                                    font.pixelSize: 9
                                }
                            }
                        }
                    }

                    Rectangle {
                        visible: timeline.interactionActive
                        z: 6
                        x: Math.max(8, Math.min(timelineLayer.width - width - 8,
                                               timeline.interactionX - width / 2))
                        y: 34
                        width: feedbackText.implicitWidth + 20
                        height: 42
                        radius: 6
                        color: "#0a0d12"
                        border.color: "#78a5ff"
                        Label {
                            id: feedbackText
                            anchors.centerIn: parent
                            text: timeline.interactionKind + "  "
                                  + EditorController.timeText(timeline.interactionTimeNs)
                                  + "  ·  F" + EditorController.frameNumberAt(timeline.interactionTimeNs)
                                  + (timeline.interactionDeltaNs === 0 ? "" :
                                     "\n" + (timeline.interactionDeltaNs > 0 ? "+" : "−")
                                     + EditorController.frameCountBetween(
                                           timeline.interactionTimeNs - timeline.interactionDeltaNs,
                                           timeline.interactionTimeNs)
                                     + "프레임  ·  "
                                     + (Math.abs(timeline.interactionDeltaNs) / 1000000000).toFixed(3)
                                     + "초")
                            color: "#eaf2ff"
                            font.family: "Consolas"
                            font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                        }
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
