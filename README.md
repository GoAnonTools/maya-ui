# Maya UI

Maya is a lightweight, local-first voice assistant shell built with Python,
Qt Quick, and QML. It provides a compact always-on-top presence, an optional
conversation workspace, wake-word interaction, speech recognition, streamed
LLM responses, text-to-speech, local memory, and guarded desktop tools.

Maya communicates with Newelle through its localhost GUI API and keeps voice,
memory, presentation, and provider orchestration in this project. Credentials
and personal runtime data are resolved locally and are never required in the
repository.

## Installation

- Python 3.9+
- PySide6 (Qt 6 with Qt Quick/QML)

On EndeavourOS, install PySide6 into a virtual environment:

```bash
cd ~/maya-ui
python3 -m venv .venv
. .venv/bin/activate
python -m pip install PySide6
```

## Running

```bash
cd ~/maya-ui
. .venv/bin/activate
python main.py
```

The compact window is frameless, transparent, always-on-top, and draggable
using Qt's native `startSystemMove()` request. It is Maya's small folded-ribbon
presence, rather than a generic assistant icon. Double-click the presence or
press `E` to open Maya's separate workspace window.

The compact window is frameless, transparent, always-on-top, and draggable.
Double-click it or press `E` to open the workspace.

## Development state controls

Press `1` through `6` to select idle, listening, thinking, speaking, tool, and
error. `Escape` returns to idle. The `MayaController` is the future backend
boundary; Newelle IPC or audio adapters can update its `state` and `detail`
properties without changing the QML components.

## Architecture

`main.py` owns application startup and injects `backend.MayaController` into
QML. `backend/maya_controller.py` owns presentation state and exposes the
latest compact exchange. `backend/newelle_client.py` is the separate
localhost API/SSE client and runs blocking HTTP work in a Qt worker thread.
`qml/` contains the visual shell. `MayaPresence.qml` is the shared identity
mark and state animation. `MayaWindow.qml` is the compact interaction surface;
its only new UI contract is the `workspaceRequested()` signal.
`MayaWorkspace.qml` is the larger presentation-only conversation shell and
reuses the controller's existing `state`, `detail`, `userText`, and
`assistantText` properties plus the existing `submit`, `start_ptt`, and
`stop_ptt` slots. No backend state is copied into QML. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full runtime design.

## Newelle GUI API

Normal graphical Newelle must be running with its GUI API enabled on
`127.0.0.1:8081`. Maya creates one chat on the first request, reuses that
chat for later turns, and consumes `/api/chats/{chat_id}/stream`. `chunk` and
`tool` events update Maya's presentation state; `done` is the definitive
transition back to idle. Only user-facing response text is displayed;
reasoning markers and tool arguments are removed.

The prototype uses translucent layered Qt Quick rectangles for the glass and
glow treatment, avoiding a blur dependency and keeping idle rendering light.
On Wayland, window movement is delegated to the compositor through Qt's native
system-move API; exact placement and drag behavior remain compositor-managed.

## Phase 2 state IPC

Maya listens for newline-delimited JSON state events on a local Unix socket:

```text
$XDG_RUNTIME_DIR/maya-ui.sock
```

If `XDG_RUNTIME_DIR` is unavailable, it falls back to
`~/.cache/maya/maya-ui.sock`. The socket is created with user-only permissions
and removed on normal application exit. Valid states are `idle`, `listening`,
`thinking`, `speaking`, `tool`, and `error`; `detail` is optional and defaults
to an empty string.

For manual testing, start Maya first, then run:

```bash
./tools/maya-state thinking
./tools/maya-state tool "Opening Firefox…"
./tools/maya-state thinking
./tools/maya-state idle
./tools/maya-state error "Tool failed"
```

Malformed JSON and unknown states are ignored safely. The user-owned Newelle
lifecycle extension is installed at
`~/.var/app/io.github.qwersyk.Newelle/config/extensions/maya_lifecycle.py`.
It wraps Newelle's existing tool-aware generation callback surface and emits
only state/detail events. Tool names are mapped to safe generic labels such as
`Opening application…`, `Searching files…`, and `Running command…`; tool
arguments are not exposed. Newelle has a user Flatpak override granting access
to the exact `/run/user/1000/maya-ui.sock` path; no TCP port is used.
