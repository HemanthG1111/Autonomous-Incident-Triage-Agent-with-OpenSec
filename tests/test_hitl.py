"""tests/test_hitl.py — Tests for HITL escalation pause / approve / reject paths.

All tests mock the LLM and the database; no real Gemini or Supabase calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from agent import (
    SENSITIVE_TOOL_NAMES,
    AgentState,
    approve_escalation,
    create_agent_graph,
    get_pending_escalation,
    reject_escalation,
    route_tools,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_escalate_ai_message() -> AIMessage:
    """AIMessage that calls escalate_ticket."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_esc_001",
                "name": "escalate_ticket",
                "args": {"ticket_title": "Auth degraded", "severity": "high"},
                "type": "tool_call",
            }
        ],
    )


def _make_safe_ai_message() -> AIMessage:
    """AIMessage that calls only safe tools."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_safe_001",
                "name": "query_service_health",
                "args": {"service": "auth"},
                "type": "tool_call",
            }
        ],
    )


def _make_final_ai_message(content: str = "Triage complete.") -> AIMessage:
    """AIMessage with no tool calls (final response)."""
    return AIMessage(content=content)


# ── route_tools ────────────────────────────────────────────────────────────────


def test_route_tools_sensitive():
    state: AgentState = {"messages": [_make_escalate_ai_message()]}
    assert route_tools(state) == "sensitive_tools"


def test_route_tools_safe():
    state: AgentState = {"messages": [_make_safe_ai_message()]}
    assert route_tools(state) == "safe_tools"


def test_route_tools_no_calls():
    state: AgentState = {"messages": [_make_final_ai_message()]}
    from langgraph.graph import END
    assert route_tools(state) == END


def test_route_tools_mixed_any_sensitive_routes_to_sensitive():
    """If ANY tool call in a message is sensitive, the whole message goes to sensitive_tools."""
    msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "query_service_health", "args": {"service": "auth"}, "type": "tool_call"},
            {"id": "c2", "name": "escalate_ticket", "args": {"ticket_title": "T", "severity": "high"}, "type": "tool_call"},
        ],
    )
    state: AgentState = {"messages": [msg]}
    assert route_tools(state) == "sensitive_tools"


# ── Pause / approve / reject using MemorySaver ────────────────────────────────


def _build_graph_with_mock_llm(llm_responses: list):
    """Build a graph with MemorySaver checkpointer and a scripted mock LLM."""
    call_count = {"n": 0}

    def fake_invoke(messages):
        idx = min(call_count["n"], len(llm_responses) - 1)
        call_count["n"] += 1
        return llm_responses[idx]

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.invoke = MagicMock(side_effect=fake_invoke)
    mock_llm._mock_return_value = True  # triggers the mock branch in create_agent_graph

    checkpointer = MemorySaver()
    graph = create_agent_graph(llm=mock_llm, checkpointer=checkpointer)
    return graph, checkpointer


def test_escalation_pauses():
    """Graph must stop before sensitive_tools when model calls escalate_ticket."""
    llm_responses = [_make_escalate_ai_message()]
    graph, _ = _build_graph_with_mock_llm(llm_responses)

    config = {"configurable": {"thread_id": "t-pause-001"}}
    result = graph.invoke({"messages": [HumanMessage(content="Auth is down, escalate.")]}, config)

    # Graph paused — last message is the AIMessage with the tool call, not a ToolMessage or final reply
    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert any(tc["name"] == "escalate_ticket" for tc in last.tool_calls)


def test_escalation_approved_executes():
    """After approval (invoke with None), escalate_ticket runs and agent gets its result."""
    llm_responses = [
        _make_escalate_ai_message(),   # first: model calls escalate_ticket
        _make_final_ai_message("Ticket created. Escalation complete."),  # after tool result
    ]
    graph, _ = _build_graph_with_mock_llm(llm_responses)

    config = {"configurable": {"thread_id": "t-approve-001"}}
    # First invoke — will pause
    graph.invoke({"messages": [HumanMessage(content="Auth is down, escalate.")]}, config)

    # Resume (approve)
    result = graph.invoke(None, config)
    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert not last.tool_calls  # final response, no more calls
    assert "Ticket" in last.content or "complete" in last.content.lower()


def test_escalation_rejected_injects_tool_message():
    """On rejection, a ToolMessage with rejection reason is injected; tool never executes."""
    llm_responses = [
        _make_escalate_ai_message(),
        _make_final_ai_message("Understood. No escalation. Continuing investigation."),
    ]
    graph, _ = _build_graph_with_mock_llm(llm_responses)

    config = {"configurable": {"thread_id": "t-reject-001"}}
    # Pause
    state_before = graph.invoke({"messages": [HumanMessage(content="Escalate!")], }, config)

    # Inject rejection
    last_ai = state_before["messages"][-1]
    tc_id = last_ai.tool_calls[0]["id"]
    rejection_msg = ToolMessage(
        content="Rejected by engineer: not yet confirmed degraded",
        tool_call_id=tc_id,
    )
    graph.update_state(config, {"messages": [rejection_msg]}, as_node="sensitive_tools")

    # Resume
    result = graph.invoke(None, config)
    last = result["messages"][-1]
    # The tool message should be in the history
    all_messages = result["messages"]
    tool_msgs = [m for m in all_messages if isinstance(m, ToolMessage)]
    assert any("Rejected" in (m.content or "") for m in tool_msgs)
    assert isinstance(last, AIMessage)


def test_get_pending_escalation_returns_details():
    """get_pending_escalation returns tool_name and parameters when thread is paused."""
    llm_responses = [_make_escalate_ai_message()]
    graph, checkpointer = _build_graph_with_mock_llm(llm_responses)

    config = {"configurable": {"thread_id": "t-pending-001"}}
    graph.invoke({"messages": [HumanMessage(content="Escalate!")]}, config)

    # Inspect state directly
    state = graph.get_state(config)
    last = state.values["messages"][-1]
    assert isinstance(last, AIMessage)
    assert last.tool_calls
    pending = None
    for tc in last.tool_calls:
        if tc["name"] in SENSITIVE_TOOL_NAMES:
            pending = {"tool_name": tc["name"], "parameters": tc["args"], "tool_call_id": tc["id"]}
    assert pending is not None
    assert pending["tool_name"] == "escalate_ticket"
    assert "ticket_title" in pending["parameters"]


def test_no_pending_escalation_after_completion():
    """After a completed (non-escalating) run, no pending escalation exists."""
    llm_responses = [_make_final_ai_message("Auth looks healthy.")]
    graph, _ = _build_graph_with_mock_llm(llm_responses)

    config = {"configurable": {"thread_id": "t-nopending-001"}}
    graph.invoke({"messages": [HumanMessage(content="Check auth.")]}, config)

    state = graph.get_state(config)
    last = state.values["messages"][-1]
    # No tool calls on final message
    assert not (isinstance(last, AIMessage) and last.tool_calls)
