#!/usr/bin/env python3
"""Maya's lightweight Qt Quick shell."""
import os
import sys

from PySide6.QtCore import QPoint, QProcess, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from backend.maya_controller import MayaController
from backend.ipc_server import IpcServer


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Maya UI")
    app.setOrganizationName("Maya")
    app.setQuitOnLastWindowClosed(False)
    controller = MayaController()
    ipc_server = IpcServer()
    ipc_server.messageReceived.connect(controller.apply_message)
    ipc_server.start()
    app.aboutToQuit.connect(ipc_server.stop)
    # Tear down every voice subsystem before the Qt event loop exits so that
    # pw-record / whisper-cli / piper / kokoro / sherpa-wake subprocesses are
    # terminated cleanly. Without this, an abrupt quit while any of them is
    # active can orphan the process holding the microphone/audio device,
    # surfacing as "mic busy" on the next launch (audit P2).
    app.aboutToQuit.connect(controller.shutdown)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("mayaController", controller)
    qml_path = os.path.join(os.path.dirname(__file__), "qml", "Main.qml")
    engine.load(QUrl.fromLocalFile(qml_path))
    if not engine.rootObjects():
        return 1

    # Place the native window after it has been shown and Qt Quick has given it
    # its initial size.  This is intentionally done from QWindow rather than
    # QML so the compositor sees the native placement request.
    window = engine.rootObjects()[0]
    window_shown = False
    placement_attempt = 0
    kwin_processes = []
    intro_revealed = False

    def window_debug_state():
        native_id = window.winId()
        flags = window.flags()
        return (
            f"visible={window.isVisible()} size={window.width()}x{window.height()} "
            f"position=({window.x()}, {window.y()}) winId={native_id} "
            f"handle_valid={native_id != 0} flags={int(flags)} "
            f"frameless={bool(flags & Qt.WindowType.FramelessWindowHint)} "
            f"stays_on_top={bool(flags & Qt.WindowType.WindowStaysOnTopHint)}"
        )

    def request_kwin_placement(reveal=False):
        if not window.isVisible():
            print("Maya KWin placement: skipped because window is not visible", flush=True)
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            print("Maya KWin placement: skipped because no primary screen exists", flush=True)
            return
        geometry = screen.availableGeometry()
        width = window.width()
        height = window.height()
        target_x = geometry.x() + geometry.width() - width - 30
        target_y = geometry.y() + geometry.height() - height - 30
        print(
            f"Maya KWin placement: requesting compositor move to "
            f"({target_x}, {target_y}); {window_debug_state()}",
            flush=True,
        )
        process = QProcess()
        kwin_processes.append(process)
        process.setProgram(os.path.join(os.path.dirname(__file__), "tools", "kwin-place-maya"))
        process.setArguments([str(target_x), str(target_y), str(width), str(height)])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)

        def placement_finished(exit_code, _exit_status):
            if reveal:
                reveal_window()
            kwin_processes.remove(process)
            process.deleteLater()

        process.finished.connect(placement_finished)
        process.start()

    def reveal_window():
        nonlocal intro_revealed
        if intro_revealed:
            return
        intro_revealed = True
        print(f"Maya reveal: compositor placement completed; {window_debug_state()}", flush=True)
        window.setOpacity(1.0)
        window.setProperty("introStarted", True)

    def on_visible_changed(visible):
        print(
            f"Maya window became visible={visible}: {window_debug_state()}",
            flush=True,
        )
        if visible:
            QTimer.singleShot(50, lambda: request_kwin_placement(reveal=True))

    window.visibleChanged.connect(on_visible_changed)

    def place_window():
        nonlocal placement_attempt
        placement_attempt += 1
        if window.width() <= 0 or window.height() <= 0:
            print(
                f"Maya native placement: attempt={placement_attempt} "
                "window is not ready; retrying",
                flush=True,
            )
            QTimer.singleShot(100, place_window)
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            print(
                f"Maya native placement: attempt={placement_attempt} "
                "no primary screen; retrying",
                flush=True,
            )
            QTimer.singleShot(100, place_window)
            return
        geometry = screen.availableGeometry()
        width = window.width()
        height = window.height()
        x = geometry.x() + geometry.width() - width - 30
        y = geometry.y() + geometry.height() - height - 30
        print(
            f"Maya native placement: attempt={placement_attempt} "
            f"screen={geometry.width()}x{geometry.height()} "
            f"window={width}x{height} calculated=({x}, {y})",
            flush=True,
        )
        window.setPosition(QPoint(x, y))
        print(
            f"Maya native placement: final=({window.x()}, {window.y()}) "
            f"visible={window.isVisible()} winId={window.winId()}",
            flush=True,
        )

    resize_timer = QTimer()
    resize_timer.setSingleShot(True)
    resize_timer.setInterval(100)

    def reposition_after_resize():
        print(
            f"Maya resize completed; applying native bottom-right placement: "
            f"size={window.width()}x{window.height()}",
            flush=True,
        )
        place_window()
        request_kwin_placement()

    resize_timer.timeout.connect(reposition_after_resize)

    def schedule_resize_placement(*_args):
        if window_shown:
            if not resize_timer.isActive():
                request_kwin_placement()
            resize_timer.start()

    window.widthChanged.connect(schedule_resize_placement)
    window.heightChanged.connect(schedule_resize_placement)

    # Apply the initial native geometry before the surface is shown. The
    # surface is kept fully transparent until KWin confirms its Wayland move.
    place_window()
    window.setOpacity(0.0)
    print(f"Maya window before show(): {window_debug_state()}", flush=True)
    window.show()
    window_shown = True
    print(f"Maya window immediately after show(): {window_debug_state()}", flush=True)
    # Plasma may assign/restack a newly-created Wayland window after the first
    # event-loop turn. Repeat the native request briefly during startup so the
    # final request wins that race without affecting later user movement.
    for delay in (0, 250, 750, 1500, 3000):
        QTimer.singleShot(delay, place_window)
    QTimer.singleShot(3200, request_kwin_placement)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
