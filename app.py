"""app.py — FastAPI + Gradio Blocks application for Autonomous Incident Triage Agent.

Features:
- REST API: /healthz, /chat, /approve, /reject
- Gradio UI: Thread ID, Incident Description, Trigger Triage, Approve/Reject HITL controls,
             Workflow State badge, Agent Log markdown.
- Shared service layer between FastAPI and Gradio.
"""

from __future__ import annotations

import uuid
from typing import Optional

import gradio as gr
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

from agent import (  # noqa: E402
    approve_escalation,
    extract_text,
    get_agent_app,
    get_pending_escalation,
    reject_escalation,
)
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

# ── Service Layer ──────────────────────────────────────────────────────────────


def service_chat(thread_id: str | None, message: str) -> dict:
    """Run triage agent and return structured state."""
    tid = thread_id.strip() if thread_id and thread_id.strip() else str(uuid.uuid4())
    msg = message.strip() if message else ""
    if not msg:
        return {"status": "ERROR", "thread_id": tid, "response": "Incident description cannot be empty."}

    agent = get_agent_app()
    config = {"configurable": {"thread_id": tid}}

    try:
        result = agent.invoke({"messages": [HumanMessage(content=msg)]}, config)
    except Exception as e:
        return {
            "status": "ERROR",
            "thread_id": tid,
            "response": f"⚠️ Error invoking triage agent: {type(e).__name__} - {str(e)}",
        }

    # Check if LangGraph paused before a sensitive tool
    pending = get_pending_escalation(tid)
    if pending:
        return {
            "status": "AWAITING_APPROVAL",
            "thread_id": tid,
            "pending_action": pending["tool_name"],
            "parameters": pending["parameters"],
            "response": (
                "⚠️ **Human Approval Required**\n\n"
                f"The agent determined that an escalation is necessary:\n"
                f"- **Tool**: `{pending['tool_name']}`\n"
                f"- **Title**: `{pending['parameters'].get('ticket_title', 'N/A')}`\n"
                f"- **Severity**: `{pending['parameters'].get('severity', 'N/A')}`\n\n"
                "Please review and click **Approve Escalation** or enter a reason and click **Reject Action**."
            ),
        }

    last = result["messages"][-1]
    reply = extract_text(last.content if isinstance(last, AIMessage) else last.content)
    return {
        "status": "COMPLETED",
        "thread_id": tid,
        "response": reply,
    }


def service_approve(thread_id: str) -> dict | None:
    """Approve pending escalation and resume execution."""
    tid = thread_id.strip() if thread_id else ""
    if not tid:
        return None

    pending = get_pending_escalation(tid)
    if not pending:
        return None

    res = approve_escalation(tid)
    return {
        "status": res.get("status", "RESOLVED"),
        "thread_id": tid,
        "response": res.get("response", "Escalation approved and executed."),
    }


def service_reject(thread_id: str, reason: str = "Rejected by engineer") -> dict | None:
    """Reject pending escalation, inject reason, and resume execution."""
    tid = thread_id.strip() if thread_id else ""
    if not tid:
        return None

    pending = get_pending_escalation(tid)
    if not pending:
        return None

    clean_reason = reason.strip() if reason and reason.strip() else "Rejected by engineer"
    res = reject_escalation(tid, reason=clean_reason)
    return {
        "status": res.get("status", "REJECTED_AND_RESUMED"),
        "thread_id": tid,
        "response": res.get("response", "Escalation rejected. Agent continued investigation."),
    }


# ── FastAPI Models & Endpoints ─────────────────────────────────────────────────


class ChatRequest(BaseModel):
    thread_id: Optional[str] = Field(None, description="Session thread ID (auto-generated if omitted)")
    message: str = Field(..., description="Incident description")


class ApproveRequest(BaseModel):
    thread_id: str = Field(..., description="Session thread ID")
    approved: bool = Field(True, description="True to approve, False to reject")
    rejection_reason: Optional[str] = Field(None, description="Reason if rejecting")


class RejectRequest(BaseModel):
    thread_id: str = Field(..., description="Session thread ID")
    reason: str = Field("Rejected by engineer", description="Rejection reason")


api = FastAPI(
    title="Autonomous Incident Triage Agent API",
    description="Spec-driven Incident Triage Agent with LangGraph, pgvector RAG, and HITL approval.",
    version="1.0.0",
)


@api.get("/healthz", tags=["meta"])
def health() -> dict:
    """Liveness probe for Render / container health checks."""
    return {"status": "ok"}


@api.post("/chat", tags=["agent"])
def chat(req: ChatRequest) -> dict:
    """Trigger incident triage investigation."""
    res = service_chat(req.thread_id, req.message)
    if res.get("status") == "ERROR" and "Incident description" in res.get("response", ""):
        raise HTTPException(status_code=400, detail="Incident message cannot be empty.")
    return res


@api.post("/approve", tags=["hitl"])
def approve(req: ApproveRequest) -> dict:
    """Approve or reject a pending escalation."""
    if req.approved:
        res = service_approve(req.thread_id)
        if res is None:
            raise HTTPException(status_code=400, detail="No pending escalation for thread.")
        return res
    else:
        reason = req.rejection_reason or "Rejected by engineer"
        res = service_reject(req.thread_id, reason=reason)
        if res is None:
            raise HTTPException(status_code=400, detail="No pending escalation for thread.")
        return res


@api.post("/reject", tags=["hitl"])
def reject(req: RejectRequest) -> dict:
    """Reject a pending escalation with a reason."""
    res = service_reject(req.thread_id, reason=req.reason)
    if res is None:
        raise HTTPException(status_code=400, detail="No pending escalation for thread.")
    return res


# ── Gradio UI ──────────────────────────────────────────────────────────────────


def ui_trigger_triage(thread_id: str, message: str):
    """Handle Trigger Triage button click."""
    tid = thread_id.strip() if thread_id and thread_id.strip() else str(uuid.uuid4())
    res = service_chat(tid, message)
    state = res.get("status", "IDLE")
    output = res.get("response", "")

    pending_info = ""
    if state == "AWAITING_APPROVAL":
        pending_info = (
            f"**Action:** `{res.get('pending_action')}` | "
            f"**Title:** `{res.get('parameters', {}).get('ticket_title')}` | "
            f"**Severity:** `{res.get('parameters', {}).get('severity')}`"
        )

    return (
        tid,             # thread_id_box
        state,           # state_label
        output,          # agent_log
        pending_info,    # pending_box
        gr.update(interactive=(state == "AWAITING_APPROVAL")),  # approve_btn
        gr.update(interactive=(state == "AWAITING_APPROVAL")),  # reject_btn
    )


def ui_approve(thread_id: str):
    """Handle Approve Escalation button click."""
    res = service_approve(thread_id)
    if res is None:
        return (
            "ERROR",
            "⚠️ No pending escalation found for this thread.",
            "",
            gr.update(interactive=False),
            gr.update(interactive=False),
        )

    return (
        res.get("status", "RESOLVED"),
        res.get("response", ""),
        "✅ Escalation approved and ticket dispatched.",
        gr.update(interactive=False),
        gr.update(interactive=False),
    )


def ui_reject(thread_id: str, reason: str):
    """Handle Reject Action button click."""
    res = service_reject(thread_id, reason=reason)
    if res is None:
        return (
            "ERROR",
            "⚠️ No pending escalation found for this thread.",
            "",
            gr.update(interactive=False),
            gr.update(interactive=False),
        )

    return (
        res.get("status", "REJECTED_AND_RESUMED"),
        res.get("response", ""),
        f"❌ Escalation rejected: {reason}",
        gr.update(interactive=False),
        gr.update(interactive=False),
    )


def ui_new_session():
    """Reset session with a fresh thread ID."""
    new_tid = str(uuid.uuid4())
    return (
        new_tid,
        "",
        "IDLE",
        "Enter an incident description above and click **Trigger Triage** to start.",
        "",
        "",
        gr.update(interactive=False),
        gr.update(interactive=False),
    )


with gr.Blocks(title="Autonomous Incident Triage Agent", ) as demo:
    gr.HTML(
        """
        <div style="text-align: center; padding: 1.25rem 0 0.5rem;">
            <h1 style="font-size: 2.2rem; font-weight: 800; color: #4338ca; margin-bottom: 0.25rem;">
                🚨 Autonomous Incident Triage Agent
            </h1>
            <p style="color: #64748b; font-size: 1rem; max-width: 680px; margin: 0 auto;">
                Autonomous incident investigation with <strong>pgvector RAG</strong>, 
                <strong>LangGraph</strong>, and <strong>Human-in-the-Loop (HITL)</strong> escalation gating.
            </p>
        </div>
        """
    )

    with gr.Row():
        with gr.Column(scale=2):
            thread_id_input = gr.Textbox(
                value=str(uuid.uuid4()),
                label="🧵 Session Thread ID",
                placeholder="Leave blank or use existing thread ID",
                info="State persists across restarts via PostgreSQL checkpointer.",
            )
            incident_input = gr.Textbox(
                label="📝 Incident Description",
                placeholder="e.g. The auth service is returning HTTP 504 Gateway Timeout errors. Escalate immediately.",
                lines=3,
            )

            with gr.Row():
                trigger_btn = gr.Button("🚀 Trigger Triage", variant="primary", scale=2)
                new_btn = gr.Button("🔄 New Session", variant="secondary", scale=1)

            gr.Markdown("#### 💡 Quick Incident Examples")
            gr.Examples(
                examples=[
                    ["The auth service is timing out with 504 errors. Redis latency is high."],
                    ["Database query latencies exceed 5 seconds and pool is exhausted."],
                    ["Payment gateway webhook processing is failing with 502 Bad Gateway errors."],
                ],
                inputs=incident_input,
            )

            gr.Markdown("---")
            gr.Markdown("### 🛡️ Human-in-the-Loop (HITL) Escalation Gate")
            pending_box = gr.Markdown("*(No pending escalation)*")

            rejection_reason_input = gr.Textbox(
                label="Rejection Reason",
                placeholder="e.g. Scheduled maintenance in progress, no need to page on-call.",
                lines=1,
            )

            with gr.Row():
                approve_btn = gr.Button("✅ Approve Escalation", variant="primary", interactive=False)
                reject_btn = gr.Button("❌ Reject Action", variant="stop", interactive=False)

        with gr.Column(scale=3):
            workflow_state_badge = gr.Textbox(
                value="IDLE",
                label="📊 Workflow State",
                interactive=False,
            )
            agent_log_output = gr.Markdown(
                value="Enter an incident description above and click **Trigger Triage** to start.",
                label="📋 Agent Log / Triage Findings",
            )

    # Event handlers
    trigger_btn.click(
        ui_trigger_triage,
        inputs=[thread_id_input, incident_input],
        outputs=[
            thread_id_input,
            workflow_state_badge,
            agent_log_output,
            pending_box,
            approve_btn,
            reject_btn,
        ],
    )

    approve_btn.click(
        ui_approve,
        inputs=[thread_id_input],
        outputs=[
            workflow_state_badge,
            agent_log_output,
            pending_box,
            approve_btn,
            reject_btn,
        ],
    )

    reject_btn.click(
        ui_reject,
        inputs=[thread_id_input, rejection_reason_input],
        outputs=[
            workflow_state_badge,
            agent_log_output,
            pending_box,
            approve_btn,
            reject_btn,
        ],
    )

    new_btn.click(
        ui_new_session,
        outputs=[
            thread_id_input,
            incident_input,
            workflow_state_badge,
            agent_log_output,
            pending_box,
            rejection_reason_input,
            approve_btn,
            reject_btn,
        ],
    )

# ── Mount Gradio on FastAPI ────────────────────────────────────────────────────

app = gr.mount_gradio_app(api, demo, path="/")
