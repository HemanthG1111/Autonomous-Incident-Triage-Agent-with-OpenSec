# Tasks: add-api-and-ui

- [x] Create service.py with shared triage_chat(), approve_thread(), reject_thread() functions
- [x] Rewrite app.py: POST /chat, POST /approve, POST /reject, GET /healthz
- [x] Mount Gradio Blocks UI at "/" with all required components
- [x] Wire Gradio callbacks to service.py (no duplicated approve/reject logic)
- [x] Auto-generate UUID when Thread ID is empty on Trigger Triage
- [x] Write tests/test_app.py with FastAPI TestClient and mocked agent
- [x] Run pytest -q and confirm all tests pass
