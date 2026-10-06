# Tasks: add-hitl-escalation

- [x] Add `escalate_ticket(ticket_title, severity)` tool to agent.py (returns a mock ticket ID string)
- [x] Add `SENSITIVE_TOOLS` list and `sensitive_tools` ToolNode in agent.py
- [x] Update `route_tools` to route escalate_ticket calls to `sensitive_tools`, others to `safe_tools`
- [x] Recompile graph with `interrupt_before=["sensitive_tools"]`
- [x] Implement `get_pending_escalation(thread_id, pool)` — returns dict or None
- [x] Implement `approve_escalation(thread_id, pool)` — resumes graph from checkpoint
- [x] Implement `reject_escalation(thread_id, reason, pool)` — injects ToolMessage and resumes
- [x] Update SYSTEM_PROMPT to include escalation instruction
- [x] Export `approve_escalation`, `reject_escalation`, `get_pending_escalation` from agent.py
- [x] Write tests/test_hitl.py with mocked LLM covering: pause, approve, reject paths
- [x] Run pytest -q and confirm all tests pass
