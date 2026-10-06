# Proposal

## Why

The core triage agent (Change 2) can diagnose incidents but cannot act on them when manual
intervention is needed. `docs/idea.md` requires that the agent be able to escalate — but
**never autonomously**. Every escalation must pause and wait for an engineer to approve or
reject before any ticket is created.

## What Changes

- Add `escalate_ticket(ticket_title, severity)` tool — marked as a **CRITICAL/sensitive** tool.
- Add a `sensitive_tools` node separate from `safe_tools`; only sensitive tools execute there.
- Compile the graph with `interrupt_before=["sensitive_tools"]` so execution pauses before
  any sensitive action, checkpointing state in Postgres.
- Add an `approve_escalation(thread_id)` helper that resumes the graph after an engineer approves.
- Add a `reject_escalation(thread_id, reason)` helper that injects a rejection `ToolMessage`
  and resumes without executing the ticket tool.
- Update the system prompt to instruct the agent to escalate when manual intervention is needed
  or the service stays degraded.
- Add `get_pending_escalation(thread_id)` to inspect paused state for the API layer.
- Tests for pause, approve, and reject paths using mocked LLM tool calls.

## Capabilities

### New Capabilities

- `hitl-approval`: Human-in-the-loop approval gate for sensitive agent actions.

### Modified Capabilities

- `triage-agent`: System prompt updated to include escalation instruction.

## Impact

- `agent.py`: New tools, new node, updated graph compile, new resume helpers.
- `requirements.txt`: No new dependencies (LangGraph interrupt is built-in).
- `tests/test_hitl.py`: New test file covering pause/approve/reject paths.

## Rollback

Revert `agent.py` to the previous commit. The `sensitive_tools` node and `escalate_ticket`
tool will be gone; the graph falls back to the safe-only loop. No DB migration needed.
