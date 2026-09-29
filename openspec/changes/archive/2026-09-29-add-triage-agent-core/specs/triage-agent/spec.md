# Spec Delta

## Purpose

Enables autonomous incident triage by inspecting service health, retrieving relevant remediation runbooks via vector similarity, and maintaining persistent conversation state across agent invocations.

## ADDED Requirements

### Requirement: Health-first investigation
The agent SHALL check the health of any service mentioned in the incident report by calling `query_service_health` before searching for runbooks.

#### Scenario: Agent checks service health first
- **GIVEN** an incident report mentioning the "auth" service
- **WHEN** the agent processes the report
- **THEN** the agent's first tool invocation is `query_service_health` with service "auth"

### Requirement: Unknown service handling
When `query_service_health` is called for a service not present in the known service registry, the tool SHALL return a descriptive error message indicating the service is unknown instead of raising an unhandled exception.

#### Scenario: Querying an unknown service
- **GIVEN** a query for a non-existent service "billing"
- **WHEN** `query_service_health` is executed
- **THEN** it returns a message stating "Service 'billing' not found. Available services: auth, database, payments"
- **AND** no unhandled exception is raised

### Requirement: Runbook retrieval
The agent SHALL retrieve remediation runbooks from `incident_docs` using vector similarity search, returning at most the top 2 matching runbooks or a message stating "No relevant runbooks found." if no matches meet the threshold.

#### Scenario: Retrieving top two runbooks
- **GIVEN** runbooks exist in `incident_docs` for multiple incident types
- **WHEN** `search_remediation_runbooks` is called with query "auth 504 timeout"
- **THEN** at most 2 runbook documents are returned, ordered by relevance

#### Scenario: No matching runbooks
- **GIVEN** `incident_docs` returns no matches above the similarity threshold
- **WHEN** `search_remediation_runbooks` is executed
- **THEN** the tool returns "No relevant runbooks found."

### Requirement: State persistence across restarts
The agent's conversation history SHALL be persisted in PostgreSQL using LangGraph `PostgresSaver` keyed by `thread_id`, such that a newly initialized agent instance can reload and continue an existing conversation given the same `thread_id`.

#### Scenario: State survives agent re-instantiation
- **GIVEN** an agent app has processed a message under thread ID "test-thread-1"
- **WHEN** a new agent app instance is initialized and queries the state for "test-thread-1"
- **THEN** the full conversation history including prior user and agent messages is present in the state

### Requirement: Content normalisation
The system SHALL normalise list-structured LLM message content into a plain string using an `extract_text` helper, ensuring downstream consumers receive clean textual responses.

#### Scenario: Model returns list-structured content parts
- **GIVEN** an AIMessage where `content` is a list of dictionary blocks or strings
- **WHEN** `extract_text` is called on the message content
- **THEN** a single concatenated plain text string is returned
