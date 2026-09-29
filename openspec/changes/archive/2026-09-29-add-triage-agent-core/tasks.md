# Tasks

## 1. Agent Tools and Helpers

- [x] 1.1 Implement `extract_text` in `agent.py` to normalise both string and list-structured LLM message content into a clean string, and verify with unit tests
- [x] 1.2 Implement `query_service_health(service: str)` tool with mock registry (`auth`, `database`, `payments`), returning health metrics for known services and a descriptive message for unknown services without raising
- [x] 1.3 Implement `search_remediation_runbooks(query: str)` tool using `GoogleGenerativeAIEmbeddings` with `task_type="RETRIEVAL_QUERY"` (768 dims) and psycopg pool calling `match_incident_docs` to return at most the top 2 matching runbooks

## 2. LangGraph StateGraph & Checkpointer

- [x] 2.1 Define `AgentState` schema using `Annotated[list[AnyMessage], add_messages]` and system prompt instructing the agent to always inspect service health first before searching runbooks
- [x] 2.2 Construct the LangGraph workflow (`agent` -> `safe_tools` -> `agent` loop, routing to `END` when no tool calls are present)
- [x] 2.3 Implement connection pool configuration with `kwargs={"prepare_threshold": None}`, `max_size=10`, `autocommit=True`, and `PostgresSaver` checkpointer setup in `get_agent_app()`

## 3. Unit Tests

- [x] 3.1 Create `tests/test_agent.py` with offline unit tests mocking Gemini LLM tool calls to verify: (a) health-first tool routing, (b) unknown service handling, (c) runbook retrieval limiting to top 2 results, (d) `extract_text` normalisation — verify with `pytest -q tests/test_agent.py`
- [x] 3.2 Add state persistence test verifying that an existing `thread_id` preserves conversation history across separate graph invocations — verify with `pytest -q tests/test_agent.py`
