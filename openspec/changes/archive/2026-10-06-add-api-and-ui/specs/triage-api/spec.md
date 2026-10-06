# Delta for triage-api

## ADDED Requirements

### Requirement: Chat endpoint triggers triage
POST /chat SHALL accept {thread_id, message} and return status COMPLETED with the agent
response, or AWAITING_APPROVAL with pending_action and parameters when escalation is pending.

#### Scenario: Completed triage
- GIVEN a valid thread_id and message
- WHEN POST /chat is called
- THEN the response has status COMPLETED and a non-empty response field

#### Scenario: Awaiting approval
- GIVEN a message that causes the agent to call escalate_ticket
- WHEN POST /chat is called
- THEN the response has status AWAITING_APPROVAL
- AND pending_action contains the tool name and parameters

### Requirement: Approve endpoint resumes paused thread
POST /approve SHALL accept {thread_id} and resume the paused escalation.
It SHALL return HTTP 400 when no escalation is pending for the thread.

#### Scenario: Successful approval
- GIVEN a thread in AWAITING_APPROVAL state
- WHEN POST /approve is called
- THEN the response has status RESOLVED

#### Scenario: Nothing pending returns 400
- GIVEN a thread that is not awaiting approval
- WHEN POST /approve is called
- THEN HTTP 400 is returned

### Requirement: Reject endpoint injects rejection and resumes
POST /reject SHALL accept {thread_id, reason} and inject a rejection ToolMessage,
then resume the agent without executing the sensitive tool.

#### Scenario: Successful rejection
- GIVEN a thread in AWAITING_APPROVAL state
- WHEN POST /reject is called with a reason
- THEN the response has status REJECTED_AND_RESUMED
- AND no ticket is created

### Requirement: Healthz returns 200 without external calls
GET /healthz SHALL return HTTP 200 and {"status": "ok"} without calling Gemini or the database.

#### Scenario: Health check
- GIVEN the server is running
- WHEN GET /healthz is called
- THEN HTTP 200 is returned with {"status": "ok"}
