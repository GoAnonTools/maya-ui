import QtQuick

Item {
    id: indicator
    property bool running: false
    width: 80; height: 12; opacity: running ? 0.7 : 0
    Behavior on opacity { NumberAnimation { duration: 250 } }
    Row {
        anchors.centerIn: parent; spacing: 4
        Repeater { model: 3; delegate: Rectangle {
            width: 3; height: 3; radius: 2; color: "#55d6ff"
            SequentialAnimation on opacity { running: indicator.running; loops: Animation.Infinite
                PauseAnimation { duration: index * 120 }
                NumberAnimation { to: 0.25; duration: 420 }
                NumberAnimation { to: 0.9; duration: 420 }
            }
        }}
    }
}
