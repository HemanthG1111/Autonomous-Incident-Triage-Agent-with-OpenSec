"""agent.py — Core Autonomous Incident Triage Agent with safe read-only tools."""

from __future__ import annotations

import os
from typing import Annotated, Any, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    SystemMessage,
)
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from psycopg_pool import ConnectionPool

load_dotenv()

# Constants
EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768
DEFAULT_CHAT_MODEL = "gemini-1.5-flash"

SERVICES_HEALTH: dict[str, str] = {
    "auth": "Status: DEGRADED. Error rate: 14.2% (HTTP 504). Redis session store latency: 4200ms. CPU: 45%.",
    "database": "Status: HEALTHY. Active connections: 42/100. P95 latency: 12ms. Disk I/O: 18%.",
    "payments": "Status: HEALTHY. Success rate: 99.8%. Webhook queue depth: 12. P95 latency: 180ms.",
}

SYSTEM_PROMPT = (
    "You are an autonomous incident triage agent. When an incident is reported, you must "
    "ALWAYS inspect service health using `query_service_health` before searching for remediation "
    "runbooks using `search_remediation_runbooks`. Synthesize your findings and provide clear "
    "diagnostic and remediation recommendations."
)


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

    # Embed query
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


# ── LangGraph Agent ───────────────────────────────────────────────────────────

SAFE_TOOLS = [query_service_health, search_remediation_runbooks]


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def route_tools(state: AgentState) -> str:
    """Route to safe_tools if tool calls are present, otherwise END."""
    messages = state["messages"]
    if not messages:
        return END
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "safe_tools"
    return END


def create_agent_graph(
    llm: Any = None,
    tools: Sequence[Any] | None = None,
    checkpointer: Any = None,
):
    """Build and compile the LangGraph agent state graph."""
    if tools is None:
        tools = SAFE_TOOLS

    if llm is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        base_llm = ChatGoogleGenerativeAI(
            model=DEFAULT_CHAT_MODEL,
            google_api_key=api_key,
            temperature=0.0,
        )
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
    builder.add_node("safe_tools", ToolNode(tools))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        route_tools,
        {"safe_tools": "safe_tools", END: END},
    )
    builder.add_edge("safe_tools", "agent")

    return builder.compile(checkpointer=checkpointer)


def get_agent_app(
    pool: ConnectionPool | None = None,
    checkpointer: Any = None,
    llm: Any = None,
):
    """Return the compiled LangGraph application with PostgresSaver checkpointer."""
    if checkpointer is None:
        if pool is None:
            pool = get_connection_pool()
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()

    return create_agent_graph(llm=llm, checkpointer=checkpointer)
