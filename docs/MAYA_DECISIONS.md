# Maya Architecture Decisions

This document records architectural choices that guide current work. These statements describe intended ownership and boundaries; they do not imply that every future capability is already implemented.

## Newelle is an interface layer, not the owner of Maya's LLM lifecycle

Maya prepares requests, selects policy and context, starts and tracks its response and speech lifecycle, and presents streamed results. Newelle provides the localhost GUI/API integration and generation event stream. Model inference is delegated to the separately managed local `llama-server` when configured. Maya should not make its voice, memory, or presentation lifecycle depend on Newelle owning those concerns.

## Maya owns memory

Memory configuration, persistence, retrieval, and explicit remember/forget behavior belong to Maya. Newelle may receive bounded retrieved context as part of a prompt, but it is not the memory store or policy owner. Memory remains optional and retrieved content is treated as reference material.

## The UI is presentation only

QML displays state and conversation content and forwards user actions to the controller. It does not own assistant policy, memory, tool execution, provider management, or request lifecycle logic.

## MCP is separate from core assistant logic

MCP tools live behind a separate local server and host integration. The controller should not need to know MCP transport details. Tool categories and individual operations retain narrow scopes, and tool execution should not become implicit core controller behavior.

## The voice pipeline remains independent

Wake detection, transcription, and speech output communicate through manager/provider contracts. Their lifecycle should remain decoupled from model choice, Newelle transport, and UI implementation so each can be configured or replaced independently.

## Small models need clear tool boundaries

Tool names, descriptions, parameters, and results should map directly to common user intent. Keep tools narrow and outputs easy to summarize; avoid ambiguous tools that combine actions or expose implementation details. Confirmation and permission checks belong at the operation boundary, not only in model instructions.

## Local inference is an external service boundary

`llama-server` is launched and checked as a separate process using Maya's local configuration. The request client currently talks to Newelle's GUI API rather than calling the model server directly. Keeping these boundaries explicit allows model serving and assistant orchestration to evolve separately.

## Future direction: Maya owns model provider selection

Provider switching is a future direction, not current behavior. Maya should own the choice among OpenAI-compatible providers, while Newelle remains the compatible client layer. A local Qwen model served by llama.cpp can serve privacy-sensitive, offline, and everyday use; an external compatible API can be selected for heavier reasoning. Provider changes should not alter memory, voice, MCP tools, UI architecture, or conversation flow. The expanded Maya UI should show a friendly active “brain mode” and allow manual switching without exposing endpoints or other technical configuration to ordinary users.

## Future direction: Codex is an optional delegated worker

Codex delegation is a future direction, not a current capability or runtime dependency. Maya remains responsible for conversation, voice, and user interaction; Codex handles only complex tasks Maya delegates. Simple, bounded actions remain with Maya's local MCP tools. A delegation coordinator should mediate requests between the controller and a Codex worker:

```text
Maya Controller
    |
Delegation Coordinator
    |
Codex worker
```

The coordinator should require explicit user approval before execution, bind approval to a specific task and workspace, and enforce filesystem limits. Commands must run within the approved scope; sensitive or irreversible actions require separate confirmation or must be excluded. Delegation stays separate from MCP's simple local tools and should fail independently without affecting normal Maya operation.
