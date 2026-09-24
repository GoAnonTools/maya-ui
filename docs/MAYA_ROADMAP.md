# Maya Roadmap

This roadmap separates current capabilities from possible improvements. Items under “Next improvements” and “Future ideas” are proposals, not claims about existing behavior.

## Stable now

- Qt Quick presents the assistant state and accepts typed input.
- The Python controller coordinates wake, STT, prompt preparation, Newelle requests, memory, and TTS.
- Wake, STT, and TTS providers have manager/provider boundaries.
- Newelle is accessed through its localhost GUI API and streamed events.
- Optional local memory uses a service/store boundary and SQLite persistence.
- A separate local MCP server exposes configuration-gated tools.
- Local Qwen inference is supported through an external `llama-server` process configured and checked by Maya helper scripts.
- Local Unix socket IPC carries state updates from helper integrations.

## Next improvements

- **Better local tools:** Make tool descriptions, parameters, and results concise and natural for small models. Add direct folder opening and clearer visible-application reporting; address the current process-listing versus window-listing gap.
- **Improved computer actions:** Make application aliases/default app resolution predictable, give focus actions a real compositor integration before exposing them, and make close operations report exact matches and avoid broad targeting.
- **Tool boundaries:** Keep capabilities narrow, permission-gated, and independently testable. Preserve filesystem root restrictions and explicit confirmation for terminal execution.
- **Maintainability:** Document configuration keys and defaults in one place; define which integration owns each lifecycle; keep routine logs useful without recording prompts, transcripts, or tool arguments.
- **Operational clarity:** Record supported Newelle, llama-server, model, and provider assumptions, plus startup and readiness behavior.

## Future ideas

- **Model provider switching:** Let Maya select among OpenAI-compatible model providers. Local Qwen served by llama.cpp would support privacy, offline use, and everyday requests; external compatible APIs could handle tasks that benefit from heavier reasoning. Maya should own provider selection, with Newelle remaining the OpenAI-compatible client layer. Switching providers should not alter memory, the voice pipeline, MCP tools, UI architecture, or conversation flow. The expanded Maya UI should show a user-friendly active “brain mode” and let users switch providers manually; endpoints and other technical details should stay out of the normal UI.
- **Codex delegation:** Let Maya delegate complex tasks to Codex while Maya remains the user-facing assistant. Maya owns conversation, voice, and user interaction; Codex is an optional specialist worker for complex work. Simple actions remain with Maya's local tools. Delegation requires explicit user approval before execution, is restricted to an approved workspace and task scope, and has clear boundaries for filesystem access, commands, and sensitive actions. Codex should be separate from simple MCP tools and must not become a dependency for normal Maya operation.
- **Stronger models:** Evaluate larger or more capable models for tool selection and complex requests while preserving the option to run within local hardware limits.
- **Automation:** Add user-defined routines for repeatable desktop tasks, with explicit triggers, inspectable steps, and clear permission boundaries before actions run.
- **Richer computer actions:** Consider search, open-folder, window-aware application discovery, and multi-step workflows after the existing core tools are reliable.
- **Extensible integrations:** Add independent adapters for other local services without coupling them to the voice pipeline or QML presentation.

These directions are future roadmap items only; they are not current Maya capabilities.
