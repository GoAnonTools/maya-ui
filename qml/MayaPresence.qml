import QtQuick

// Smoked, hand-shaped glass holding Maya's living inner presence.
// All motion is presentation of state, independent of audio amplitude.
Item {
    id: presence
    objectName: "mayaPresence"
    property string stateName: "idle"
    property real breath: 0
    readonly property color primaryColor: stateName === "error" ? "#C97878"
        : stateName === "listening" ? "#7FD7E8"
        : stateName === "thinking" ? "#8B7FD8"
        : stateName === "speaking" ? "#D98B6A"
        : stateName === "tool" ? "#D6B25E" : "#E8CFA3"
    readonly property color secondaryColor: stateName === "error" ? "#E2A1A1"
        : stateName === "listening" ? "#D4F6FF"
        : stateName === "thinking" ? "#D0C7FF"
        : stateName === "speaking" ? "#FFE0B5"
        : stateName === "tool" ? "#F4D890" : "#FFF0D0"
    readonly property int cadence: stateName === "speaking" ? 1500
        : stateName === "listening" ? 2500 : stateName === "thinking" ? 3300 : 5200
    readonly property int lightCadence: stateName === "speaking" ? 2200
        : stateName === "listening" ? 4200 : stateName === "thinking" ? 3000 : 9000
    implicitWidth: 104
    implicitHeight: 180
    Accessible.role: Accessible.Indicator
    Accessible.name: "Maya, " + stateName

    SequentialAnimation on breath {
        running: presence.visible
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: presence.cadence; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: presence.cadence; easing.type: Easing.InOutSine }
    }
    Canvas {
        anchors.fill: parent
        onPaint: {
            let c = getContext("2d"); c.reset();
            c.scale(width / 104, height / 180);
            function shell() {
                c.beginPath(); c.moveTo(54, 7);
                c.bezierCurveTo(78, 5, 89, 30, 87, 60);
                c.bezierCurveTo(85, 93, 92, 130, 77, 157);
                c.bezierCurveTo(69, 174, 41, 177, 27, 164);
                c.bezierCurveTo(12, 151, 17, 119, 15, 93);
                c.bezierCurveTo(12, 65, 16, 35, 29, 18);
                c.bezierCurveTo(35, 10, 43, 8, 54, 7); c.closePath();
            }
            c.save(); c.translate(0, 4); shell(); c.fillStyle = "#26000000"; c.fill(); c.restore();
            shell();
            let smoke = c.createLinearGradient(18, 8, 85, 164);
            smoke.addColorStop(0, "#ed434442"); smoke.addColorStop(0.28, "#ed292f32");
            smoke.addColorStop(0.7, "#f01b2229"); smoke.addColorStop(1, "#f525292c");
            c.fillStyle = smoke; c.fill();
            c.strokeStyle = "#526e7474"; c.lineWidth = 0.8; c.stroke();
            c.save(); c.clip();
            let warmth = c.createRadialGradient(48, 116, 0, 48, 116, 64);
            warmth.addColorStop(0, "#297f6655"); warmth.addColorStop(1, "#007f6655");
            c.fillStyle = warmth; c.fillRect(0, 0, 104, 180);
            let reflection = c.createLinearGradient(20, 15, 65, 115);
            reflection.addColorStop(0, "#306f8585"); reflection.addColorStop(1, "#006f8585");
            c.fillStyle = reflection; c.beginPath(); c.moveTo(35, 15);
            c.bezierCurveTo(13, 48, 27, 104, 30, 136);
            c.bezierCurveTo(28, 78, 54, 52, 63, 12); c.closePath(); c.fill();
            c.restore();
            // Broken reflections give the glass a rim, without a badge-like border.
            c.beginPath(); c.moveTo(27, 33); c.bezierCurveTo(31, 17, 40, 11, 54, 10);
            c.strokeStyle = "#8aada69a"; c.lineWidth = 0.75; c.stroke();
            c.beginPath(); c.moveTo(83, 83); c.bezierCurveTo(84, 115, 87, 142, 73, 158);
            c.strokeStyle = "#476d7c85"; c.stroke();
            c.beginPath(); c.moveTo(33, 164); c.bezierCurveTo(46, 172, 64, 169, 70, 164);
            c.strokeStyle = "#527f7266"; c.stroke();
        }
    }
    // Maya's inner presence is light held inside the glass: no object,
    // silhouette, or edge—only a slowly breathing volumetric field.
    Canvas {
        id: fluidAtmosphere
        objectName: "fluidAtmosphere"
        anchors.fill: parent
        anchors.margins: 8
        property color currentColor: presence.primaryColor
        property color currentSecondaryColor: presence.secondaryColor
        property real flowPhase: 0
        property real radiusPhase: 0
        Behavior on currentColor { ColorAnimation { duration: 700 } }
        Behavior on currentSecondaryColor { ColorAnimation { duration: 700 } }
        onCurrentColorChanged: requestPaint()
        onCurrentSecondaryColorChanged: requestPaint()
        onFlowPhaseChanged: requestPaint()
        onRadiusPhaseChanged: requestPaint()
        Connections {
            target: presence
            function onBreathChanged() { fluidAtmosphere.requestPaint() }
        }
        SequentialAnimation on flowPhase {
            running: presence.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 1; duration: presence.lightCadence; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1; to: 0; duration: presence.lightCadence; easing.type: Easing.InOutSine }
        }
        SequentialAnimation on radiusPhase {
            running: presence.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 1; duration: presence.lightCadence * 1.35; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1; to: 0; duration: presence.lightCadence * 1.35; easing.type: Easing.InOutSine }
        }
        // The compact 124x200 window needs a little more luminance for the
        // atmosphere to read, while remaining subordinate to the glass shell.
        opacity: 0.46 + presence.breath * 0.22
        onPaint: {
            let c = getContext("2d"); c.reset();
            let w = width, h = height;
            let flow = Math.sin(flowPhase * Math.PI * 2);
            // A broad, asymmetric drift reads as internal fluid motion rather
            // than a bouncing object at the compact 124x200 scale.
            let cx = w * (0.50 + flow * 0.10);
            let cy = h * (0.49 - flow * 0.07);
            let radius = Math.max(w, h) * (0.42 + radiusPhase * 0.08 + presence.breath * 0.04);
            let field = c.createRadialGradient(cx, cy, 2, cx, cy, radius);
            field.addColorStop(0, Qt.rgba(currentColor.r, currentColor.g, currentColor.b, 0.70));
            field.addColorStop(0.38, Qt.rgba(currentColor.r, currentColor.g, currentColor.b, 0.36));
            field.addColorStop(0.72, Qt.rgba(currentSecondaryColor.r, currentSecondaryColor.g, currentSecondaryColor.b, 0.13));
            field.addColorStop(1, Qt.rgba(currentSecondaryColor.r, currentSecondaryColor.g, currentSecondaryColor.b, 0));
            c.fillStyle = field;
            c.fillRect(0, 0, w, h);
        }
    }
}
