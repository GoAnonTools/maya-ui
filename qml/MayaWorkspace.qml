import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts

Window {
    id: workspace
    objectName: "mayaWorkspace"
    title: "Maya — Workspace"
    width: 880; height: 660
    minimumWidth: 620; minimumHeight: 480
    visible: false
    color: "#191d23"
    // Independent workspace: native decoration preserves resize, move and keyboard access.
    transientParent: null
    function openWorkspace() { show(); raise(); requestActivate(); composer.forceInputFocus() }
    onClosing: function(close) { close.accepted = false; hide() }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#303333" }
            GradientStop { position: 0.65; color: "#20262c" }
            GradientStop { position: 1; color: "#191d23" }
        }
    }
    RowLayout {
        anchors.fill: parent; anchors.margins: 32; spacing: 30
        ColumnLayout {
            Layout.preferredWidth: 145; Layout.fillHeight: true; spacing: 20
            Text { text: "Maya"; color: "#eee4d4"; font.pixelSize: 25; font.weight: Font.Light }
            Text { text: "Here, whenever you need."; color: "#89999e"; font.pixelSize: 10 }
            Item { Layout.preferredHeight: 8 }
            MayaPresence { Layout.alignment: Qt.AlignHCenter; stateName: mayaController.state }
            Text {
                Layout.fillWidth: true; text: mayaController.detail; textFormat: Text.PlainText
                wrapMode: Text.Wrap; color: "#9aabae"; font.pixelSize: 11
                maximumLineCount: 5; elide: Text.ElideRight
            }
            Item { Layout.fillHeight: true }
            ComboBox {
                id: modelSelector
                objectName: "modelSelector"
                Layout.fillWidth: true
                textRole: "displayName"
                valueRole: "id"
                model: mayaController.availableProviders
                currentIndex: {
                    var list = mayaController.availableProviders || []
                    for (var i = 0; i < list.length; i++) {
                        if (list[i].id === mayaController.currentProviderName) return i
                    }
                    return 0
                }
                onActivated: function(index) {
                    var list = mayaController.availableProviders || []
                    if (index >= 0 && index < list.length) {
                        mayaController.select_provider(list[index].id)
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#253f4549" }
            Text { text: "A little space to think."; color: "#89999e"; font.pixelSize: 11 }
        }
        Rectangle { Layout.fillHeight: true; implicitWidth: 1; color: "#253f4549" }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 20
            RowLayout {
                Layout.fillWidth: true
                Text { text: "A space for us"; color: "#eee4d4"; font.pixelSize: 24; font.weight: Font.Light; Layout.fillWidth: true }
                Text { text: ""; color: "#89999e"; font.pixelSize: 9; font.letterSpacing: 1 }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#253f4549" }
            ScrollView {
                id: conversation
                objectName: "conversationScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                Column {
                    width: conversation.availableWidth; spacing: 18
                    Text {
                        visible: !mayaController.userText && !mayaController.assistantText
                        width: parent.width; topPadding: 75
                        text: "What’s on your mind?"; color: "#e2d8c8"
                        font.pixelSize: 28; font.weight: Font.Light; wrapMode: Text.Wrap
                    }
                    Text {
                        visible: !mayaController.userText && !mayaController.assistantText
                        width: parent.width; text: "Take your time. I’m here."
                        color: "#98a9ad"; font.pixelSize: 14; wrapMode: Text.Wrap
                    }
                    Text { visible: !!mayaController.userText; text: "You"; color: "#89999e"; font.pixelSize: 11; font.letterSpacing: 0.3 }
                    TextEdit {
                        visible: !!mayaController.userText; width: parent.width - 12
                        text: mayaController.userText; textFormat: TextEdit.PlainText
                        readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                        color: "#b9c6c8"; font.pixelSize: 15; selectionColor: "#4b625f"
                    }
                    Text { visible: !!mayaController.assistantText; topPadding: 16; text: "Maya"; color: "#cbbc9f"; font.pixelSize: 11; font.letterSpacing: 0.3 }
                    TextEdit {
                        visible: !!mayaController.assistantText; width: parent.width - 12
                        text: mayaController.assistantText; textFormat: TextEdit.PlainText
                        readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                        color: "#eee4d4"; font.pixelSize: 16; selectionColor: "#4b625f"
                    }
                }
            }
            InputBar {
                id: composer
                Layout.fillWidth: true
                onSubmitted: mayaController.submit(text)
                onPttPressed: mayaController.start_ptt()
                onPttReleased: mayaController.stop_ptt()
            }
            Text { text: "Enter to send  ·  Hold the microphone to talk"; color: "#89999e"; font.pixelSize: 10 }
        }
    }
}
