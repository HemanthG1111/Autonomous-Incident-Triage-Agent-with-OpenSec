# Proposal

## Why

The triage agent needs a user-facing interface. Engineers need both a web UI for interactive
use and a REST API for automation and CI. The HITL escalation (Change 3) also requires
`/approve` and `/reject` endpoints so engineers can act on paused threads.

## What Changes

- Replace the current `app.py` (simple `/triage` endpoint + basic chatbot) with a fully spec-compliant implementation:
  - `POST /chat` — accepts `{thread_id, message}`, returns `COMPLETED` or `AWAITING_APPROVAL`
  - `POST /approve` — accepts `{thread_id}`, returns `RESOLVED` or HTTP 400 if nothing pending
  - `POST /reject` — accepts `{thread_id, reason}`, returns `REJECTED_AND_RESUMED`
  - `GET /healthz` — liveness probe (no Gemini/DB calls)
- Gradio Blocks UI with: Thread ID field, incident description, Trigger Triage button,
  Approve and Reject buttons, Rejection Reason field, Workflow State label, Agent Log markdown.
- REST handlers and Gradio callbacks share one service layer (`service.py`) — no duplicated logic.
- Local run defaults to `$PORT` env var with fallback to 8000.
- Tests with FastAPI TestClient and mocked agent.

## Capabilities

### New Capabilities

- `triage-api`: REST API for the triage agent.
- `triage-ui`: Gradio web UI for the triage agent.

## Impact

- `app.py`: Full rewrite.
- `service.py`: New shared service layer.
- `tests/test_app.py`: New test file.

## Rollback

Revert `app.py` and delete `service.py`. The agent core (`agent.py`) is unaffected.
