# Proposal

## Why

The archived `hitl-approval` spec says:
> The agent MUST pause before executing any sensitive tool and MUST NOT execute it
> without an explicit approval for that thread.

The original implementation of `route_tools` only inspected `tool_calls[0]` -- the first
tool call in a model message. If the model emits a mixed message such as
`[query_service_health, escalate_ticket]`, routing sends it to `safe_tools` which does not
contain `escalate_ticket`. This causes either a KeyError at runtime or, after a future refactor,
silent unapproved execution.

This change hardens routing to check every tool call and route to `sensitive_tools` whenever
any call is sensitive. The requirement is MODIFIED (not new).

## What Changes

- `route_tools` in `agent.py`: already iterates all tool_calls (implemented proactively).
- `tests/test_hitl.py`: two regression tests added for mixed safe+sensitive routing.

## Capabilities

### Modified Capabilities

- `hitl-approval`: MODIFIED -- routing now checks ALL tool calls, not just the first.

## Impact

- `agent.py`: `route_tools` function verified correct.
- `tests/test_hitl.py`: regression tests cover mixed-call scenario.

## Rollback

Revert `route_tools` to only inspect `tool_calls[0]`. Risk: silent bypass on mixed messages.
