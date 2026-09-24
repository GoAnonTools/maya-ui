import QtQuick
import QtQuick.Window
import QtQuick.Controls

Item {
    id: panel
    objectName: "compactPresence"
    property bool alwaysOnTop: true
    signal workspaceRequested()

    MayaPresence {
        anchors.centerIn: parent
        stateName: mayaController.state
    }
    Menu {
        id: contextMenu
        MenuItem { text: "Open Maya workspace"; onTriggered: panel.workspaceRequested() }
        MenuItem {
            text: "Always on top"; checkable: true; checked: panel.alwaysOnTop
            onTriggered: panel.alwaysOnTop = checked
        }
    }
    MouseArea {
        id: interaction
        objectName: "presenceInteraction"
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        property real pressX: 0
        property real pressY: 0
        property bool moving: false
        onPressed: function(mouse) {
            pressX = mouse.x; pressY = mouse.y; moving = false
            if (mouse.button === Qt.RightButton) contextMenu.popup(mouse.x, mouse.y)
        }
        // Start a native drag only after movement, leaving double-click intact.
        onPositionChanged: function(mouse) {
            if (pressed && (pressedButtons & Qt.LeftButton) && !moving
                    && Math.abs(mouse.x - pressX) + Math.abs(mouse.y - pressY) > 10) {
                moving = true; panel.Window.window.startSystemMove()
            }
        }
        onDoubleClicked: function(mouse) {
            if (mouse.button === Qt.LeftButton) panel.workspaceRequested()
        }
        ToolTip.visible: containsMouse && !pressed
        ToolTip.delay: 1000
        ToolTip.text: "Maya · " + mayaController.state + "\nDouble-click to open workspace"
        Accessible.role: Accessible.Button
        Accessible.name: "Open Maya workspace"
        Accessible.onPressAction: panel.workspaceRequested()
    }
}
