# Delta for triage-agent

## ADDED Requirements

### Requirement: Escalation instruction in system prompt
The agent's system prompt SHALL instruct it to call escalate_ticket when manual
intervention is needed or a service remains degraded after runbook steps.

#### Scenario: Agent chooses to escalate on degraded service
- GIVEN an incident where service health shows DEGRADED status
- WHEN the agent has already searched runbooks and the issue persists
- THEN the model emits an escalate_ticket tool call
