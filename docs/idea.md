# Idea: Autonomous Incident Triage Agent

When an on-call engineer describes an incident in plain English ("the auth service is timing
out"), an AI agent should investigate on its own: check the health of the affected backend
services, search our internal runbooks for matching remediation steps, and reply with what it
found and what to do next. If the problem needs manual intervention or the service stays
degraded, the agent may escalate by opening a ticket and paging the on-call team, but it must
never do this by itself. Every escalation pauses and waits for an engineer to approve or reject
it, a rejected escalation must not happen, and a paused investigation must survive restarts so
someone can approve it hours later.

Engineers should use it through a simple web UI and a REST API. Everything must run on free
tiers with no credit card: Gemini via Google AI Studio for reasoning and embeddings, Supabase
Postgres with pgvector for runbooks and agent state, LangGraph for the agent, FastAPI with a
Gradio UI for the app, and Render for hosting. Start with a few sample runbooks covering the
auth, database and payments services.
