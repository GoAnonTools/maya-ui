import QtQuick
import QtQuick.Window

Window {
    id: root
    property bool introFinished: false
    property bool introStarted: false
    width: 124; height: 200
    minimumWidth: 124; minimumHeight: 200
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.Tool | (mayaWindow.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
    visible: false
    // Keep the compact title stable: the existing KWin placement helper uses it.
    title: "Maya"
    onIntroStartedChanged: if (introStarted) introFinished = true

    MayaWindow {
        id: mayaWindow
        anchors.fill: parent
        opacity: root.introFinished ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
        onWorkspaceRequested: workspace.openWorkspace()
    }
    MayaWorkspace { id: workspace }

    // The compact root window hides when the workspace window is active.
    Connections {
        target: workspace
        function onVisibleChanged() {
            if (workspace.visible) {
                root.visible = false
            } else {
                root.visible = true
                root.raise()
                root.requestActivate()
            }
        }
    }

    Shortcut { sequence: "1"; onActivated: mayaController.set_demo_state(1) }
    Shortcut { sequence: "2"; onActivated: mayaController.set_demo_state(2) }
    Shortcut { sequence: "3"; onActivated: mayaController.set_demo_state(3) }
    Shortcut { sequence: "4"; onActivated: mayaController.set_demo_state(4) }
    Shortcut { sequence: "5"; onActivated: mayaController.set_demo_state(5) }
    Shortcut { sequence: "6"; onActivated: mayaController.set_demo_state(6) }
    Shortcut { sequence: "E"; onActivated: workspace.openWorkspace() }
    Shortcut { sequence: "Esc"; context: Qt.ApplicationShortcut; onActivated: mayaController.reset() }
}
