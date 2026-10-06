"""app.py — FastAPI + Gradio Blocks application for the Autonomous Incident Triage Agent.

Start locally:
    uvicorn app:app --reload --port 8000

On Render (free web service):
    uvicorn app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import uuid

import gradio as gr
from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

from agent import get_agent_app  # noqa: E402 (after load_dotenv)

# ── FastAPI app ────────────────────────────────────────────────────────────────

api = FastAPI(
    title="Incident Triage Agent API",
    description="Autonomous incident triage powered by Gemini + LangGraph + Supabase.",
    version="1.0.0",
)


@api.get("/healthz", tags=["meta"])
def health() -> dict:
    """Liveness probe for Render."""
    return {"status": "ok"}


@api.post("/triage", tags=["agent"])
def triage(incident: dict) -> dict:
    """
    Run the triage agent on an incident description.

    Body: {"message": "the auth service is timing out"}
    Returns: {"response": "<agent reply>", "thread_id": "<uuid>"}
    """
    message = incident.get("message", "").strip()
    if not message:
        return {"error": "message field is required"}

    agent = get_agent_app()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"messages": [HumanMessage(content=message)]}, config)
    last = result["messages"][-1]
    return {"response": last.content, "thread_id": thread_id}


# ── Gradio UI ──────────────────────────────────────────────────────────────────

_agent_cache: dict = {}


def _get_agent():
    if "app" not in _agent_cache:
        _agent_cache["app"] = get_agent_app()
    return _agent_cache["app"]


def respond(message: str, history: list, thread_id: str):
    """Run the agent and append the response to chat history."""
    if not message.strip():
        return history, ""

    agent = _get_agent()
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"messages": [HumanMessage(content=message)]}, config)
    last = result["messages"][-1]
    reply = last.content if isinstance(last, AIMessage) else str(last.content)

    history = history or []
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    return history, ""


def new_session():
    new_tid = str(uuid.uuid4())
    return [], new_tid, new_tid


with gr.Blocks(title="Incident Triage Agent") as demo:
    thread_state = gr.State(str(uuid.uuid4()))

    gr.HTML(
        """
        <div style="text-align:center; padding: 1.5rem 0 0.5rem;">
            <h1 style="font-size:2rem; font-weight:700; color:#4f46e5; margin:0;">
                🚨 Incident Triage Agent
            </h1>
            <p style="color:#64748b; margin-top:0.5rem;">
                Describe an incident in plain English — the agent will inspect service health,
                search remediation runbooks, and tell you what to do.
            </p>
        </div>
        """
    )

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                label="Triage Session",
                height=480,
                layout="bubble",
            )
            with gr.Row():
                msg_box = gr.Textbox(
                    placeholder='e.g. "the auth service is timing out with 504 errors"',
                    show_label=False,
                    scale=5,
                    container=False,
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)
            new_btn = gr.Button("🔄 New Session", variant="secondary", size="sm")

        with gr.Column(scale=1):
            gr.Markdown("### 💡 Example Incidents")
            gr.Examples(
                examples=[
                    ["the auth service is timing out with 504 errors"],
                    ["database queries are taking more than 5 seconds"],
                    ["payment transactions are failing with 502 responses"],
                ],
                inputs=msg_box,
            )
            gr.Markdown("---")
            gr.Markdown("### 🧵 Session Thread")
            thread_display = gr.Textbox(
                value=thread_state.value,
                label="Thread ID",
                interactive=False,
                elem_classes=["thread-box"],
            )

    send_btn.click(respond, [msg_box, chatbot, thread_state], [chatbot, msg_box])
    msg_box.submit(respond, [msg_box, chatbot, thread_state], [chatbot, msg_box])
    new_btn.click(new_session, outputs=[chatbot, thread_state, thread_display])
    thread_state.change(lambda t: t, thread_state, thread_display)


# ── Mount Gradio on FastAPI ────────────────────────────────────────────────────

app = gr.mount_gradio_app(api, demo, path="/")
