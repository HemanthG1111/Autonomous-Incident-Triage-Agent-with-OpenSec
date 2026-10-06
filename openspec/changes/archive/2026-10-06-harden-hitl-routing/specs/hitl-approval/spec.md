# Delta for hitl-approval

## MODIFIED Requirements

### Requirement: Sensitive actions require human approval
The agent MUST pause before executing a model message if ANY of its tool calls is sensitive,
and MUST NOT execute any sensitive tool without explicit approval for that thread.
(Previously: only the first tool call was inspected.)

#### Scenario: Escalation pauses before execution
- GIVEN an incident where the model decides to call escalate_ticket
- WHEN the graph runs
- THEN execution stops before the sensitive_tools node
- AND no ticket is created
- AND the thread state is persisted in Postgres

#### Scenario: Approved escalation executes
- GIVEN a thread paused before sensitive_tools
- WHEN an engineer calls approve_escalation(thread_id)
- THEN the graph resumes, escalate_ticket runs once
- AND the agent produces a final response

#### Scenario: Rejected escalation is not executed
- GIVEN a thread paused before sensitive_tools
- WHEN an engineer calls reject_escalation(thread_id, reason)
- THEN escalate_ticket is never executed
- AND the agent receives the rejection reason as a ToolMessage and continues reasoning

#### Scenario: Pause survives process restart
- GIVEN a thread paused before sensitive_tools
- WHEN the Python process restarts and a new graph is loaded
- THEN get_pending_escalation(thread_id) still returns the pending action details
- AND the thread can still be approved or rejected

#### Scenario: Mixed safe and sensitive calls route to sensitive_tools
- GIVEN the model returns [query_service_health, escalate_ticket] in one message
- WHEN the graph runs
- THEN execution pauses for approval before sensitive_tools
- AND the approval payload lists escalate_ticket

#### Scenario: Rejection answers every pending sensitive call
- GIVEN a paused message with multiple tool calls including escalate_ticket
- WHEN an engineer rejects
- THEN each sensitive tool call receives a ToolMessage with the rejection reason
- AND no sensitive tool executes
