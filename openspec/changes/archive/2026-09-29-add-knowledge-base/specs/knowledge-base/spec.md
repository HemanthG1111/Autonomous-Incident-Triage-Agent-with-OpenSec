# Spec Delta

## Purpose

Provides a pgvector-backed runbook knowledge base that the triage agent can query by semantic
similarity to find relevant remediation steps for any reported incident.

## ADDED Requirements

### Requirement: Runbook storage
The system SHALL store runbooks in the `incident_docs` table with a `content` text column,
a `metadata` jsonb column (e.g. `{"service": "auth"}`), and a 768-dimension `embedding` vector column.

#### Scenario: Schema matches embedding size
- **GIVEN** the migration has been applied to Supabase
- **WHEN** a 768-dimension vector is inserted into `incident_docs`
- **THEN** the insert succeeds
- **AND** a vector of any other dimension is rejected by the schema constraint

#### Scenario: Metadata is queryable
- **GIVEN** a runbook row exists with `metadata = {"service": "auth"}`
- **WHEN** a jsonb containment query `metadata @> '{"service":"auth"}'` is run
- **THEN** that row is returned

### Requirement: Idempotent seeding
Running `seed_rag.py` more than once SHALL NOT create duplicate runbook rows. The script
MUST detect existing rows by a stable identifier (content hash or title) and skip them.

#### Scenario: Re-running the seed
- **GIVEN** the three runbooks (auth 504 timeouts, database high latency, payment gateway failures) have already been seeded
- **WHEN** `seed_rag.py` is executed a second time
- **THEN** the `incident_docs` table still contains exactly three rows — no duplicates are added

#### Scenario: First-time seeding
- **GIVEN** the `incident_docs` table is empty
- **WHEN** `seed_rag.py` is executed
- **THEN** the table contains exactly three rows with the expected service metadata

### Requirement: Semantic retrieval function
The database SHALL expose a `match_incident_docs(query_embedding vector(768), match_count int, filter jsonb)` 
RPC function that returns rows ordered by cosine similarity, filtered by jsonb containment on `metadata`.

#### Scenario: Filter by service
- **GIVEN** runbooks for auth, database and payments are stored in `incident_docs`
- **WHEN** `match_incident_docs` is called with `filter = '{"service": "auth"}'` and `match_count = 5`
- **THEN** only rows with `metadata @> '{"service":"auth"}'` are returned, ordered by cosine similarity descending

#### Scenario: No filter returns top matches globally
- **GIVEN** runbooks for multiple services are stored
- **WHEN** `match_incident_docs` is called with an empty filter `'{}'`
- **THEN** the top `match_count` most similar rows are returned regardless of service

### Requirement: Embedding dimensions
All embeddings stored in `incident_docs` MUST use exactly 768 dimensions, produced by the
Gemini embeddings model with `output_dimensionality=768`.

#### Scenario: Seed uses correct task type
- **GIVEN** `seed_rag.py` is run with a mocked embeddings client
- **WHEN** the mock is called
- **THEN** it is called with `task_type="RETRIEVAL_DOCUMENT"` and `output_dimensionality=768`
