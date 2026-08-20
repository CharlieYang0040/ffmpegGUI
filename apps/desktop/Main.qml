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
    property bool showGraphicsNode: false
    property bool showGlobalTrimNode: false
    property bool showColorManagementNode: false
    property bool showOutputSettingsNode: false
    property string expandedNode: ""
    property string expandedGradeNode: ""

    function durationText(nanoseconds) {
        const totalSeconds = Math.max(0, Math.floor(nanoseconds / 1000000000))
        const minutes = Math.floor(totalSeconds / 60)
        const seconds = totalSeconds % 60
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    function requestExport() {
        if (EditorController.missingFrameCount > 0)
            missingFrameWarning.open()
        else
            continueExport()
    }

    function continueExport() {
        if (EditorController.exportContainer === 3 && EditorController.gifSizeRisk === 2)
            gifSizeWarning.open()
        else
            EditorController.exportTimeline()
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
        property string nodeKey
        property string title
        property string summary
        readonly property bool expanded: root.expandedNode === nodeKey
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
                TapHandler {
                    onTapped: root.expandedNode = node.expanded ? "" : node.nodeKey
                }
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
        nameFilters: [
            "지원 미디어 (*.mp4 *.mkv *.mov *.avi *.webm *.gif *.png *.jpg *.jpeg *.tif *.tiff *.tga *.bmp *.webp *.dpx *.hdr *.exr)",
            "영상 (*.mp4 *.mkv *.mov *.avi *.webm)",
            "이미지·시퀀스 (*.gif *.png *.jpg *.jpeg *.tif *.tiff *.tga *.bmp *.webp *.dpx *.hdr *.exr)",
            "모든 파일 (*)"
        ]
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
    FolderDialog {
        id: outputFolderDialog
        title: "출력 폴더 선택"
        currentFolder: "file:///" + EditorController.outputDirectory.replace(/\\/g, "/")
        onAccepted: EditorController.setOutputDirectoryUrl(selectedFolder)
    }
    FileDialog {
        id: ocioConfigDialog
        title: "OpenColorIO 설정 선택"
        fileMode: FileDialog.OpenFile
        nameFilters: ["OpenColorIO 설정 (*.ocio *.ocioz)"]
        onAccepted: EditorController.setCustomOcioUrl(selectedFile)
    }
    FileDialog {
        id: gradeLutDialog
        title: "LUT / Look 추가"
        fileMode: FileDialog.OpenFile
        nameFilters: ["컬러 LUT / Look (*.cube *.3dl *.clf *.ctf)"]
        onAccepted: EditorController.addGradeLutUrl(selectedFile)
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
        id: gifSizeWarning
        anchors.centerIn: parent
        modal: true
        title: "GIF 예상 용량이 큽니다"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: EditorController.exportTimeline()
        Label {
            width: 430
            wrapMode: Text.WordWrap
            text: EditorController.gifEstimatedSizeText +
                  "\n\nGIF는 장면의 움직임에 따라 예상보다 더 커질 수 있습니다. " +
                  "계속 저장하려면 확인을 누르고, 취소한 뒤 크기·FPS·색상 수를 낮출 수 있습니다."
        }
    }
    Dialog {
        id: missingFrameWarning
        anchors.centerIn: parent
        modal: true
        title: "이미지 시퀀스에 누락 프레임이 있습니다"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: root.continueExport()
        Label {
            width: 440
            wrapMode: Text.WordWrap
            text: "현재 출력 구간에 누락 프레임이 " + EditorController.missingFrameCount
                  + "개 있습니다. 미리보기의 MISSING FRAME 화면 대신 시간상 가장 가까운 정상 프레임으로 대체해 출력합니다."
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
                    onClicked: root.requestExport()
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
                            height: modelData.exrPartOptions.length > 0 ? 140 : 106
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
                                              + (mediaCard.modelData.sequenceRange.length > 0
                                                 ? "  ·  " + mediaCard.modelData.sequenceRange : "")
                                        color: "#8994a3"
                                        font.pixelSize: 11
                                    }
                                    Label {
                                        visible: mediaCard.modelData.kind !== "video"
                                        text: (mediaCard.modelData.kind === "imageSequence" ? "이미지 시퀀스"
                                              : mediaCard.modelData.kind === "animatedImage" ? "애니메이션 이미지"
                                              : "스틸 이미지")
                                              + (mediaCard.modelData.missingFrameCount > 0
                                                 ? "  ·  누락 " + mediaCard.modelData.missingFrameCount + "프레임" : "")
                                              + (mediaCard.modelData.exrLayer.length > 0
                                                 ? "  ·  " + mediaCard.modelData.exrLayer : "")
                                        color: mediaCard.modelData.missingFrameCount > 0 ? "#ff7c88" : "#8ca2bb"
                                        font.pixelSize: 10
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Label {
                                            text: mediaCard.modelData.colorUnresolved ? "⚠ 입력 색" : "입력 색"
                                            color: mediaCard.modelData.colorUnresolved ? "#ffb45e" : "#8193a8"
                                            font.pixelSize: 10
                                        }
                                        ComboBox {
                                            id: inputColorSpaceBox
                                            Layout.fillWidth: true
                                            implicitHeight: 25
                                            enabled: !EditorController.importing
                                            editable: true
                                            model: EditorController.inputColorSpaceOptions
                                            currentIndex: find(mediaCard.modelData.colorSpace)
                                            editText: currentIndex < 0
                                                ? mediaCard.modelData.colorSpace : currentText
                                            ToolTip.visible: hovered
                                            ToolTip.text: "이 미디어를 해석할 OCIO 입력 색공간"
                                            onActivated: EditorController.setAssetInputColorSpace(
                                                mediaCard.assetId, currentText)
                                            onAccepted: EditorController.setAssetInputColorSpace(
                                                mediaCard.assetId, editText)
                                        }
                                    }
                                    Loader {
                                        Layout.fillWidth: true
                                        active: mediaCard.modelData.exrPartOptions.length > 0
                                        sourceComponent: RowLayout {
                                        width: parent ? parent.width : 0
                                        spacing: 5
                                        Label {
                                            text: "EXR"
                                            color: "#8ca2bb"
                                            font.pixelSize: 10
                                        }
                                        ComboBox {
                                            id: exrPartBox
                                            Layout.preferredWidth: 92
                                            implicitHeight: 25
                                            enabled: !EditorController.importing
                                            model: mediaCard.modelData.exrPartOptions
                                            textRole: "label"
                                            valueRole: "value"
                                            currentIndex: indexOfValue(mediaCard.modelData.exrPart)
                                            ToolTip.visible: hovered
                                            ToolTip.text: "OpenEXR part"
                                            onActivated: EditorController.updateExrSelection(
                                                mediaCard.assetId, currentValue, "", "")
                                        }
                                        ComboBox {
                                            id: exrViewBox
                                            Layout.preferredWidth: 78
                                            implicitHeight: 25
                                            visible: mediaCard.modelData.exrViewOptions.length > 1
                                                     || mediaCard.modelData.exrView.length > 0
                                            enabled: !EditorController.importing
                                            model: mediaCard.modelData.exrViewOptions
                                            textRole: "label"
                                            valueRole: "value"
                                            currentIndex: indexOfValue(mediaCard.modelData.exrView)
                                            ToolTip.visible: hovered
                                            ToolTip.text: "OpenEXR view"
                                            onActivated: EditorController.updateExrSelection(
                                                mediaCard.assetId, mediaCard.modelData.exrPart,
                                                currentValue, "")
                                        }
                                        ComboBox {
                                            id: exrLayerBox
                                            Layout.fillWidth: true
                                            implicitHeight: 25
                                            enabled: !EditorController.importing
                                            model: mediaCard.modelData.exrLayerOptions
                                            textRole: "label"
                                            valueRole: "value"
                                            currentIndex: indexOfValue(mediaCard.modelData.exrLayer)
                                            ToolTip.visible: hovered
                                            ToolTip.text: "표시할 레이어/AOV"
                                            onActivated: EditorController.updateExrSelection(
                                                mediaCard.assetId, mediaCard.modelData.exrPart,
                                                mediaCard.modelData.exrView, currentValue)
                                        }
                                        }
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
                                visible: EditorController.cpuPreviewFallback
                                text: "CPU 복구"
                                color: "#f5b942"
                                font.pixelSize: 10
                            }
                            ComboBox {
                                implicitWidth: 118
                                visible: EditorController.colorPipelineMode !== 0
                                model: ["검수 끄기", "Gamut", "False color"]
                                currentIndex: EditorController.reviewOverlayMode
                                onActivated: EditorController.reviewOverlayMode = currentIndex
                            }
                            AppButton {
                                text: EditorController.scopesVisible ? "스코프 닫기" : "스코프"
                                compact: true
                                onClicked: EditorController.scopesVisible =
                                    !EditorController.scopesVisible
                            }
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
                        readonly property real stampRatio: EditorController.stampBarPercent / 100
                        readonly property real expandedBarHeight:
                            EditorController.stampEnabled && EditorController.stampMode === 1
                            ? height * stampRatio / (1 + 2 * stampRatio) : 0
                        readonly property real videoTop: expandedBarHeight
                        readonly property real videoHeight: height - expandedBarHeight * 2

                        Loader {
                            id: previewVideoLoader
                            x: 0
                            y: previewSurface.videoTop
                            width: parent.width
                            height: previewSurface.videoHeight
                            active: EditorController.inProcessPreview
                            sourceComponent: VideoPreviewItem {
                                id: inProcessVideoPreview
                                Component.onCompleted:
                                    EditorController.attachVideoItem(inProcessVideoPreview)
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    acceptedButtons: Qt.LeftButton
                                    cursorShape: containsMouse ? Qt.CrossCursor : Qt.ArrowCursor
                                    onPressed: function(mouse) {
                                        EditorController.inspectPreviewPixel(
                                            mouse.x / Math.max(1, width),
                                            mouse.y / Math.max(1, height))
                                    }
                                    onPositionChanged: function(mouse) {
                                        if (pressed)
                                            EditorController.inspectPreviewPixel(
                                                mouse.x / Math.max(1, width),
                                                mouse.y / Math.max(1, height))
                                    }
                                }
                            }
                        }
                        WindowContainer {
                            id: nativePreviewContainer
                            x: 0
                            y: previewSurface.videoTop
                            width: parent.width
                            height: previewSurface.videoHeight
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
                        Label {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            anchors.margins: 10
                            z: 30
                            visible: EditorController.pixelInspectorText.length > 0
                            text: EditorController.pixelInspectorText
                            color: "#e8eef5"
                            font.family: "Consolas"
                            font.pixelSize: 11
                            padding: 6
                            background: Rectangle {
                                color: "#c80b0e12"
                                radius: 3
                                border.color: "#3a4654"
                            }
                        }
                        Label {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            z: 30
                            visible: EditorController.previewCompareEnabled &&
                                     EditorController.colorPipelineMode !== 0
                            text: "왼쪽 그레이드 후  ·  오른쪽 표시 변환"
                            color: "#d6deea"
                            font.pixelSize: 10
                            padding: 5
                            background: Rectangle { color: "#990b0e12"; radius: 3 }
                        }

                        Item {
                            id: graphicOverlayLayer
                            anchors.fill: parent
                            z: 20
                            readonly property real stampBarHeight:
                                EditorController.stampMode === 1
                                ? previewSurface.expandedBarHeight
                                : height * EditorController.stampBarPercent / 100

                            Rectangle {
                                id: topStampBar
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                height: parent.stampBarHeight
                                color: EditorController.stampMode === 0
                                       ? Qt.rgba(0, 0, 0, EditorController.stampOpacity / 100)
                                       : "transparent"
                                visible: EditorController.stampEnabled
                                ShaderEffectSource {
                                    anchors.fill: parent
                                    visible: EditorController.stampMode === 1 &&
                                             EditorController.inProcessPreview
                                    sourceItem: previewVideoLoader
                                    sourceRect: Qt.rect(
                                        0, 0, previewVideoLoader.width,
                                        Math.max(1, previewVideoLoader.height * previewSurface.stampRatio))
                                    live: true
                                    recursive: true
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    visible: EditorController.stampMode === 1
                                    color: Qt.rgba(0, 0, 0, EditorController.stampOpacity / 100)
                                }
                                Label {
                                    anchors.left: parent.left
                                    anchors.leftMargin: Math.max(10, parent.width * 28 / 1280)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: EditorController.stampInformation
                                    color: "white"
                                    font.pixelSize: Math.max(10, parent.width * 24 / 1280)
                                }
                                Label {
                                    anchors.right: parent.right
                                    anchors.rightMargin: Math.max(10, parent.width * 28 / 1280)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: EditorController.stampWorker.length > 0
                                          ? "작업자  " + EditorController.stampWorker : ""
                                    color: "white"
                                    font.pixelSize: Math.max(10, parent.width * 24 / 1280)
                                }
                            }
                            Rectangle {
                                id: bottomStampBar
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: parent.stampBarHeight
                                color: EditorController.stampMode === 0
                                       ? Qt.rgba(0, 0, 0, EditorController.stampOpacity / 100)
                                       : "transparent"
                                visible: EditorController.stampEnabled
                                ShaderEffectSource {
                                    anchors.fill: parent
                                    visible: EditorController.stampMode === 1 &&
                                             EditorController.inProcessPreview
                                    sourceItem: previewVideoLoader
                                    sourceRect: Qt.rect(
                                        0,
                                        Math.max(0, previewVideoLoader.height -
                                                 previewVideoLoader.height * previewSurface.stampRatio),
                                        previewVideoLoader.width,
                                        Math.max(1, previewVideoLoader.height * previewSurface.stampRatio))
                                    live: true
                                    recursive: true
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    visible: EditorController.stampMode === 1
                                    color: Qt.rgba(0, 0, 0, EditorController.stampOpacity / 100)
                                }
                                Label {
                                    anchors.right: parent.right
                                    anchors.rightMargin: Math.max(10, parent.width * 28 / 1280)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: EditorController.timeText(EditorController.playheadNs).slice(0, 8)
                                    color: "white"
                                    font.family: "Consolas"
                                    font.pixelSize: Math.max(10, parent.width * 24 / 1280)
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
                                    y: previewSurface.videoTop +
                                       modelData.positionY * previewSurface.videoHeight - height / 2

                                    Rectangle {
                                        anchors.fill: parent
                                        color: Qt.rgba(0, 0, 0, modelData.backgroundOpacity / 100)
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
                                        drag.minimumY: previewSurface.videoTop - overlayTextItem.height / 2
                                        drag.maximumY: previewSurface.videoTop + previewSurface.videoHeight -
                                                       overlayTextItem.height / 2
                                        onPressed: EditorController.selectCaption(modelData.id)
                                        onReleased: EditorController.updateCaptionPosition(
                                            modelData.id,
                                            (overlayTextItem.x + overlayTextItem.width / 2) /
                                                graphicOverlayLayer.width,
                                            (overlayTextItem.y + overlayTextItem.height / 2 -
                                                previewSurface.videoTop) / previewSurface.videoHeight)
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: EditorController.scopesVisible ? 190 : 0
                        visible: EditorController.scopesVisible
                        color: "#0b0e12"
                        border.color: "#27303a"
                        clip: true

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: "컬러 스코프"
                                    color: "#c8d1dc"
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                ComboBox {
                                    implicitWidth: 148
                                    model: ["그레이드 전", "그레이드 후", "디스플레이 변환 후"]
                                    currentIndex: EditorController.scopeReferenceStage
                                    onActivated: EditorController.scopeReferenceStage = currentIndex
                                }
                                Label {
                                    text: EditorController.scopeStageHint
                                    color: "#758292"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Label {
                                    visible: EditorController.outOfGamutPercent > 0
                                    text: "범위 초과 " + EditorController.outOfGamutPercent.toFixed(1) + "%"
                                    color: "#ef86c3"
                                    font.pixelSize: 10
                                }
                                ComboBox {
                                    implicitWidth: 132
                                    model: ["Waveform", "RGB Parade", "Vectorscope", "Histogram"]
                                    currentIndex: EditorController.scopeMode
                                    onActivated: EditorController.scopeMode = currentIndex
                                }
                            }
                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                ColorScopeItem {
                                    id: colorScope
                                    anchors.fill: parent
                                    mode: EditorController.scopeMode
                                    Component.onCompleted: EditorController.attachScopeItem(colorScope)
                                }
                                Label {
                                    anchors.centerIn: parent
                                    visible: !colorScope.hasSignal
                                    text: EditorController.durationNs === 0
                                          ? "미디어를 추가하면 스코프가 표시됩니다"
                                          : "프레임 분석 대기 중"
                                    color: "#687587"
                                    font.pixelSize: 11
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
                            model: ["출력", "오디오", "이펙트", "문구·스탬프", "전체 트림", "컬러 관리", "출력 설정"]
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
                                else if (nodePicker.currentIndex === 5) root.showColorManagementNode = true
                                else root.showOutputSettingsNode = true
                            }
                        }
                    }

                    InspectorNode {
                        visible: root.showOutputNode
                        nodeKey: "output"
                        title: "출력"
                        summary: EditorController.exporting
                                 ? EditorController.exportStage : EditorController.nextOutputName
                        onRemoveRequested: {
                            root.showOutputNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }
                        Label {
                            Layout.fillWidth: true
                            text: EditorController.outputDirectory
                            elide: Text.ElideMiddle
                            color: EditorController.outputDirectoryValid ? "#aeb9c7" : "#ff8990"
                            ToolTip.visible: outputPathHover.hovered
                            ToolTip.text: EditorController.outputDirectory
                            HoverHandler { id: outputPathHover }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: EditorController.outputDirectoryValid
                                  ? EditorController.nextOutputName
                                  : EditorController.outputDirectoryError
                            color: EditorController.outputDirectoryValid ? "#7f91a6" : "#ff8990"
                            font.pixelSize: 11
                            elide: Text.ElideMiddle
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            AppButton { text: "폴더 변경"; compact: true; onClicked: outputFolderDialog.open() }
                            AppButton {
                                text: "열기"; compact: true
                                enabled: EditorController.outputDirectoryValid
                                onClicked: EditorController.openOutputDirectory()
                            }
                            AppButton { text: "복사"; compact: true; onClicked: EditorController.copyOutputDirectory() }
                        }
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
                        RowLayout {
                            Layout.fillWidth: true
                            visible: EditorController.exporting
                            Label { text: "경과 " + EditorController.exportElapsedText; color: "#8f9dad"; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                            Label { text: "남은 시간 " + EditorController.exportRemainingText; color: "#8f9dad"; font.pixelSize: 11 }
                        }
                        AppButton {
                            Layout.fillWidth: true
                            text: EditorController.exporting ? "취소" : "영상 내보내기"
                            enabled: EditorController.exporting || EditorController.durationNs > 0
                            onClicked: EditorController.exporting
                                ? EditorController.cancelExport() : root.requestExport()
                        }
                    }

                    InspectorNode {
                        visible: root.showAudioNode
                        nodeKey: "audio"
                        title: "오디오"
                        summary: EditorController.selectedClipIds.length > 0
                                 ? EditorController.selectedClipIds.length + "개 클립" : "클립을 선택하세요"
                        onRemoveRequested: {
                            root.showAudioNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }
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
                        nodeKey: "effects"
                        title: "이펙트"
                        summary: "디졸브 · Color Grading"
                        onRemoveRequested: {
                            root.showEffectsNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }
                        Label { text: "클립 컬러 그레이드"; font.bold: true }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: EditorController.selectedClipIds.length === 1
                                  ? "노드는 위에서 아래 순서로 적용됩니다."
                                  : "컬러 노드를 편집할 클립 하나를 선택하세요."
                            color: "#7f8c9c"; font.pixelSize: 11
                        }
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
                        RowLayout {
                            Layout.fillWidth: true
                            enabled: EditorController.selectedClipIds.length === 1
                            ComboBox {
                                id: gradeNodePicker
                                Layout.fillWidth: true
                                model: ["Primary Wheels", "Log Wheels", "RGB Mixer", "RGB Curves", "Hue Curves", "HDR Zones", "Color Warper"]
                            }
                            AppButton {
                                text: "노드 추가"
                                onClicked: EditorController.addGradeNode(gradeNodePicker.currentIndex)
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            enabled: EditorController.selectedClipIds.length === 1
                            AppButton {
                                text: "LUT / Look"
                                Layout.fillWidth: true
                                onClicked: gradeLutDialog.open()
                            }
                            AppButton {
                                text: "붙여넣기"
                                Layout.fillWidth: true
                                enabled: EditorController.gradeClipboardAvailable
                                onClicked: EditorController.pasteGradeNode()
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: "LUT / Look은 작업 색공간의 창작 노드로 적용됩니다. 입력·표시·출력 변환은 프로젝트 컬러 설정에서 분리해 관리합니다."
                            color: "#738194"
                            font.pixelSize: 10
                        }
                        Repeater {
                            model: EditorController.selectedGradeNodes
                            delegate: Rectangle {
                                id: gradeNode
                                required property var modelData
                                function scalarControls(type) {
                                    if (type === 0) return [
                                        { label: "대비", key: "contrast", scale: 100, from: 0, to: 400 },
                                        { label: "피벗", key: "pivot", scale: 1000, from: 0, to: 1000 },
                                        { label: "채도", key: "saturation", scale: 100, from: 0, to: 400 },
                                        { label: "색조", key: "hue", scale: 1, from: -180, to: 180 },
                                        { label: "컬러 부스트", key: "colorBoost", scale: 1, from: -100, to: 100 }
                                    ]
                                    if (type === 1) return [
                                        { label: "섀도 R", key: "shadowR", scale: 1000, from: -500, to: 500 },
                                        { label: "섀도 G", key: "shadowG", scale: 1000, from: -500, to: 500 },
                                        { label: "섀도 B", key: "shadowB", scale: 1000, from: -500, to: 500 },
                                        { label: "미드 R", key: "midtoneR", scale: 1000, from: -500, to: 500 },
                                        { label: "미드 G", key: "midtoneG", scale: 1000, from: -500, to: 500 },
                                        { label: "미드 B", key: "midtoneB", scale: 1000, from: -500, to: 500 },
                                        { label: "하이라이트 R", key: "highlightR", scale: 1000, from: -500, to: 500 },
                                        { label: "하이라이트 G", key: "highlightG", scale: 1000, from: -500, to: 500 },
                                        { label: "하이라이트 B", key: "highlightB", scale: 1000, from: -500, to: 500 },
                                        { label: "Low Range", key: "lowRange", scale: 100, from: 1, to: 49 },
                                        { label: "High Range", key: "highRange", scale: 100, from: 51, to: 99 }
                                    ]
                                    if (type === 2) return [
                                        { label: "R ← R", key: "rr", scale: 100, from: -200, to: 200 },
                                        { label: "R ← G", key: "rg", scale: 100, from: -200, to: 200 },
                                        { label: "R ← B", key: "rb", scale: 100, from: -200, to: 200 },
                                        { label: "G ← R", key: "gr", scale: 100, from: -200, to: 200 },
                                        { label: "G ← G", key: "gg", scale: 100, from: -200, to: 200 },
                                        { label: "G ← B", key: "gb", scale: 100, from: -200, to: 200 },
                                        { label: "B ← R", key: "br", scale: 100, from: -200, to: 200 },
                                        { label: "B ← G", key: "bg", scale: 100, from: -200, to: 200 },
                                        { label: "B ← B", key: "bb", scale: 100, from: -200, to: 200 }
                                    ]
                                    if (type === 5) return [
                                        { label: "블랙 노출", key: "blackExposure", scale: 10, from: -100, to: 100 },
                                        { label: "섀도 노출", key: "shadowExposure", scale: 10, from: -100, to: 100 },
                                        { label: "미드 노출", key: "midtoneExposure", scale: 10, from: -100, to: 100 },
                                        { label: "하이라이트 노출", key: "highlightExposure", scale: 10, from: -100, to: 100 },
                                        { label: "스페큘러 노출", key: "specularExposure", scale: 10, from: -100, to: 100 },
                                        { label: "존 폭", key: "zoneWidth", scale: 10, from: 1, to: 80 }
                                    ]
                                    return []
                                }
                                Layout.fillWidth: true
                                implicitHeight: gradeHeader.implicitHeight + (gradeBody.visible ? gradeBody.implicitHeight + 12 : 0)
                                radius: 7
                                color: "#141a20"
                                border.color: root.expandedGradeNode === modelData.id ? "#6682a6" : "#303b47"

                                ColumnLayout {
                                    anchors.fill: parent
                                    spacing: 4
                                    RowLayout {
                                        id: gradeHeader
                                        Layout.fillWidth: true
                                        Layout.leftMargin: 8; Layout.rightMargin: 6
                                        CheckBox {
                                            checked: gradeNode.modelData.enabled
                                            onToggled: EditorController.setGradeNodeEnabled(gradeNode.modelData.id, checked)
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: gradeNode.modelData.name
                                            color: gradeNode.modelData.enabled ? "#e4ebf3" : "#687483"
                                            font.bold: true
                                            TapHandler { onTapped: root.expandedGradeNode = root.expandedGradeNode === gradeNode.modelData.id ? "" : gradeNode.modelData.id }
                                        }
                                        Label {
                                            visible: gradeNode.modelData.shared
                                            text: "공유"
                                            color: "#8fc5a6"
                                            font.pixelSize: 10
                                            font.bold: true
                                        }
                                        AppButton { text: "↑"; compact: true; onClicked: EditorController.moveGradeNode(gradeNode.modelData.id, -1) }
                                        AppButton { text: "↓"; compact: true; onClicked: EditorController.moveGradeNode(gradeNode.modelData.id, 1) }
                                        AppButton { text: "×"; compact: true; danger: true; onClicked: EditorController.removeGradeNode(gradeNode.modelData.id) }
                                    }
                                    GridLayout {
                                        id: gradeBody
                                        Layout.fillWidth: true
                                        Layout.leftMargin: 10; Layout.rightMargin: 10; Layout.bottomMargin: 8
                                        columns: 2
                                        visible: root.expandedGradeNode === gradeNode.modelData.id
                                        Label { text: "이름"; color: "#9aa7b7" }
                                        TextField {
                                            Layout.fillWidth: true
                                            text: gradeNode.modelData.name
                                            maximumLength: 80
                                            selectByMouse: true
                                            onEditingFinished: EditorController.setGradeNodeName(
                                                gradeNode.modelData.id, text)
                                        }
                                        RowLayout {
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            Label {
                                                Layout.fillWidth: true
                                                text: gradeNode.modelData.shared
                                                      ? "연결된 클립에 함께 적용"
                                                      : "이 클립에만 적용"
                                                color: gradeNode.modelData.shared ? "#8fc5a6" : "#7f8c9c"
                                                font.pixelSize: 10
                                            }
                                            AppButton {
                                                text: gradeNode.modelData.shared ? "연결 해제" : "공유로 전환"
                                                compact: true
                                                onClicked: {
                                                    if (gradeNode.modelData.shared)
                                                        EditorController.unlinkGradeNode(gradeNode.modelData.id)
                                                    else
                                                        EditorController.makeGradeNodeShared(gradeNode.modelData.id)
                                                }
                                            }
                                        }
                                        Label { text: "혼합"; color: "#9aa7b7" }
                                        SpinBox {
                                            Layout.fillWidth: true; from: 0; to: 100
                                            value: gradeNode.modelData.mixPercent
                                            textFromValue: function(value) { return value + "%" }
                                            onValueModified: EditorController.setGradeNodeMix(gradeNode.modelData.id, value)
                                        }
                                        RowLayout {
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            visible: gradeNode.modelData.keyframeSupported &&
                                                     gradeNode.modelData.parameterNames.length > 0
                                            Label { text: "키프레임"; color: "#9aa7b7" }
                                            ComboBox {
                                                id: keyframeParameterPicker
                                                Layout.fillWidth: true
                                                model: gradeNode.modelData.parameterNames
                                            }
                                            AppButton {
                                                readonly property bool keyed:
                                                    gradeNode.modelData.keyframedParameters.indexOf(
                                                        keyframeParameterPicker.currentText) >= 0
                                                readonly property bool atCurrent:
                                                    gradeNode.modelData.keyframesAtPlayhead.indexOf(
                                                        keyframeParameterPicker.currentText) >= 0
                                                text: atCurrent ? "◆" : "◇"
                                                compact: true
                                                onClicked: EditorController.toggleGradeParameterKeyframe(
                                                    gradeNode.modelData.id,
                                                    keyframeParameterPicker.currentText)
                                                ToolTip.visible: hovered
                                                ToolTip.text: atCurrent
                                                    ? "현재 원본 프레임의 키프레임 제거"
                                                    : keyed
                                                      ? "현재 원본 프레임에 키프레임 추가"
                                                      : "이 파라미터의 첫 키프레임 추가"
                                            }
                                        }
                                        Label {
                                            visible: gradeNode.modelData.type === 7
                                            text: "파일"
                                            color: "#9aa7b7"
                                        }
                                        Label {
                                            visible: gradeNode.modelData.type === 7
                                            Layout.fillWidth: true
                                            text: gradeNode.modelData.externalFileName
                                            elide: Text.ElideMiddle
                                            color: "#d5dee8"
                                            ToolTip.visible: lutHover.hovered
                                            ToolTip.text: gradeNode.modelData.externalPath
                                            HoverHandler { id: lutHover }
                                        }
                                        RowLayout {
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            Item { Layout.fillWidth: true }
                                            AppButton {
                                                text: "복사"
                                                compact: true
                                                onClicked: EditorController.copyGradeNode(gradeNode.modelData.id)
                                            }
                                            AppButton {
                                                text: "초기화"
                                                compact: true
                                                onClicked: EditorController.resetGradeNode(gradeNode.modelData.id)
                                            }
                                        }
                                        Label { visible: gradeNode.modelData.type === 0; text: "노출"; color: "#9aa7b7" }
                                        SpinBox {
                                            visible: gradeNode.modelData.type === 0
                                            Layout.fillWidth: true; from: -100; to: 100
                                            value: Math.round((gradeNode.modelData.parameters.exposure || 0) * 10)
                                            textFromValue: function(value) { return (value / 10).toFixed(1) + " stop" }
                                            onValueModified: EditorController.setGradeParameter(gradeNode.modelData.id, "exposure", value / 10)
                                        }
                                        Label { visible: gradeNode.modelData.type === 0; text: "온도"; color: "#9aa7b7" }
                                        SpinBox {
                                            visible: gradeNode.modelData.type === 0
                                            Layout.fillWidth: true; from: -100; to: 100
                                            value: Math.round(gradeNode.modelData.parameters.temperature || 0)
                                            onValueModified: EditorController.setGradeParameter(gradeNode.modelData.id, "temperature", value)
                                        }
                                        Label { visible: gradeNode.modelData.type === 0; text: "틴트"; color: "#9aa7b7" }
                                        SpinBox {
                                            visible: gradeNode.modelData.type === 0
                                            Layout.fillWidth: true; from: -100; to: 100
                                            value: Math.round(gradeNode.modelData.parameters.tint || 0)
                                            onValueModified: EditorController.setGradeParameter(gradeNode.modelData.id, "tint", value)
                                        }
                                        Repeater {
                                            model: gradeNode.scalarControls(gradeNode.modelData.type)
                                            delegate: RowLayout {
                                                required property var modelData
                                                Layout.columnSpan: 2
                                                Layout.fillWidth: true
                                                Label {
                                                    Layout.preferredWidth: 105
                                                    text: modelData.label
                                                    color: "#9aa7b7"
                                                }
                                                SpinBox {
                                                    Layout.fillWidth: true
                                                    from: modelData.from
                                                    to: modelData.to
                                                    value: Math.round(
                                                        (gradeNode.modelData.parameters[modelData.key] || 0) *
                                                        modelData.scale)
                                                    editable: true
                                                    textFromValue: function(value) {
                                                        return (value / modelData.scale).toFixed(
                                                            modelData.scale >= 100 ? 2 : 1)
                                                    }
                                                    valueFromText: function(text) {
                                                        return Math.round((parseFloat(text) || 0) * modelData.scale)
                                                    }
                                                    onValueModified: EditorController.setGradeParameter(
                                                        gradeNode.modelData.id, modelData.key,
                                                        value / modelData.scale)
                                                }
                                            }
                                        }
                                        RowLayout {
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            visible: gradeNode.modelData.type === 3 ||
                                                     gradeNode.modelData.type === 4
                                            ComboBox {
                                                id: curvePicker
                                                Layout.fillWidth: true
                                                model: gradeNode.modelData.type === 3
                                                       ? ["master", "red", "green", "blue"]
                                                       : ["hueVsHue", "hueVsSat", "hueVsLum",
                                                          "lumVsSat", "satVsSat", "satVsLum", "lumVsLum"]
                                            }
                                            SpinBox {
                                                Layout.fillWidth: true
                                                from: -100; to: 100
                                                value: gradeNode.modelData.curveMidpoints[curvePicker.currentText] || 0
                                                textFromValue: function(value) {
                                                    return value > 0 ? "+" + value : value.toString()
                                                }
                                                onValueModified: EditorController.setGradeCurveMidpoint(
                                                    gradeNode.modelData.id, curvePicker.currentText, value)
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            visible: gradeNode.modelData.type === 6
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label { text: "Hue 셀"; color: "#9aa7b7" }
                                                ComboBox {
                                                    id: warperHueCell
                                                    Layout.fillWidth: true
                                                    model: ["0°", "30°", "60°", "90°", "120°", "150°",
                                                            "180°", "210°", "240°", "270°", "300°", "330°"]
                                                }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label { text: "Hue 이동"; color: "#9aa7b7"; Layout.preferredWidth: 105 }
                                                SpinBox {
                                                    Layout.fillWidth: true; from: -180; to: 180
                                                    value: Math.round(gradeNode.modelData.parameters[
                                                        "hueShift" + warperHueCell.currentIndex] || 0)
                                                    onValueModified: EditorController.setGradeParameter(
                                                        gradeNode.modelData.id,
                                                        "hueShift" + warperHueCell.currentIndex, value)
                                                }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label { text: "채도 배율"; color: "#9aa7b7"; Layout.preferredWidth: 105 }
                                                SpinBox {
                                                    Layout.fillWidth: true; from: 0; to: 300
                                                    value: Math.round((gradeNode.modelData.parameters[
                                                        "satScale" + warperHueCell.currentIndex] === undefined
                                                        ? 1 : gradeNode.modelData.parameters[
                                                            "satScale" + warperHueCell.currentIndex]) * 100)
                                                    textFromValue: function(value) { return value + "%" }
                                                    onValueModified: EditorController.setGradeParameter(
                                                        gradeNode.modelData.id,
                                                        "satScale" + warperHueCell.currentIndex, value / 100)
                                                }
                                            }
                                        }
                                        Label {
                                            Layout.columnSpan: 2; Layout.fillWidth: true; wrapMode: Text.WordWrap
                                            visible: gradeNode.modelData.type === 3 ||
                                                     gradeNode.modelData.type === 4
                                            text: "중앙점 조절은 공통 float 렌더와 GPU LUT에 즉시 반영됩니다."
                                            color: "#7f8c9c"; font.pixelSize: 11
                                        }
                                    }
                                }
                            }
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
                        nodeKey: "graphics"
                        title: "문구·스탬프"
                        summary: EditorController.stampMode === 1
                                 ? "문구 · 확장 스탬프" : "문구 · 오버레이 스탬프"
                        onRemoveRequested: {
                            root.showGraphicsNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }

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
                                Label { text: "배경 불투명도"; color: "#b4bdc8" }
                                SpinBox {
                                    Layout.fillWidth: true
                                    from: 0; to: 100; stepSize: 5
                                    value: EditorController.selectedCaptionBackgroundOpacity
                                    textFromValue: function(value) {
                                        return value === 0 ? "없음" : value + "%"
                                    }
                                    valueFromText: function(text) { return parseInt(text) || 0 }
                                    onValueModified:
                                        EditorController.setSelectedCaptionBackgroundOpacity(value)
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: "프로그램 모니터에서 직접 끌어 배치합니다. 배경 0%는 없음, 100%는 불투명입니다."
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
                            Label { text: "배치 방식"; color: "#b4bdc8" }
                            ComboBox {
                                Layout.fillWidth: true
                                model: ["영상 위에 겹치기", "캔버스 높이 확장"]
                                currentIndex: EditorController.stampMode
                                onActivated: EditorController.setStampMode(currentIndex)
                            }
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
                            Label { text: "바 불투명도"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true
                                from: 0; to: 100; stepSize: 5
                                value: EditorController.stampOpacity
                                textFromValue: function(value) {
                                    return value === 0 ? "투명" : value + "%"
                                }
                                valueFromText: function(text) { return parseInt(text) || 0 }
                                onValueModified: EditorController.setStampOpacity(value)
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: EditorController.stampMode === 0
                                  ? "영상 위에 바를 겹칩니다. 출력 해상도는 바뀌지 않습니다."
                                  : "원본 영상은 축소하지 않고 위·아래 픽셀을 추가해 출력 높이를 늘립니다."
                            wrapMode: Text.WordWrap
                            color: "#7f8c9c"; font.pixelSize: 11
                        }
                    }

                    InspectorNode {
                        visible: root.showGlobalTrimNode
                        nodeKey: "globalTrim"
                        title: "전체 트림"
                        summary: "모든 클립의 앞·뒤를 프레임 단위로 정리"
                        onRemoveRequested: {
                            root.showGlobalTrimNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }
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
                        visible: root.showColorManagementNode
                        nodeKey: "colorManagement"
                        title: "컬러 관리"
                        summary: EditorController.colorPipelineSummary
                        onRemoveRequested: {
                            root.showColorManagementNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }
                        Label { text: "프로젝트 컬러 파이프라인"; color: "#b4bdc8" }
                        ComboBox {
                            Layout.fillWidth: true
                            model: ["현재 색 유지 · Legacy", "ACES 2.0 · ACEScg", "사용자 OpenColorIO"]
                            currentIndex: EditorController.colorPipelineMode
                            onActivated: {
                                if (currentIndex === 2 && EditorController.customOcioPath.length === 0)
                                    ocioConfigDialog.open()
                                else
                                    EditorController.setColorPipelineMode(currentIndex)
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: EditorController.colorPipelineMode === 2
                            Label {
                                Layout.fillWidth: true
                                text: EditorController.customOcioPath
                                elide: Text.ElideMiddle
                                color: "#8796a8"
                                font.pixelSize: 10
                            }
                            AppButton { text: "변경"; compact: true; onClicked: ocioConfigDialog.open() }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: EditorController.colorPipelineMode !== 0
                            wrapMode: Text.WordWrap
                            text: "입력 변환 → ACEScg 작업 → Display/View 표시 변환을 분리합니다. Legacy로 돌아가면 기존 색처리를 그대로 사용합니다."
                            color: "#7f8c9c"
                            font.pixelSize: 11
                        }
                        Label {
                            visible: EditorController.colorPipelineMode !== 0
                            text: "모니터 Display"
                            color: "#b4bdc8"
                        }
                        ComboBox {
                            Layout.fillWidth: true
                            visible: EditorController.colorPipelineMode !== 0
                            model: EditorController.displayOptions
                            displayText: EditorController.displayName.length > 0
                                         ? EditorController.displayName
                                         : "기본 출력 색공간"
                            currentIndex: Math.max(
                                0, EditorController.displayOptions.indexOf(EditorController.displayName))
                            onActivated: EditorController.setDisplayName(currentText)
                        }
                        Label {
                            visible: EditorController.colorPipelineMode !== 0
                            text: "모니터 View"
                            color: "#b4bdc8"
                        }
                        ComboBox {
                            Layout.fillWidth: true
                            visible: EditorController.colorPipelineMode !== 0
                            model: EditorController.viewOptions
                            displayText: EditorController.viewName.length > 0
                                         ? EditorController.viewName
                                         : "기본 View"
                            currentIndex: Math.max(
                                0, EditorController.viewOptions.indexOf(EditorController.viewName))
                            onActivated: EditorController.setViewName(currentText)
                        }
                        Switch {
                            visible: EditorController.colorPipelineMode !== 0
                            text: "표시 변환 우회"
                            checked: EditorController.displayTransformBypassed
                            onToggled: EditorController.setDisplayTransformBypassed(checked)
                        }
                        Switch {
                            visible: EditorController.colorPipelineMode !== 0 &&
                                     !EditorController.displayTransformBypassed
                            text: "적용 전후 비교"
                            checked: EditorController.previewCompareEnabled
                            onToggled: EditorController.setPreviewCompareEnabled(checked)
                        }
                        Switch {
                            visible: EditorController.colorPipelineMode !== 0
                            text: "HDR 모니터 출력"
                            checked: EditorController.hdrMonitoring
                            onToggled: EditorController.setHdrMonitoring(checked)
                        }
                        GridLayout {
                            visible: EditorController.colorPipelineMode !== 0 && EditorController.hdrMonitoring
                            Layout.fillWidth: true
                            columns: 2
                            Label { text: "HDR 피크"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true; from: 100; to: 10000; stepSize: 50
                                value: EditorController.hdrPeakNits
                                textFromValue: function(value) { return value + " nits" }
                                valueFromText: function(text) { return parseInt(text) || 1000 }
                                onValueModified: EditorController.setHdrPeakNits(value)
                            }
                            Label { text: "SDR 흰색"; color: "#b4bdc8" }
                            SpinBox {
                                Layout.fillWidth: true; from: 80; to: 500; stepSize: 1
                                value: EditorController.sdrWhiteNits
                                textFromValue: function(value) { return value + " nits" }
                                valueFromText: function(text) { return parseInt(text) || 203 }
                                onValueModified: EditorController.setSdrWhiteNits(value)
                            }
                        }
                    }

                    InspectorNode {
                        visible: root.showOutputSettingsNode
                        nodeKey: "outputSettings"
                        title: "출력 설정"
                        summary: ["MP4", "MKV", "MOV", "GIF"][EditorController.exportContainer]
                        onRemoveRequested: {
                            root.showOutputSettingsNode = false
                            if (root.expandedNode === nodeKey) root.expandedNode = ""
                        }
                        Label { text: "파일 형식"; color: "#b4bdc8" }
                        ComboBox { Layout.fillWidth: true; model: ["MP4", "MKV", "MOV", "GIF"]; currentIndex: EditorController.exportContainer; onActivated: EditorController.exportContainer = currentIndex }
                        Label { visible: EditorController.exportContainer !== 3; text: "화질"; color: "#b4bdc8" }
                        ComboBox { visible: EditorController.exportContainer !== 3; Layout.fillWidth: true; model: ["고화질", "균형", "용량 절약"]; currentIndex: EditorController.exportQuality; onActivated: EditorController.exportQuality = currentIndex }
                        Label { visible: EditorController.exportContainer !== 3; text: "코덱"; color: "#b4bdc8" }
                        ComboBox { visible: EditorController.exportContainer !== 3; Layout.fillWidth: true; model: ["H.264 · 높은 호환성", "H.265 / HEVC · 작은 용량", "원본 스트림 복사 · 가능할 때"]; currentIndex: EditorController.exportCodec; onActivated: EditorController.exportCodec = currentIndex }
                        Label { visible: EditorController.exportContainer !== 3; text: "해상도"; color: "#b4bdc8" }
                        ComboBox { visible: EditorController.exportContainer !== 3; Layout.fillWidth: true; model: ["원본", "4K · 3840×2160", "FHD · 1920×1080", "HD · 1280×720"]; currentIndex: EditorController.exportResolution; onActivated: EditorController.exportResolution = currentIndex }
                        Label { visible: EditorController.exportContainer !== 3; text: "프레임률"; color: "#b4bdc8" }
                        ComboBox { visible: EditorController.exportContainer !== 3; Layout.fillWidth: true; model: ["원본", "60 fps", "30 fps", "24 fps"]; currentIndex: EditorController.exportFrameRate; onActivated: EditorController.exportFrameRate = currentIndex }

                        Label {
                            visible: EditorController.exportContainer === 3
                            text: "GIF 용량 프리셋"
                            color: "#b4bdc8"
                        }
                        ComboBox {
                            visible: EditorController.exportContainer === 3
                            Layout.fillWidth: true
                            model: ["가볍게 · 공유용", "균형 · 권장", "부드럽게 · 큰 용량", "사용자 설정"]
                            currentIndex: EditorController.gifPreset
                            onActivated: EditorController.setGifPreset(currentIndex)
                        }
                        GridLayout {
                            visible: EditorController.exportContainer === 3
                            Layout.fillWidth: true
                            columns: 2
                            Label { text: "크기"; color: "#b4bdc8" }
                            ComboBox {
                                Layout.fillWidth: true
                                model: ["480×270", "640×360", "960×540"]
                                currentIndex: EditorController.gifResolution
                                onActivated: EditorController.setGifResolution(currentIndex)
                            }
                            Label { text: "초당 프레임"; color: "#b4bdc8" }
                            ComboBox {
                                Layout.fillWidth: true
                                model: ["8 fps · 작게", "12 fps · 권장", "15 fps", "20 fps · 매우 큼"]
                                currentIndex: EditorController.gifFrameRate
                                onActivated: EditorController.setGifFrameRate(currentIndex)
                            }
                            Label { text: "색상 수"; color: "#b4bdc8" }
                            ComboBox {
                                Layout.fillWidth: true
                                model: ["64색 · 작게", "128색 · 권장", "256색 · 선명"]
                                currentIndex: EditorController.gifColors
                                onActivated: EditorController.setGifColors(currentIndex)
                            }
                            Label { text: "디더링"; color: "#b4bdc8" }
                            ComboBox {
                                Layout.fillWidth: true
                                model: ["Bayer · 용량 안정", "Sierra · 그라데이션 우선", "없음 · 단순 화면"]
                                currentIndex: EditorController.gifDither
                                onActivated: EditorController.setGifDither(currentIndex)
                            }
                        }
                        Switch {
                            visible: EditorController.exportContainer === 3
                            text: "계속 반복 재생"
                            checked: EditorController.gifLoop
                            onToggled: EditorController.setGifLoop(checked)
                        }
                        Rectangle {
                            visible: EditorController.exportContainer === 3
                            Layout.fillWidth: true
                            implicitHeight: gifEstimate.implicitHeight + 20
                            radius: 6
                            color: EditorController.gifSizeRisk === 2 ? "#3d2023"
                                 : EditorController.gifSizeRisk === 1 ? "#3a3020" : "#18271f"
                            border.color: EditorController.gifSizeRisk === 2 ? "#d45b65"
                                        : EditorController.gifSizeRisk === 1 ? "#c79b45" : "#3d7352"
                            Label {
                                id: gifEstimate
                                anchors.fill: parent
                                anchors.margins: 10
                                text: {
                                    return EditorController.gifEstimatedSizeText +
                                        (EditorController.gifSizeRisk === 2
                                         ? "\n용량 위험: 해상도·FPS·색상 수를 낮추세요."
                                         : EditorController.gifSizeRisk === 1
                                           ? "\n용량 주의: 공유 제한을 확인하세요."
                                           : "\n화면 움직임에 따라 실제 용량은 달라집니다.")
                                }
                                color: "#f1f4f7"
                                wrapMode: Text.WordWrap
                                font.pixelSize: 11
                            }
                        }
                        Label {
                            visible: EditorController.exportContainer === 3
                            Layout.fillWidth: true
                            text: "GIF에는 오디오가 포함되지 않습니다. 두 단계 팔레트 최적화로 색 번짐과 불필요한 용량 증가를 줄입니다."
                            color: "#8693a3"
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                        }
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
                                return clipWidth >= 24 &&
                                       clip.timelineInNs + clip.durationNs > timeline.viewportStartNs &&
                                       clip.timelineInNs < timeline.viewportStartNs +
                                                           timeline.viewportDurationNs
                            })
                        Repeater {
                            model: timelineThumbnails.visibleThumbnailClips
                            delegate: Item {
                                id: clipCard
                                required property var modelData
                                readonly property bool selected:
                                    EditorController.selectedClipIds.indexOf(modelData.id) >= 0
                                x: 12 + timelineThumbnails.contentWidth *
                                   (modelData.timelineInNs - timeline.viewportStartNs) /
                                   Math.max(1, timeline.viewportDurationNs)
                                y: 30
                                width: timelineThumbnails.contentWidth * modelData.durationNs /
                                       Math.max(1, timeline.viewportDurationNs)
                                height: Math.max(1, timelineThumbnails.height - 44)
                                visible: x + width > 12 && x < timelineThumbnails.width - 12
                                clip: true

                                Rectangle {
                                    anchors.fill: parent
                                    color: "#0b0b0b"
                                    border.width: clipCard.selected ? 2 : 1
                                    border.color: clipCard.selected ? "#f0c66a" : "#f4f4f4"
                                }
                                Image {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    anchors.topMargin: 23
                                    visible: modelData.thumbnailAtlas.length > 0
                                    source: visible
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
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    height: 23
                                    color: "#d9000000"
                                    Label {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 10
                                        text: modelData.name
                                        elide: Text.ElideMiddle
                                        verticalAlignment: Text.AlignVCenter
                                        color: "white"
                                        font.pixelSize: 11
                                        font.bold: clipCard.selected
                                    }
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    width: 7
                                    color: clipCard.selected ? "#f0c66a" : "#e6ffffff"
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 1; height: 18; color: "#171717"
                                    }
                                }
                                Rectangle {
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    width: 7
                                    color: clipCard.selected ? "#f0c66a" : "#e6ffffff"
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 1; height: 18; color: "#171717"
                                    }
                                }
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
