# Design: add-hitl-escalation

## Key Decisions

### 1. `interrupt_before=["sensitive_tools"]` via LangGraph
LangGraph's built-in `interrupt_before` compiles a graph that auto-checkpoints and pauses
before the named node. The PostgresSaver persists the full graph state, so the thread can be
resumed hours later across restarts. No additional tables are needed.

**Alternative considered:** A custom middleware flag in Postgres. Rejected — LangGraph's native
interrupt is simpler and already integrated with the checkpointer.

### 2. Rejection via `update_state` + injected ToolMessage
On rejection, we call `graph.update_state(config, {"messages": [ToolMessage(...)]}, as_node="sensitive_tools")`
then resume with `graph.invoke(None, config)`. This tells the agent it tried to escalate but
was rejected, so it can reason about alternatives.

**Alternative considered:** Simply ending the graph on rejection. Rejected — the agent should
be able to suggest next steps after a rejection, not just stop.

### 3. Separate `sensitive_tools` node
Only `escalate_ticket` lives in `sensitive_tools`. Safe tools (`query_service_health`,
`search_remediation_runbooks`) remain in `safe_tools` which runs without interruption.
The `route_tools` function checks `tool_calls[0]["name"]` to decide the destination.

> **Known gap:** Only the first tool call is inspected. If the model emits multiple tool calls
> in one message and `escalate_ticket` is not first, it would be routed to `safe_tools` which
> doesn't contain it. This is flagged for Change 6 (`harden-hitl-routing`).

### Free-tier limits
- PostgresSaver keeps all checkpoint rows indefinitely; no automatic TTL on free Supabase.
- Gemini free tier: 15 RPM — do not call the LLM in tests; mock it.

## Implementation Notes
- `get_pending_escalation(thread_id)` reads the latest checkpoint via `PostgresSaver` and
  inspects the last `AIMessage` for any tool_calls where `name == "escalate_ticket"`.
- `approve_escalation` calls `graph.invoke(None, config)` — passing `None` resumes from checkpoint.
- `reject_escalation` injects a `ToolMessage` with `tool_call_id` matching the pending call.
