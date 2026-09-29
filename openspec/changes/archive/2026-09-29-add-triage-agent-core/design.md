# Design

## Context

See `proposal.md` for motivation. The knowledge base and database migration (`001_incident_docs.sql`) are already established. The agent needs to query service health, perform semantic searches against `incident_docs`, and maintain conversation state across invocations using PostgresSaver over the Supabase transaction pooler.

## Goals / Non-Goals

**Goals:**
- Construct a deterministic LangGraph workflow: `agent` -> `safe_tools` -> `agent` -> `END`.
- Implement safe read-only tools: `query_service_health` and `search_remediation_runbooks`.
- Provide persistent conversation state keyed by `thread_id` using `PostgresSaver`.
- Normalise model output via `extract_text` to handle multi-part content structures.

**Non-Goals:**
- Escalation or write operations (deliberately deferred to Change 3: `add-hitl-escalation`).
- REST API and UI integration (deferred to Change 4).

## Decisions

### Decision 1: LangGraph StateGraph Architecture
- **Choice**: Explicit `StateGraph(AgentState)` with conditional routing on tool calls.
- **Rationale**: Provides granular control over node transitions and checkpointing, which is critical when adding human-in-the-loop interrupts in subsequent changes.
- **Alternatives Considered**: LangChain prebuilt ReAct agent (`create_react_agent`). Rejected because customizing checkpointing and node-level interrupts is more brittle with prebuilt agents.

### Decision 2: Supabase Pooler Configuration (`prepare_threshold=None`)
- **Choice**: Use `psycopg_pool.ConnectionPool` with `kwargs={"prepare_threshold": None}`, `autocommit=True`, `max_size=10`, and `connect_timeout=15`.
- **Rationale**: Supabase uses PgBouncer in transaction mode on port 6543. Prepared statements across pooled transactions cause `prepared statement does not exist` or `already exists` errors unless prepared statement caching is disabled with `prepare_threshold=None`.
- **Alternatives Considered**: Direct connection on port 5432. Rejected because free-tier Supabase instances have very low max connection limits (typically 20-30 connections) which can quickly be exhausted.

### Decision 3: Embeddings Task Type for Search
- **Choice**: Use `task_type="RETRIEVAL_QUERY"` for the agent's runbook search queries, whereas `RETRIEVAL_DOCUMENT` was used during seeding.
- **Rationale**: Gemini embedding models optimize vector representations differently for documents vs query intents.
- **Alternatives Considered**: Reusing `RETRIEVAL_DOCUMENT` for queries. Rejected as it degrades cosine similarity search quality.

### Decision 4: Content Normalisation Helper (`extract_text`)
- **Choice**: A dedicated helper function `extract_text(content: str | list[Any]) -> str` that concatenates string parts and dictionary text attributes.
- **Rationale**: Gemini models via `langchain-google-genai` can return content as either a plain string or a list of text/dict blocks. Normalising at the agent boundary guarantees consistent strings for consumers.

## Risks / Trade-offs

- **[Gemini Free Tier Rate Limits (15 RPM)]** → Keep the prompt structured so the agent completes triage in 1-2 tool calls (service health check + runbook search), avoiding excessive LLM loop iterations.
- **[Postgres Connection Cold Starts]** → Set `connect_timeout=15` in `psycopg_pool` to handle brief network latency or container spin-up delays on Supabase.
- **[Checkpointer Schema Initialization]** → Call `checkpointer.setup()` within `get_agent_app()` to ensure `checkpoints` tables are automatically created on first startup if they do not yet exist.
