"""tests/test_agent.py — Unit tests for agent.py.

All tests are offline and do not connect to real Gemini or Postgres.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver

import agent


# ── Test extract_text ─────────────────────────────────────────────────────────


class TestExtractText:
    """Verify normalisation of diverse content types."""

    def test_extract_text_plain_string(self):
        assert agent.extract_text("Hello world") == "Hello world"

    def test_extract_text_list_of_strings(self):
        assert agent.extract_text(["Hello", "world"]) == "Hello world"

    def test_extract_text_list_of_dicts(self):
        content = [{"type": "text", "text": "Part 1"}, {"type": "text", "text": "Part 2"}]
        assert agent.extract_text(content) == "Part 1 Part 2"

    def test_extract_text_mixed_list(self):
        content = ["Leading text", {"text": "middle text"}, 123]
        assert agent.extract_text(content) == "Leading text middle text 123"


# ── Test Safe Tools ───────────────────────────────────────────────────────────


class TestSafeTools:
    """Verify query_service_health and search_remediation_runbooks behaviors."""

    def test_query_service_health_known_service(self):
        result = agent.query_service_health.invoke({"service": "auth"})
        assert "AUTH SERVICE HEALTH" in result
        assert "DEGRADED" in result
        assert "504" in result

    def test_query_service_health_case_insensitive(self):
        result = agent.query_service_health.invoke({"service": "  Database  "})
        assert "DATABASE SERVICE HEALTH" in result
        assert "HEALTHY" in result

    def test_query_service_health_unknown_service(self):
        """Spec: query_service_health('billing') returns not-found message rather than raising."""
        result = agent.query_service_health.invoke({"service": "billing"})
        assert "Service 'billing' not found" in result
        assert "Available services: auth, database, payments" in result

    def test_search_remediation_runbooks_returns_top_matches(self):
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1] * agent.EMBEDDING_DIM

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            (1, "Runbook 1 content", {"service": "auth"}, 0.95),
            (2, "Runbook 2 content", {"service": "auth"}, 0.88),
        ]
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection.return_value = mock_conn

        res = agent.search_runbooks_in_db(
            "auth timeout",
            pool=mock_pool,
            embeddings_client=mock_emb,
            match_count=2,
        )
        assert "Runbook 1 content" in res
        assert "Runbook 2 content" in res
        assert mock_cur.execute.called

    def test_search_remediation_runbooks_no_results(self):
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1] * agent.EMBEDDING_DIM

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connection.return_value = mock_conn

        res = agent.search_runbooks_in_db(
            "unknown issue",
            pool=mock_pool,
            embeddings_client=mock_emb,
        )
        assert res == "No relevant runbooks found."


# ── Test Routing & Agent Graph ────────────────────────────────────────────────


class TestAgentGraph:
    """Verify tool routing, graph execution, and state persistence."""

    def test_route_tools_with_tool_call(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "query_service_health", "args": {"service": "auth"}, "id": "tc1"}],
        )
        state: agent.AgentState = {"messages": [msg]}
        assert agent.route_tools(state) == "safe_tools"

    def test_route_tools_without_tool_call(self):
        msg = AIMessage(content="All services are operating normally.")
        state: agent.AgentState = {"messages": [msg]}
        assert agent.route_tools(state) == agent.END

    def test_agent_graph_invokes_health_first_and_returns_final(self):
        """Mock LLM to emit tool call, receive tool result, and output final response."""
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        # Step 1: Model issues tool call
        tool_call_msg = AIMessage(
            content="",
            tool_calls=[{"name": "query_service_health", "args": {"service": "auth"}, "id": "tc-101"}],
        )
        # Step 2: After tool execution, model produces final response
        final_msg = AIMessage(content="Auth service is currently degraded due to Redis timeouts.")

        mock_llm.invoke.side_effect = [tool_call_msg, final_msg]

        checkpointer = MemorySaver()
        app = agent.create_agent_graph(llm=mock_llm, checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "test-thread-triage"}}
        result = app.invoke(
            {"messages": [HumanMessage(content="Auth service is returning 504 errors")]},
            config=config,
        )

        messages = result["messages"]
        # Must have: HumanMessage, AIMessage (tool call), ToolMessage, AIMessage (final)
        assert len(messages) >= 4
        assert any(isinstance(m, ToolMessage) and "DEGRADED" in m.content for m in messages)
        assert messages[-1].content == "Auth service is currently degraded due to Redis timeouts."

    def test_state_persistence_across_separate_invocations(self):
        """Given a thread_id, subsequent invocations retain conversation state."""
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(content="First response"),
            AIMessage(content="Second response"),
        ]

        checkpointer = MemorySaver()
        app = agent.create_agent_graph(llm=mock_llm, checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "thread-persistence-123"}}

        app.invoke({"messages": [HumanMessage(content="Message one")]}, config=config)
        state_after_first = app.get_state(config)
        assert len(state_after_first.values["messages"]) == 2

        app.invoke({"messages": [HumanMessage(content="Message two")]}, config=config)
        state_after_second = app.get_state(config)
        assert len(state_after_second.values["messages"]) == 4
