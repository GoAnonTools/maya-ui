import QtQuick
import QtQuick.Controls

Rectangle {
    signal submitted(string text)
    signal pttPressed()
    signal pttReleased()
    property alias text: field.text
    function forceInputFocus() { field.forceActiveFocus() }
    height: 52; radius: 17; color: "#70232b30"; border.color: "#59666b68"; border.width: 1
    Button {
        id: ptt
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: 40
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.name: "Push to talk microphone"
        Accessible.description: "Hold to talk"
        ToolTip.visible: hovered || activeFocus
        ToolTip.text: "Hold to talk"
        ToolTip.delay: 500
        background: Rectangle {
            anchors.centerIn: parent
            width: 32; height: 32; radius: 16
            color: ptt.pressed || mayaController.state === "listening" ? "#305f726b" : (ptt.hovered || ptt.activeFocus ? "#207e796d" : "transparent")
            border.width: ptt.pressed || mayaController.state === "listening" ? 1 : 0
            border.color: ptt.pressed ? "#b5cfc4" : "#b5cfc4"
            opacity: ptt.pressed || mayaController.state === "listening" ? 1.0 : (ptt.hovered || ptt.activeFocus ? 0.9 : 0.72)
            Behavior on color { ColorAnimation { duration: 120 } }
            Behavior on opacity { NumberAnimation { duration: 120 } }
        }
        contentItem: Item {
            anchors.fill: parent

            // Minimal microphone glyph built from QML primitives.
            Rectangle {
                x: (parent.width - 10) / 2; y: 7
                width: 10; height: 16; radius: 5
                color: ptt.pressed || mayaController.state === "listening" ? "#cbbc9f" : "#d8ccba"
                border.width: 1
                border.color: ptt.pressed || mayaController.state === "listening" ? "#b5cfc4" : "#9baea9"
            }
            Rectangle {
                x: (parent.width - 16) / 2; y: 17
                width: 16; height: 12; radius: 8
                color: "transparent"
                border.width: 1.5
                border.color: ptt.pressed || mayaController.state === "listening" ? "#b5cfc4" : "#cbbc9f"
                clip: true
            }
            Rectangle {
                x: (parent.width - 2) / 2; y: 27
                width: 2; height: 4; radius: 1
                color: ptt.pressed || mayaController.state === "listening" ? "#b5cfc4" : "#cbbc9f"
            }
            Rectangle {
                x: (parent.width - 12) / 2; y: 31
                width: 12; height: 1.5; radius: 1
                color: ptt.pressed || mayaController.state === "listening" ? "#b5cfc4" : "#cbbc9f"
            }
        }
        onPressed: parent.pttPressed()
        onReleased: parent.pttReleased()
        Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Space && !event.isAutoRepeat) {
                parent.pttPressed(); event.accepted = true
            }
        }
        Keys.onReleased: function(event) {
            if (event.key === Qt.Key_Space && !event.isAutoRepeat) {
                parent.pttReleased(); event.accepted = true
            }
        }
    }
    TextField {
        id: field
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        anchors.leftMargin: 12; anchors.rightMargin: ptt.width + 8
        background: null; placeholderText: "Talk to Maya…"; placeholderTextColor: "#89999e"; color: "#eee4d4"; font.pixelSize: 14
        onAccepted: { if (text.trim().length > 0) { submitted(text); clear() } }
    }
}
