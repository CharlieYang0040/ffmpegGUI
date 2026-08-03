import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

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
                Rectangle {
                    anchors.fill: parent
                    color: "#080a0d"
                    Label { anchors.centerIn: parent; text: "미리보기"; color: "#657080" }
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
            Rectangle {
                anchors.fill: parent
                color: "#151a20"
                Label { anchors.centerIn: parent; text: "00:00:00:00"; color: "#8994a3" }
            }
        }
    }
}
