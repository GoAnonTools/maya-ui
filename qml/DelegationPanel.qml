import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    objectName: "delegationObservabilityPanel"
    Layout.fillWidth: true
    Layout.preferredHeight: 220
    color: "#252d31"
    radius: 8
    border.color: "#3a4b4d"

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 7
        RowLayout {
            Layout.fillWidth: true
            Text { text: "Delegation"; color: "#eee4d4"; font.pixelSize: 13; font.weight: Font.Medium }
            Text { text: mayaController.delegationStatus || "not connected"; color: "#b8c7c3"; font.pixelSize: 11; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 6
            TextField {
                id: delegationId
                objectName: "delegationIdField"
                Layout.fillWidth: true
                placeholderText: "Delegation ID"
                color: "#eee4d4"
                selectByMouse: true
            }
            Button {
                text: "Watch"
                onClicked: mayaController.watch_delegation(delegationId.text)
            }
        }
        Button {
            text: "Analyze this repository"
            Layout.fillWidth: true
            onClicked: mayaController.start_repository_analysis()
        }
        Text {
            visible: !!mayaController.delegationError
            text: mayaController.delegationError
            color: "#e49a8e"; font.pixelSize: 11; elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Rectangle {
            visible: Object.keys(mayaController.delegationApproval || {}).length > 0
            Layout.fillWidth: true; implicitHeight: 34; color: "#4b3c2d"; radius: 5
            Text {
                anchors.fill: parent; anchors.margins: 8
                text: "Approval required — " + ((mayaController.delegationApproval || {}).reason || (mayaController.delegationApproval || {}).message || "Maya must approve this step")
                color: "#f0d0a0"; font.pixelSize: 11; elide: Text.ElideRight
            }
            Button {
                anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                text: "Approve"
                onClicked: mayaController.approve_delegation()
            }
        }
        ListView {
            id: timeline
            objectName: "delegationTimeline"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 3
            model: mayaController.delegationTimeline
            delegate: Text {
                width: timeline.width
                text: (modelData.status || modelData.event_type || "event") + (modelData.message ? "  ·  " + modelData.message : "")
                color: "#aebcbd"; font.pixelSize: 10; elide: Text.ElideRight
            }
        }
        Text {
            visible: !!mayaController.delegationResult
            text: "Final result: " + mayaController.delegationResult
            color: "#eee4d4"; font.pixelSize: 11; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }
}
