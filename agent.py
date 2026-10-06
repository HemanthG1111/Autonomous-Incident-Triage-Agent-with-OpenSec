"""agent.py — Autonomous Incident Triage Agent with HITL escalation gate.

Safe tools run without interruption.
Sensitive tools (escalate_ticket) are gated behind a human-approval interrupt.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from psycopg_pool import ConnectionPool

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768
DEFAULT_CHAT_MODEL = "gemini-3.5-flash-lite"

SERVICES_HEALTH: dict[str, str] = {
    "auth": "Status: DEGRADED. Error rate: 14.2% (HTTP 504). Redis session store latency: 4200ms. CPU: 45%.",
    "database": "Status: HEALTHY. Active connections: 42/100. P95 latency: 12ms. Disk I/O: 18%.",
    "payments": "Status: HEALTHY. Success rate: 99.8%. Webhook queue depth: 12. P95 latency: 180ms.",
}

SYSTEM_PROMPT = (
    "You are an autonomous incident triage agent. When an incident is reported, you must "
    "ALWAYS inspect service health using `query_service_health` before searching for remediation "
    "runbooks using `search_remediation_runbooks`. Synthesize your findings and provide clear "
    "diagnostic and remediation recommendations. "
    "If manual intervention is required or a service remains DEGRADED after runbook steps, "
    "you MUST call `escalate_ticket` to open a support ticket — but this will require "
    "engineer approval before it executes."
)

SENSITIVE_TOOL_NAMES: set[str] = {"escalate_ticket"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def extract_text(content: Any) -> str:
    """Normalise string or list-structured LLM message content into a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", part)))
            else:
                parts.append(str(part))
        return " ".join(parts)
    return str(content)


# ── Tools ─────────────────────────────────────────────────────────────────────


@tool
def query_service_health(service: str) -> str:
    """Check the real-time health and diagnostic metrics for a specific service (e.g. 'auth', 'database', 'payments')."""
    key = service.strip().lower()
    if key in SERVICES_HEALTH:
        return f"[{key.upper()} SERVICE HEALTH]\n{SERVICES_HEALTH[key]}"
    available = ", ".join(SERVICES_HEALTH.keys())
    return f"Service '{service}' not found. Available services: {available}"


_global_pool: ConnectionPool | None = None


def get_connection_pool(database_url: str | None = None) -> ConnectionPool:
    """Return a shared ConnectionPool configured for Supabase transaction pooler."""
    global _global_pool
    if _global_pool is None:
        import atexit
        url = database_url or os.environ.get("DATABASE_URL", "")
        pool_kwargs = {
            "prepare_threshold": None,  # Required for Supabase transaction pooler
            "autocommit": True,
            "connect_timeout": 15,
        }
        _global_pool = ConnectionPool(
            url,
            min_size=1,
            max_size=10,
            kwargs=pool_kwargs,
        )
        atexit.register(_global_pool.close)
    return _global_pool


def search_runbooks_in_db(
    query: str,
    pool: ConnectionPool | None = None,
    embeddings_client: GoogleGenerativeAIEmbeddings | None = None,
    match_count: int = 2,
) -> str:
    """Execute vector similarity search against incident_docs."""
    if embeddings_client is None:
        embeddings_client = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=os.environ.get("GEMINI_API_KEY", ""),
            task_type="RETRIEVAL_QUERY",
        )

    query_vector = embeddings_client.embed_query(query, output_dimensionality=EMBEDDING_DIM)

    if pool is None:
        pool = get_connection_pool()

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content, metadata, 1 - (embedding <=> %s::vector) AS similarity "
                "FROM incident_docs "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (query_vector, query_vector, match_count),
            )
            rows = cur.fetchall()

    if not rows:
        return "No relevant runbooks found."

    results: list[str] = []
    for row in rows:
        content = row[1]
        results.append(content.strip())
    return "\n\n---\n\n".join(results)


@tool
def search_remediation_runbooks(query: str) -> str:
    """Search the runbook knowledge base using semantic vector search for remediation procedures."""
    return search_runbooks_in_db(query)


@tool
def escalate_ticket(ticket_title: str, severity: str) -> str:
    """
    SENSITIVE: Open a support ticket and page the on-call team.
    Requires engineer approval before execution.
    severity should be one of: low, medium, high, critical.
    """
    ticket_id = f"INC-{abs(hash(ticket_title)) % 10000:04d}"
    return (
        f"Ticket {ticket_id} created: '{ticket_title}' (severity={severity}). "
        "On-call team has been paged."
    )


# ── LangGraph Agent ───────────────────────────────────────────────────────────

SAFE_TOOLS = [query_service_health, search_remediation_runbooks]
SENSITIVE_TOOLS = [escalate_ticket]
ALL_TOOLS = SAFE_TOOLS + SENSITIVE_TOOLS


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def route_tools(state: AgentState) -> str:
    """Route to sensitive_tools if any call is sensitive, safe_tools otherwise, or END."""
    messages = state["messages"]
    if not messages:
        return END
    last_message = messages[-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return END
    # If ANY tool call is sensitive, route to sensitive_tools (requires approval)
    for tc in last_message.tool_calls:
        if tc["name"] in SENSITIVE_TOOL_NAMES:
            return "sensitive_tools"
    return "safe_tools"


def create_agent_graph(
    llm: Any = None,
    tools: Sequence[Any] | None = None,
    checkpointer: Any = None,
    interrupt_before_sensitive: bool = True,
):
    """Build and compile the LangGraph agent state graph with HITL interrupt."""
    if tools is None:
        tools = ALL_TOOLS

    if llm is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        primary_llm = ChatGoogleGenerativeAI(
            model=DEFAULT_CHAT_MODEL,
            google_api_key=api_key,
            temperature=0.0,
            timeout=30,
            max_retries=1,
        )
        fallback_llm = ChatGoogleGenerativeAI(
            model="gemini-flash-lite-latest",
            google_api_key=api_key,
            temperature=0.0,
            timeout=30,
            max_retries=1,
        )
        base_llm = primary_llm.with_fallbacks([fallback_llm])
        model = base_llm.bind_tools(tools)
    elif hasattr(llm, "bind_tools") and not hasattr(llm, "_mock_return_value"):
        model = llm.bind_tools(tools)
    else:
        model = llm

    def agent_node(state: AgentState) -> dict[str, list[AnyMessage]]:
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        response = model.invoke(messages)
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("safe_tools", ToolNode(SAFE_TOOLS))
    builder.add_node("sensitive_tools", ToolNode(SENSITIVE_TOOLS))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        route_tools,
        {"safe_tools": "safe_tools", "sensitive_tools": "sensitive_tools", END: END},
    )
    builder.add_edge("safe_tools", "agent")
    builder.add_edge("sensitive_tools", "agent")

    interrupt_nodes = ["sensitive_tools"] if interrupt_before_sensitive else []
    return builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_nodes)


def get_agent_app(
    pool: ConnectionPool | None = None,
    checkpointer: Any = None,
    llm: Any = None,
    interrupt_before_sensitive: bool = True,
):
    """Return the compiled LangGraph application with PostgresSaver checkpointer."""
    if checkpointer is None:
        if pool is None:
            pool = get_connection_pool()
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()

    return create_agent_graph(
        llm=llm,
        checkpointer=checkpointer,
        interrupt_before_sensitive=interrupt_before_sensitive,
    )


# ── HITL helpers ──────────────────────────────────────────────────────────────


def get_pending_escalation(
    thread_id: str,
    pool: ConnectionPool | None = None,
) -> dict | None:
    """
    Return pending sensitive tool call details for a paused thread, or None.

    Returns: {"tool_name": str, "parameters": dict, "tool_call_id": str} or None.
    """
    app = get_agent_app(pool=pool)
    config = {"configurable": {"thread_id": thread_id}}
    state = app.get_state(config)
    if state is None or not state.values.get("messages"):
        return None
    last = state.values["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return None
    for tc in last.tool_calls:
        if tc["name"] in SENSITIVE_TOOL_NAMES:
            return {
                "tool_name": tc["name"],
                "parameters": tc["args"],
                "tool_call_id": tc["id"],
            }
    return None


def approve_escalation(
    thread_id: str,
    pool: ConnectionPool | None = None,
) -> dict:
    """Resume a paused thread, allowing the sensitive tool to execute."""
    app = get_agent_app(pool=pool)
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(None, config)
    last = result["messages"][-1]
    return {"status": "RESOLVED", "response": extract_text(last.content)}


def reject_escalation(
    thread_id: str,
    reason: str,
    pool: ConnectionPool | None = None,
) -> dict:
    """
    Inject a rejection ToolMessage for every pending sensitive call, then resume.
    The agent receives the rejection reason and can continue reasoning.
    """
    app = get_agent_app(pool=pool)
    config = {"configurable": {"thread_id": thread_id}}
    state = app.get_state(config)

    if state is None or not state.values.get("messages"):
        return {"status": "ERROR", "response": "No state found for thread."}

    last = state.values["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {"status": "ERROR", "response": "No pending tool calls."}

    # Inject a ToolMessage rejection for every sensitive pending call
    rejection_messages = []
    for tc in last.tool_calls:
        if tc["name"] in SENSITIVE_TOOL_NAMES:
            rejection_messages.append(
                ToolMessage(
                    content=f"Rejected by engineer: {reason}",
                    tool_call_id=tc["id"],
                )
            )

    if not rejection_messages:
        return {"status": "ERROR", "response": "No sensitive tool calls found."}

    app.update_state(config, {"messages": rejection_messages}, as_node="sensitive_tools")
    result = app.invoke(None, config)
    last_msg = result["messages"][-1]
    return {"status": "REJECTED_AND_RESUMED", "response": extract_text(last_msg.content)}

