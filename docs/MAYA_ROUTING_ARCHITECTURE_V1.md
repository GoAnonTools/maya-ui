# Maya Core Routing Architecture v1

Status: contract proposal only. This document defines the routing boundary and
wire concepts; it does not implement routing or change current runtime
behavior.

## 1. Purpose

Maya Core is the orchestrator. Providers and delegated workers execute work
selected by Maya Core.

The v1 policy is online-first:

1. Maya Core deterministic logic
2. Ministral for normal conversational intelligence
3. Lightning/Hermes for specialized heavy work
4. Local Qwen for emergency or explicitly local-only operation
5. Newelle for legacy compatibility only

Provider availability is evaluated after capability classification. A provider
being available must not cause it to become the preferred worker for an
inappropriate task.

## 2. Core concepts

### 2.1 Provider role versus provider instance

`role` describes what kind of worker a provider is allowed to perform. A
`provider_id` identifies a concrete configured implementation.

For example:

```text
role: conversational
provider_id: ministral_14b
```

The routing contract uses roles so the policy does not depend on a particular
vendor, endpoint, or model name.

The existing provider ID `ministral_14b` remains stable for configuration and
credential compatibility. It currently identifies the conversational worker
configured with the `ministral-8b-2512` model; the ID is not a model-selection
contract.

### 2.2 Request identity

Every routed request belongs to:

- `request_id`: unique identifier for one assistant request
- `session_id`: stable client/user session identifier
- `conversation_id`: logical conversation identifier

These identifiers must be preserved across provider execution and fallback.
A provider-specific chat ID must not replace the Maya conversation ID.

## 3. Routing decision object

The routing decision is an internal Core object and may be emitted as
diagnostic metadata. It is not a provider implementation detail.

Conceptual schema:

```json
{
  "schema_version": 1,
  "request_id": "req-01J...",
  "session_id": "session-01J...",
  "conversation_id": "conversation-01J...",
  "intent": "conversation",
  "capabilities_required": ["conversation", "streaming"],
  "privacy_mode": "standard",
  "network_policy": "allowed",
  "tool_policy": "none",
  "preferred_role": "conversational",
  "selected_role": "conversational",
  "selected_provider_id": "ministral_14b",
  "reason_code": "normal_conversation",
  "delegation": null,
  "fallback_chain": ["local_qwen", "newelle"],
  "user_visible": false
}
```

Required semantics:

- `capabilities_required` describes the task, not the provider currently
  available.
- `preferred_role` is chosen from the request classification.
- `selected_role` and `selected_provider_id` describe the current execution
  choice.
- `fallback_chain` may only contain workers capable of satisfying the required
  capabilities.
- `reason_code` must be stable enough for logs, tests, and diagnostics.
- `delegation` is present only when a specialist worker is being used.
- `user_visible` controls whether routing detail should be shown in the UI;
  provider endpoints and implementation details remain hidden by default.

Suggested intent values:

```text
conversation
explanation
planning
rewrite
memory_operation
local_command
tool_action
repository_task
coding_task
long_running_workflow
unsupported_or_ambiguous
```

Suggested reason codes:

```text
deterministic_rule
normal_conversation
specialist_capability_required
explicit_local_only
privacy_restriction
provider_unavailable
provider_failed
legacy_compatibility
```

## 4. Worker capability schema

Every worker advertised to Maya Core should expose a capability descriptor.

Conceptual schema:

```json
{
  "provider_id": "ministral_14b",
  "role": "conversational",
  "display_name": "Ministral",
  "availability": "available",
  "capabilities": {
    "conversation": true,
    "streaming": true,
    "reasoning": true,
    "memory_context": true,
    "tool_call_proposal": true,
    "long_context": false,
    "coding": false,
    "repository_access": false,
    "filesystem_read": false,
    "filesystem_write": false,
    "network_access": true,
    "offline": false,
    "long_running_tasks": false
  },
  "constraints": {
    "max_context_tokens": null,
    "latency_class": "normal",
    "cost_class": "metered",
    "privacy_class": "external"
  }
}
```

Capability descriptors are assertions about execution capability, not routing
decisions. The router must still apply permissions, privacy policy, user
preferences, and task scope.

## 5. Provider roles

### Maya Core deterministic logic

This is not a model provider. It owns:

- command recognition
- state transitions
- conversation/session handling
- permissions
- tool policy
- safety gates
- routing classification
- fallback decisions

### Ministral

Role: `conversational`

Primary worker for:

- greetings
- ordinary questions
- explanations
- rewriting
- daily planning
- normal reasoning
- memory-aware conversation

Ministral should be the default conversational worker in online mode.

### Lightning/Hermes

Role: `specialist`

External specialist worker for:

- repository analysis
- coding workflows
- multi-file application work
- long-running tasks
- specialized heavy reasoning
- approved autonomous workflows

Lightning/Hermes is not the normal conversational worker and should not be
selected for routine chat.

### Local Qwen

Role: `offline_fallback`

Used only for:

- unavailable network or APIs
- explicit local-only mode
- privacy restrictions against external processing
- emergency continuity

Local Qwen is not loaded or preferred during normal online operation.

### Newelle

Role: `legacy_compatibility`

Used only for:

- legacy deployments
- compatibility mode
- final fallback when the Maya Core path is unavailable

Newelle is not a normal routing target and does not define Maya's domain
semantics.

## 6. Delegation contract

Delegation is used when the request requires specialist capabilities that the
normal conversational worker should not perform.

Conceptual delegation object:

```json
{
  "delegation_id": "delegation-01J...",
  "worker_role": "specialist",
  "worker_id": "lightning_hermes",
  "task_summary": "Analyze repository and propose implementation",
  "scope": {
    "workspace": "/approved/workspace",
    "allowed_operations": ["read", "write"],
    "network": false
  },
  "approval": "required",
  "parent_request_id": "req-01J..."
}
```

Delegation must preserve the parent `request_id`, `session_id`, and
`conversation_id`. It must not create an unrelated user-visible conversation.

## 7. Delegation events

All delegation events use a common envelope:

```json
{
  "schema_version": 1,
  "event_id": "event-01J...",
  "event_type": "delegation.started",
  "request_id": "req-01J...",
  "session_id": "session-01J...",
  "conversation_id": "conversation-01J...",
  "delegation_id": "delegation-01J...",
  "sequence": 3,
  "payload": {}
}
```

Reserved event types:

| Event | Meaning |
|---|---|
| `delegation.proposed` | Core classified the task as suitable for delegation. |
| `delegation.approval_required` | User approval is required before execution. |
| `delegation.approved` | The requested scope was approved. |
| `delegation.rejected` | The user or policy rejected delegation. |
| `delegation.started` | The specialist worker accepted the task. |
| `delegation.progress` | Structured progress update. |
| `delegation.tool_request` | Specialist requested an operation subject to policy. |
| `delegation.tool_result` | Result of an approved operation. |
| `delegation.completed` | Specialist produced a final result. |
| `delegation.failed` | Specialist failed without completing the task. |
| `delegation.cancelled` | User or Core cancelled execution. |

Events must be ordered by `sequence` within one delegation. A failure or
cancellation is terminal and must not be followed by progress events.

## 8. Tool activation policy

Tools are controlled by Maya Core, not by the worker alone.

The sequence is:

1. Core classifies the request.
2. Core checks whether a tool is required or appropriate.
3. Core validates permissions and scope.
4. Core requests confirmation when required.
5. A worker may propose a tool call.
6. Core authorizes or rejects the call.
7. Core emits the result back into the conversation.

Destructive, mutating, filesystem, terminal, and external-network operations
require explicit policy checks. A model instruction must never be the sole
authorization mechanism.

## 9. Fallback rules

Fallback is capability-preserving and happens only after the preferred route
has been selected.

### Normal conversation

```text
Ministral
  -> Local Qwen if local-only or external service unavailable
  -> Newelle only for legacy compatibility
```

### Specialist task

```text
Lightning/Hermes
  -> Ministral only if the task can be safely reduced to conversational help
  -> Local Qwen only for a reduced offline response
  -> Otherwise report that specialist capability is unavailable
```

A repository modification request must not silently become a normal chat
answer merely because the specialist worker is unavailable.

### Deterministic command or tool action

```text
Maya Core policy/tool path
  -> no model fallback for an unauthorized or unsafe action
```

Fallback invariants:

- Do not interrupt an active request solely because a higher-priority worker
  becomes unavailable.
- Preserve request, session, and conversation identifiers.
- Preserve privacy and permission constraints.
- Never escalate from local-only mode to an external worker.
- Never spend specialist capacity on routine conversation.
- Do not route to Newelle as a normal substitute for Ministral.

## 10. UI and Core responsibilities

### Maya UI owns

- Input capture and display
- Voice, STT, and TTS lifecycle
- QML presentation
- Sending provider-neutral requests to Maya Core
- Rendering text, state, progress, and delegation events
- Local compatibility behavior when Core is unreachable
- Keeping active requests and UI threads responsive

### Maya Core owns

- Request classification
- Routing decisions
- Provider capability matching
- Conversation/session continuity
- Memory policy
- Tool permissions
- Delegation approval and scope
- Worker fallback
- Structured response and delegation events

### Providers and workers own

- Model or worker execution
- Streaming execution events
- Provider-specific transport
- Provider-specific error normalization

They must not own Maya memory, identity, permission policy, or UI state.

## 11. Compatibility with current behavior

This contract does not change the current implementation.

Until routing is implemented:

- `ProviderManager` remains unchanged.
- Existing provider selection remains unchanged.
- Newelle remains available.
- Existing Maya Core lifecycle behavior remains unchanged.
- Current localhost operation remains unchanged.
- No Lightning/Hermes worker is assumed to exist.
- No local Qwen routing policy is activated.
- No QML changes are required.

The contract is intentionally additive and can later be implemented behind
the existing provider-neutral request and streaming-event interfaces.

## 12. Non-goals for v1

- Implementing routing logic
- Moving memory into Maya Core
- Adding authentication
- Defining remote deployment
- Selecting a specific Lightning or Hermes product
- Replacing `ProviderManager`
- Removing Newelle
- Loading or tuning local Qwen during normal operation
