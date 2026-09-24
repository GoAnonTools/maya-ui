import QtQuick

Item {
    id: orb
    property real size: 108
    property string stateName: "idle"
    property real amplitude: 0.10
    property real breathValue: 1.0
    property real listeningValue: 1.0
    property real speakingValue: 1.0
    property real errorValue: 1.0
    width: size + 42
    height: size + 42

    // One quiet atmospheric halo. It expands only slightly in active states.
    Rectangle {
        anchors.centerIn: parent
        width: size + 38
        height: width
        radius: width / 2
        color: stateName === "error" ? "#a35b66" : "#8b7cff"
        opacity: stateName === "error" ? 0.12 : 0.075
        scale: orb.breathValue * (stateName === "listening" ? listeningValue : 1) * (stateName === "speaking" ? speakingValue : 1) * (stateName === "error" ? errorValue : 1)
        Behavior on opacity { NumberAnimation { duration: 260 } }
    }

    // A soft listening beacon makes the active microphone state legible even
    // when the user is not looking at the status text.
    Rectangle {
        anchors.centerIn: parent
        width: size + 22
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 1
        border.color: "#6acbd2"
        opacity: stateName === "listening" ? 0.42 : 0
        scale: stateName === "listening" ? 1.0 : 0.86
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Behavior on scale { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
        SequentialAnimation on scale {
            running: stateName === "listening"
            loops: Animation.Infinite
            NumberAnimation { to: 1.08; duration: 800; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1.0; duration: 800; easing.type: Easing.InOutSine }
        }
    }

    // The original single-core direction: dark glass, a restrained violet
    // gradient, and one thin luminous edge.
    Rectangle {
        id: core
        anchors.centerIn: parent
        width: size
        height: width
        radius: width / 2
        border.width: 1
        border.color: "#9b91ed"
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#302d59" }
            GradientStop { position: 0.42; color: "#1b1a35" }
            GradientStop { position: 1.0; color: "#090b10" }
        }
        scale: stateName === "speaking" ? orb.speakingValue : 1.0
        Behavior on scale { NumberAnimation { duration: 500; easing.type: Easing.InOutSine } }
    }

    // Thinking accents remain partial, light elements rather than a ring.
    Item {
        anchors.fill: parent
        visible: stateName === "thinking"
        opacity: 0.38
        RotationAnimation on rotation { running: visible; from: 0; to: 360; duration: 5600; loops: Animation.Infinite }
        Rectangle { x: parent.width / 2 - 0.75; y: 2; width: 1.5; height: 24; radius: 1; color: "#b8b1ff"; opacity: 0.8 }
    }
    Item {
        anchors.fill: parent
        visible: stateName === "thinking"
        opacity: 0.28
        RotationAnimation on rotation { running: visible; from: 180; to: -180; duration: 7200; loops: Animation.Infinite }
        Rectangle { x: parent.width / 2 - 0.75; y: 4; width: 1.5; height: 20; radius: 1; color: "#b8b1ff"; opacity: 0.8 }
    }

    // Cyan is reserved for tool execution; idle remains nearly monochrome.
    Rectangle {
        visible: stateName === "tool"
        width: 6
        height: 6
        radius: 3
        color: "#55d6ff"
        x: parent.width / 2 + size * 0.45
        y: parent.height / 2 - size * 0.42
        opacity: 0.78
        RotationAnimation on rotation { running: visible; from: 0; to: 360; duration: 1800; loops: Animation.Infinite }
    }

    SequentialAnimation on breathValue {
        running: true
        loops: Animation.Infinite
        NumberAnimation { to: 1.0; duration: 2000; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.018; duration: 2000; easing.type: Easing.InOutSine }
    }
    SequentialAnimation on listeningValue {
        running: stateName === "listening"
        loops: Animation.Infinite
        NumberAnimation { to: 1.015; duration: 900; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.055; duration: 1100; easing.type: Easing.InOutSine }
    }
    SequentialAnimation on speakingValue {
        running: stateName === "speaking"
        loops: Animation.Infinite
        NumberAnimation { to: 0.985; duration: 520; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.02; duration: 680; easing.type: Easing.InOutSine }
    }
    SequentialAnimation on errorValue {
        running: stateName === "error"
        loops: Animation.Infinite
        NumberAnimation { to: 1.0; duration: 900; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.08; duration: 900; easing.type: Easing.InOutSine }
    }
}
