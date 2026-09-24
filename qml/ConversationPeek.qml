import QtQuick

Item {
    property string userText: ""
    property string assistantText: ""
    height: userText === "" ? 48 : 74

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        width: parent.width - 36
        text: userText === "" ? "Ready when you are" : userText
        color: userText === "" ? "#77768a" : "#aaa8bf"
        font.pixelSize: 12
        font.letterSpacing: 0.2
        elide: Text.ElideRight
        maximumLineCount: 2
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 25
        width: parent.width - 36
        text: assistantText
        color: "#e6e4f5"
        font.pixelSize: 12
        font.letterSpacing: 0.1
        elide: Text.ElideRight
        maximumLineCount: 2
        visible: assistantText !== ""
    }
}
