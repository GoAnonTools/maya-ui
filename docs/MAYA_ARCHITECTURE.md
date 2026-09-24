# Maya Architecture

This document describes the current implementation in this repository. Maya is a local desktop assistant shell: it owns the voice and memory orchestration, request preparation, presentation state, and local tool server. Newelle and the local model server are separate runtime processes.

## Components and responsibilities

| Component | Responsibility | Boundary |
|---|---|---|
| Wake detection (`backend/wake/`) | `WakeManager` owns wake-provider configuration and lifecycle. `SherpaProvider` captures microphone audio, detects the configured wake phrase, and captures the following command audio. | A provider callback interface reports detection, command WAV readiness, errors, and audio level. It does not transcribe or interpret the command. |
| Speech-to-text (`backend/stt/`) | `STTManager` owns STT configuration and request generations. `WhisperCppProvider` records or transcribes audio and reports transcript, errors, and level. | The manager communicates through the STT provider and callback contract. It does not submit assistant requests. |
| Controller (`backend/maya_controller.py`) | `MayaController` coordinates state, typed and voice input, wake/STT/TTS lifecycles, request submission, language selection, memory commands, and prompt preparation. It exposes properties and signals for the UI. | It connects services through their public interfaces and routes assistant work to `NewelleClient`. It does not render QML or implement wake/STT/TTS engines. |
| Behaviour policy (`backend/behaviour_policy.py`) | Deterministically classifies a request and supplies a short response instruction. | Pure local policy: no model call or runtime I/O. Its output is guidance, not an authorization mechanism for tools. |
| Prompt builder (`backend/prompt_builder.py`) | Assembles behaviour, language, optional memory reference, and user request in a fixed order with bounded added context. | Pure prompt composition. It receives prepared values and does not retrieve memory or call a model. |
| Memory (`backend/memory/`) | `MemoryService` applies local settings and retrieval/write policy; models represent memory records and context; `MemoryStore` abstracts persistence; `SQLiteMemoryStore` persists locally. The controller handles explicit remember/forget flows. | Memory is optional and fail-closed when disabled or misconfigured. Retrieved notes are labeled as reference information in the prompt. Maya, not Newelle, owns this feature and its storage. |
| Newelle client (`backend/newelle_client.py`) | `NewelleClient` manages one-at-a-time worker threads. A worker uses Newelle's localhost GUI API to create/reuse a chat, submit the prompt, and consume streamed events. It strips reasoning markers from user-facing text and maps tool events to generic UI details. | HTTP/SSE is the integration boundary. Network work runs outside the Qt GUI thread. Newelle provides the generation interface and tool-aware event stream; Maya owns its surrounding request, voice, memory, and UI state lifecycle. |
| Qwen / `llama-server` | The local model server is an external process. `tools/maya-llm-start` reads Maya's LLM configuration and starts `llama-server` with the configured model, alias, loopback host, port, context size, and GPU layers. `tools/maya-llm-ready` checks the configured API for that alias. | Maya's request path goes through Newelle's GUI API; the Maya client does not call the llama-server endpoint directly. Newelle must be configured to use the local model for this arrangement. |
| MCP tools (`backend/mcp_server.py`, `tools/maya-mcp`) | A separate stdio MCP server exposes category-gated system, application, filesystem, and terminal tools. Filesystem access is restricted to Documents, Downloads, and Projects; terminal execution is disabled unless configured and requires a confirmation token. | MCP transport and tool execution are separate from the controller's core request logic. Newelle can host/call tools and report tool events; Maya's MCP process does not own prompts, memory, or voice. |
| Text-to-speech (`backend/tts/`) | `TTSManager` selects Piper or Kokoro, sanitizes and chunks streamed assistant text, queues playback, and reports lifecycle and audio-level events. | Providers implement a shared interface. The controller coordinates speech lifecycle; TTS does not call the LLM or own UI rendering. |
| QML UI (`qml/`) | Components render Maya's orb, status, tool indicator, conversation preview, and input. They call controller slots for user actions and display controller properties. | Presentation only. Runtime decisions and service behavior belong in Python. |
| State IPC (`backend/ipc_protocol.py`, `backend/ipc_server.py`) | A local Unix socket receives newline-delimited JSON state messages from helper integrations. | IPC validates incoming messages and emits them to the controller; it does not execute MCP tools or generate responses. |

## Main data flows

### Voice request

1. `WakeManager` starts or resumes wake capture through `SherpaProvider`.
2. On wake detection, the provider captures the user's command to a WAV and emits `commandReady`.
3. The controller hands that file to `STTManager`; generation identifiers prevent stale STT callbacks from taking over a newer request.
4. The transcript returns to the controller, which detects a spoken language, handles explicit memory commands locally, and otherwise retrieves optional memory context.
5. Behaviour policy and prompt builder prepare the request. The controller starts TTS streaming and submits the prompt through `NewelleClient`.
6. Newelle streams text, tool, completion, or error events. Text updates the UI and TTS; tool events update the controller's presentation state; completion flushes the last speech chunk.
7. TTS finishes playback and the controller returns Maya to idle. The wake manager resumes according to the controller state.

### Typed request

The QML input calls the controller's `submit` slot. The controller cancels conflicting STT activity, handles explicit memory commands, prepares the prompt and optional memory context, then submits through the same Newelle client and streamed response path used by voice requests.

### MCP tool request

The MCP host launches `tools/maya-mcp`, which serves MCP JSON-RPC over stdio. `tools/list` exposes only tools in enabled categories. `tools/call` dispatches to the local implementation and returns a JSON result in MCP text content. This is an integration path hosted outside the controller; the Newelle event stream can tell Maya that a tool is running without exposing arguments in the UI label.

### External state event

A local helper sends one newline-delimited JSON message to Maya's Unix socket. `IpcServer` validates and emits the message; the controller applies valid state and detail values, which QML then renders.

## Cross-component invariants

- Qt-facing controller state is changed on the controller's Qt thread; wake callbacks are queued across the thread boundary.
- STT and TTS generation IDs prevent stale asynchronous callbacks from affecting the current lifecycle.
- Wake command audio remains available until STT has finished with it; cleanup is coordinated between the provider and controller.
- Newelle's `done` event ends generation, but queued TTS playback may continue after it.
- Prompt sections remain bounded, and retrieved memory remains reference material rather than instructions.
- Filesystem MCP operations stay within their allowed roots; tool categories remain configuration-gated.
- QML presents controller state and sends user actions; it does not become the owner of service logic.
