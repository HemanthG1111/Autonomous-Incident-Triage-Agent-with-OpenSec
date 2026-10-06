# Delta for triage-ui

## ADDED Requirements

### Requirement: Gradio UI exposes triage workflow
The UI SHALL provide Thread ID, Incident Description, Trigger Triage, Approve Escalation,
Reject Action, Rejection Reason, Workflow State label, and Agent Log markdown components.

#### Scenario: Successful triage without escalation
- GIVEN the UI is open
- WHEN an incident is entered and Trigger Triage is clicked
- THEN the Workflow State shows COMPLETED and the Agent Log shows the response

#### Scenario: Escalation awaiting approval
- GIVEN an incident that triggers escalate_ticket
- WHEN Trigger Triage is clicked
- THEN the Workflow State shows AWAITING_APPROVAL
- AND the Approve and Reject buttons become active

#### Scenario: Approve via UI
- GIVEN the UI is in AWAITING_APPROVAL state
- WHEN Approve Escalation is clicked
- THEN the Workflow State shows RESOLVED

#### Scenario: Reject via UI
- GIVEN the UI is in AWAITING_APPROVAL state
- WHEN Reject Action is clicked with a reason
- THEN the Workflow State shows REJECTED_AND_RESUMED

### Requirement: Empty Thread ID is handled
If Thread ID is empty when Trigger Triage is clicked, the UI SHALL auto-generate a UUID.

#### Scenario: Empty Thread ID auto-generates
- GIVEN the Thread ID field is empty
- WHEN Trigger Triage is clicked
- THEN a UUID is assigned to the Thread ID field
