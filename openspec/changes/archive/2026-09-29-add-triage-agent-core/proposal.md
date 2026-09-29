# Proposal

## Why

The incident triage agent needs a core reasoning engine to inspect service health and retrieve relevant remediation runbooks when an incident is reported. Building the safe (read-only) execution loop first establishes the state graph, tool invocation, and persistent memory foundations before introducing sensitive write actions like ticket escalation.

## What Changes

- Implement `agent.py` containing the core LangGraph agent with a safe read-only tool loop.
- Configure a `psycopg_pool.ConnectionPool` with `max_size=10`, `autocommit=True`, `connect_timeout=15`, and `prepare_threshold=None` for Supabase compatibility.
- Implement read-only tools:
  - `query_service_health(service: str)`: checks mock service table (`auth`, `database`, `payments`).
  - `search_remediation_runbooks(query: str)`: queries `incident_docs` using vector similarity with `task_type="RETRIEVAL_QUERY"`, returning top 2 runbooks.
- Define `AgentState` with `messages: Annotated[list[AnyMessage], add_messages]`.
- System prompt instructing the model to always inspect service health first, then search runbooks.
- `extract_text(content)` helper to flatten list-structured Gemini output to a clean string.
- LangGraph architecture: `agent` -> `safe_tools` -> `agent` loop, routing to `END` when no tool calls are present.
- State persistence using LangGraph `PostgresSaver` backed by psycopg pool, initialized with `.setup()`.
- Export `get_agent_app()` to compile and return the runnable graph.
- Exclude `escalate_ticket` deliberately until Change 3.
- Unit tests in `tests/test_agent.py` with mocked Gemini LLM verifying tool call routing and state persistence by `thread_id`.

## Capabilities

### New Capabilities
- `triage-agent`: Autonomous reasoning loop that checks service health, retrieves runbooks from vector storage, normalises model output, and preserves conversation state across executions.

### Modified Capabilities
None.

## Impact

- **Affected Code**: Creates `agent.py` and `tests/test_agent.py`.
- **Dependencies**: Uses `langgraph`, `langgraph-checkpoint-postgres`, `langchain-google-genai`, `langchain-core`, and `psycopg-pool`.
- **Database**: Reads from `incident_docs` table and creates checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) via `PostgresSaver.setup()`.
- **Rollback Note**: In the event of a rollback, `agent.py` and `tests/test_agent.py` can be removed; checkpointer tables in Postgres are harmless and can be retained or dropped with `DROP TABLE IF EXISTS checkpoints, checkpoint_blobs, checkpoint_writes;`.
