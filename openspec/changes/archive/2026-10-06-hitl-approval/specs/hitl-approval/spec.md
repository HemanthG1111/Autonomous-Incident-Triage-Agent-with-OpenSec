# Delta for hitl-approval

## ADDED Requirements

### Requirement: Sensitive actions require human approval
The agent MUST pause before executing any sensitive tool and MUST NOT execute it
without an explicit approval for that thread.

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

### Requirement: Pending escalation is inspectable
The system SHALL expose get_pending_escalation(thread_id) returning the pending tool
call name and arguments when a thread is awaiting approval, or None otherwise.

#### Scenario: Pending escalation returns details
- GIVEN a thread paused before sensitive_tools
- WHEN get_pending_escalation is called with that thread_id
- THEN it returns a dict with tool_name and parameters fields

#### Scenario: No pending escalation returns None
- GIVEN a thread that has completed without escalation
- WHEN get_pending_escalation is called
- THEN it returns None
