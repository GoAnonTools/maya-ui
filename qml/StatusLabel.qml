import QtQuick
import QtQuick.Controls

Item {
    property string stateName: "idle"
    property string detail: ""
    width: 260; height: detail !== "" && detail !== (stateName === "error" ? "Something went wrong" : "") ? 38 : 22
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: stateName === "idle" ? "Maya" : ({ listening: "Listening…", thinking: "Thinking…", speaking: "Speaking", tool: "Working", error: "Something went wrong" }[stateName] || "Maya")
        color: stateName === "error" ? "#e59aa0" : "#e6e4f5"
        font.pixelSize: 15
        font.weight: Font.Medium
        font.letterSpacing: 0.65
    }
    Text {
        anchors.top: parent.top
        anchors.topMargin: 21
        anchors.horizontalCenter: parent.horizontalCenter
        text: detail
        visible: detail !== "" && detail !== (stateName === "error" ? "Something went wrong" : "")
        color: "#aaa8c1"
        opacity: 0.78
        font.pixelSize: 11
        font.letterSpacing: 0.15
        elide: Text.ElideRight
    }
}
