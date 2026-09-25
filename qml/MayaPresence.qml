import QtQuick

// Liquid glass sphere holding Maya's living inner presence.
// No bottle shape — a perfect sphere with caustic glass shell
// and a living volumetric nebula inside, driven purely by state.
Item {
    id: presence
    objectName: "mayaPresence"
    property string stateName: "idle"
    property real breath: 0

    // ── State colours ───────────────────────────────────────────
    readonly property color primaryColor: stateName === "error"     ? "#C97878"
                                        : stateName === "listening" ? "#7FD7E8"
                                        : stateName === "thinking"  ? "#8B7FD8"
                                        : stateName === "speaking"  ? "#D98B6A"
                                        : stateName === "tool"      ? "#D6B25E"
                                                                    : "#E8CFA3"
    readonly property color secondaryColor: stateName === "error"     ? "#E2A1A1"
                                          : stateName === "listening" ? "#D4F6FF"
                                          : stateName === "thinking"  ? "#D0C7FF"
                                          : stateName === "speaking"  ? "#FFE0B5"
                                          : stateName === "tool"      ? "#F4D890"
                                                                      : "#FFF0D0"

    // ── Per-state animation cadences ────────────────────────────
    readonly property int cadence:      stateName === "speaking"  ? 1500
                                      : stateName === "listening" ? 2500
                                      : stateName === "thinking"  ? 3300 : 5200
    readonly property int lightCadence: stateName === "speaking"  ? 2200
                                      : stateName === "listening" ? 4200
                                      : stateName === "thinking"  ? 3000 : 9000

    // ── Per-state dynamics (encoded as 0–1 intensities) ─────────
    // warpAmplitude: how much the nebula core wobbles
    // turbulence:    shimmer / ripple intensity
    // ripples:       number of concentric pulse rings (0–4)
    readonly property real warpAmplitude: stateName === "error"     ? 0.9
                                        : stateName === "speaking"  ? 0.7
                                        : stateName === "listening" ? 0.55
                                        : stateName === "thinking"  ? 0.42
                                        : stateName === "tool"      ? 0.38
                                                                    : 0.22
    readonly property real turbulence:   stateName === "error"     ? 1.5
                                       : stateName === "speaking"  ? 0.9
                                       : stateName === "thinking"  ? 1.2
                                       : stateName === "listening" ? 0.7
                                       : stateName === "tool"      ? 0.6
                                                                   : 0.3
    readonly property int rippleCount:   stateName === "speaking"  ? 4
                                       : stateName === "thinking"  ? 3
                                       : stateName === "listening" ? 2
                                       : stateName === "tool"      ? 2 : 0

    implicitWidth:  124
    implicitHeight: 124   // Perfect square — sphere fits inside
    Accessible.role: Accessible.Indicator
    Accessible.name: "Maya, " + stateName

    // ── Breath oscillator ────────────────────────────────────────
    SequentialAnimation on breath {
        running: presence.visible
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: presence.cadence;      easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: presence.cadence;      easing.type: Easing.InOutSine }
    }

    // ── Sphere canvas ────────────────────────────────────────────
    Canvas {
        id: sphere
        anchors.centerIn: parent
        width:  118
        height: 118

        // Animation phases
        property real flowPhase:  0
        property real warpPhase:  0
        property real pulsePhase: 0

        // Smooth colour transitions
        property color curPrimary:   presence.primaryColor
        property color curSecondary: presence.secondaryColor
        Behavior on curPrimary   { ColorAnimation { duration: 750; easing.type: Easing.OutCubic } }
        Behavior on curSecondary { ColorAnimation { duration: 750; easing.type: Easing.OutCubic } }

        onCurPrimaryChanged:   requestPaint()
        onCurSecondaryChanged: requestPaint()
        onFlowPhaseChanged:    requestPaint()
        onWarpPhaseChanged:    requestPaint()
        onPulsePhaseChanged:   requestPaint()

        // Update when breath changes
        Connections {
            target: presence
            function onBreathChanged()        { sphere.requestPaint() }
            function onWarpAmplitudeChanged() { sphere.requestPaint() }
            function onTurbulenceChanged()    { sphere.requestPaint() }
            function onRippleCountChanged()   { sphere.requestPaint() }
        }

        // ── Flow oscillator (nebula core drift) ──────────────────
        SequentialAnimation on flowPhase {
            running: presence.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 1; duration: presence.lightCadence;       easing.type: Easing.InOutSine }
            NumberAnimation { from: 1; to: 0; duration: presence.lightCadence;       easing.type: Easing.InOutSine }
        }
        // ── Warp oscillator (secondary lobe) ─────────────────────
        SequentialAnimation on warpPhase {
            running: presence.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 1; duration: presence.lightCadence * 1.35; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1; to: 0; duration: presence.lightCadence * 1.35; easing.type: Easing.InOutSine }
        }
        // ── Pulse oscillator (ripple rings) ──────────────────────
        SequentialAnimation on pulsePhase {
            running: presence.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 1; duration: presence.cadence * 0.8;      easing.type: Easing.Linear }
        }

        // ── Paint ─────────────────────────────────────────────────
        onPaint: {
            const c   = getContext("2d");
            c.reset();
            const W   = width, H = height;
            const CX  = W * 0.5, CY = H * 0.5;
            const R   = W * 0.5 - 2;          // sphere radius (1px rim clearance)

            // Derived animation values
            const breath = presence.breath;
            const flow   = Math.sin(flowPhase  * Math.PI * 2);
            const warp   = Math.sin(warpPhase  * Math.PI * 2);
            const pulse  = pulsePhase;          // 0→1 sawtooth for ripples
            const wa     = presence.warpAmplitude;
            const turb   = presence.turbulence;
            const nRip   = presence.rippleCount;

            // Colours as component arrays for easy alpha control
            const p  = curPrimary,  pr  = p.r,  pg  = p.g,  pb  = p.b;
            const s  = curSecondary,sr  = s.r,  sg  = s.g,  sb  = s.b;

            // ── Drop shadow ──────────────────────────────────────
            c.save();
            c.translate(0, 4);
            c.scale(1, 0.28);
            const sdw = c.createRadialGradient(CX, CY / 0.28 + R * 0.78, 2,
                                               CX, CY / 0.28 + R * 0.85, R * 0.92);
            sdw.addColorStop(0, "rgba(0,0,0,0.55)");
            sdw.addColorStop(1, "rgba(0,0,0,0)");
            c.beginPath(); c.arc(CX, CY / 0.28 + R * 0.85, R * 0.92, 0, Math.PI * 2);
            c.fillStyle = sdw; c.fill();
            c.restore();

            // ── Clip everything else inside the sphere ────────────
            c.save();
            c.beginPath(); c.arc(CX, CY, R, 0, Math.PI * 2); c.clip();

            // Dark glass base
            c.fillStyle = "rgba(4,5,16,0.94)";
            c.fillRect(0, 0, W, H);

            // ── Living nebula — primary core ─────────────────────
            // Drifts with flow + warp, swells with breath
            const ncX  = CX + flow * R * 0.22 * wa;
            const ncY  = CY - flow * R * 0.14 * wa + warp * R * 0.10 * wa;
            const ncR  = R * (0.55 + breath * 0.14 + wa * 0.10);
            const core = c.createRadialGradient(ncX, ncY, ncR * 0.04, ncX, ncY, ncR);
            core.addColorStop(0,    Qt.rgba(pr, pg, pb, 0.70 + breath * 0.20));
            core.addColorStop(0.30, Qt.rgba((pr + sr) * 0.5, (pg + sg) * 0.5, (pb + sb) * 0.5,
                                            0.36 + breath * 0.08));
            core.addColorStop(0.65, Qt.rgba(sr, sg, sb, 0.14));
            core.addColorStop(1,    Qt.rgba(sr, sg, sb, 0));
            c.fillStyle = core; c.fillRect(0, 0, W, H);

            // ── Secondary drifting lobe ──────────────────────────
            const l2X = CX - flow * R * 0.30 - warp * R * 0.18 * wa;
            const l2Y = CY + warp * R * 0.25 * wa + breath * R * 0.10;
            const l2R = R * (0.30 + breath * 0.08 + wa * 0.06);
            const lobe= c.createRadialGradient(l2X, l2Y, 0, l2X, l2Y, l2R);
            lobe.addColorStop(0,   Qt.rgba(sr, sg, sb, 0.38 + breath * 0.14));
            lobe.addColorStop(0.5, Qt.rgba(sr, sg, sb, 0.10));
            lobe.addColorStop(1,   Qt.rgba(sr, sg, sb, 0));
            c.fillStyle = lobe; c.fillRect(0, 0, W, H);

            // ── Ripple rings (state-specific pulse) ──────────────
            for (let i = 0; i < nRip; i++) {
                const rPhase = (pulse * 1.8 + i / Math.max(nRip, 1)) % 1;
                const rR     = R * (0.06 + rPhase * 0.80);
                const rA     = (1 - rPhase) * 0.20 * turb;
                const ring   = c.createRadialGradient(ncX, ncY, rR * 0.88, ncX, ncY, rR);
                ring.addColorStop(0,   Qt.rgba(pr, pg, pb, 0));
                ring.addColorStop(0.6, Qt.rgba(pr, pg, pb, rA));
                ring.addColorStop(1,   Qt.rgba(pr, pg, pb, 0));
                c.fillStyle = ring;
                c.beginPath(); c.arc(ncX, ncY, rR, 0, Math.PI * 2); c.fill();
            }

            // ── Shimmer threads (turbulence-driven) ─────────────
            for (let i = 0; i < 3; i++) {
                const ang = flowPhase * Math.PI * 2 + i * Math.PI * 0.667;
                const tx1 = CX + Math.cos(ang)         * R * 0.62;
                const ty1 = CY + Math.sin(ang)         * R * 0.52;
                const tx2 = CX + Math.cos(ang + 1.6)   * R * 0.44;
                const ty2 = CY + Math.sin(ang + 1.6)   * R * 0.36;
                c.beginPath();
                c.moveTo(tx1, ty1);
                c.quadraticCurveTo(ncX, ncY, tx2, ty2);
                c.strokeStyle = Qt.rgba(pr, pg, pb, 0.055 * turb);
                c.lineWidth = 1.4;
                c.stroke();
            }

            c.restore();  // end inner clip

            // ── Glass shell (drawn on top, unclipped) ────────────
            c.save();
            c.beginPath(); c.arc(CX, CY, R, 0, Math.PI * 2); c.clip();

            // Frosted glass body tint
            const glass = c.createRadialGradient(CX - R * 0.22, CY - R * 0.22, R * 0.04,
                                                  CX, CY, R);
            glass.addColorStop(0,    "rgba(200,225,255,0.038)");
            glass.addColorStop(0.55, "rgba(120,175,220,0.022)");
            glass.addColorStop(0.88, "rgba(80,140,210,0.055)");
            glass.addColorStop(1,    "rgba(40,80,150,0.18)");
            c.fillStyle = glass; c.fillRect(0, 0, W, H);

            // Primary specular caustic — upper left
            const s1 = c.createRadialGradient(CX - R * 0.42, CY - R * 0.44, 0,
                                               CX - R * 0.38, CY - R * 0.38, R * 0.40);
            s1.addColorStop(0,    "rgba(255,255,255,0.72)");
            s1.addColorStop(0.28, "rgba(240,250,255,0.26)");
            s1.addColorStop(0.65, "rgba(220,238,255,0.06)");
            s1.addColorStop(1,    "rgba(0,0,0,0)");
            c.fillStyle = s1; c.fillRect(0, 0, W, H);

            // Sharp glint — tiny bright pinpoint
            const s2 = c.createRadialGradient(CX - R * 0.53, CY - R * 0.53, 0,
                                               CX - R * 0.51, CY - R * 0.51, R * 0.10);
            s2.addColorStop(0,   "rgba(255,255,255,0.96)");
            s2.addColorStop(0.5, "rgba(255,255,255,0.28)");
            s2.addColorStop(1,   "rgba(255,255,255,0)");
            c.fillStyle = s2; c.fillRect(0, 0, W, H);

            // Bottom caustic — refracted state colour pooling at base
            const bc = c.createRadialGradient(CX + R * 0.26, CY + R * 0.54, 0,
                                               CX + R * 0.20, CY + R * 0.50, R * 0.34);
            bc.addColorStop(0,   Qt.rgba(pr, pg, pb, 0.22 + breath * 0.08));
            bc.addColorStop(0.5, Qt.rgba(pr, pg, pb, 0.08));
            bc.addColorStop(1,   Qt.rgba(pr, pg, pb, 0));
            c.fillStyle = bc; c.fillRect(0, 0, W, H);

            // Edge darkening (depth / thickness illusion)
            const edge = c.createRadialGradient(CX, CY, R * 0.76, CX, CY, R * 1.01);
            edge.addColorStop(0, "rgba(0,0,0,0)");
            edge.addColorStop(1, "rgba(0,0,12,0.58)");
            c.fillStyle = edge; c.fillRect(0, 0, W, H);

            // IOR transmission band
            c.beginPath();
            c.moveTo(CX - R * 0.14, CY - R);
            c.bezierCurveTo(CX + R * 0.58, CY - R * 0.42,
                            CX + R * 0.68, CY + R * 0.52,
                            CX + R * 0.08, CY + R);
            c.strokeStyle = "rgba(160,210,255,0.12)";
            c.lineWidth = 2.2;
            c.stroke();

            c.restore();

            // Outer rim — drawn outside clip, with gradient
            const rim = c.createLinearGradient(CX - R, CY - R, CX + R, CY + R);
            rim.addColorStop(0,    "rgba(210,240,255,0.55)");
            rim.addColorStop(0.30, "rgba(130,195,235,0.18)");
            rim.addColorStop(0.70, "rgba(80,155,205,0.10)");
            rim.addColorStop(1,    "rgba(180,225,255,0.42)");
            c.beginPath(); c.arc(CX, CY, R, 0, Math.PI * 2);
            c.strokeStyle = rim; c.lineWidth = 1.0; c.stroke();
        }
    }
}
