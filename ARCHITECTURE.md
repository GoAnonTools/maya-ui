# Maya Architecture

Maya is a local-first desktop assistant with a Python/Qt process and
independently managed local services. The UI is presentation-only; the
controller owns assistant lifecycle and routes work through provider
interfaces.

## Qt/QML UI layer

`main.py` creates `QGuiApplication`, `QQmlApplicationEngine`, the controller,
and the local IPC server. `qml/Main.qml` owns the compact top-level window and
the separate workspace. `MayaPresence.qml` is shared by both surfaces and
renders state-driven animation. QML forwards user actions to controller slots
but does not duplicate backend state or assistant policy.

## Maya controller

`backend/maya_controller.py` coordinates state, typed input, push-to-talk,
wake-triggered requests, cancellation, generation tracking, and routing of
completed transcripts into the common request path. It exposes state, detail,
transcript, and response properties to QML.

## Wake word pipeline

`backend/wake/` provides the wake interface and Sherpa-ONNX implementation.
The provider captures microphone frames, feeds the configured Maya keyword
model, and emits a wake callback. The controller changes to listening and
requests a bounded command recording.

## STT pipeline

`backend/stt/` abstracts transcription. The Whisper C++ provider consumes a
recorded WAV file or push-to-talk audio and returns a transcript. The
controller applies language selection and submits the transcript through the
same path as typed input.

## LLM provider architecture

`backend/llm/` defines provider contracts, registration, credential lookup,
and provider selection. Newelle is the default localhost GUI/API integration;
OpenAI-compatible providers can be registered without changing controller,
memory, or voice code. Secrets are resolved locally and are not stored in
provider configuration.

## TTS pipeline

`backend/tts/` manages response generations, sentence/chunk queues, synthesis,
and playback through Kokoro or Piper providers. It emits speaking lifecycle
events so the controller maintains `thinking → speaking → idle` transitions
while streamed responses and queued audio complete.

## Memory system

`backend/memory/` contains memory models, service policy, store interfaces, and
the SQLite implementation. Memory is optional and fail-closed. Explicit
remember/forget commands are handled locally; retrieved notes are bounded and
inserted into prompts as reference context rather than instructions. User
databases remain local and are ignored by Git.

## IPC communication

`backend/ipc_server.py` listens on the user-owned Unix socket
`$XDG_RUNTIME_DIR/maya-ui.sock` (with a cache fallback). Newline-delimited
JSON state messages can update presentation state without coupling external
services to QML. The Newelle client uses its localhost GUI API and streamed
events for chat generation.

## Typical voice request

```text
microphone → Sherpa wake detector → wake callback → command WAV
→ Whisper STT → controller/prompt + optional memory → LLM stream
→ TTS synthesis/playback → controller idle state → QML presence
```
