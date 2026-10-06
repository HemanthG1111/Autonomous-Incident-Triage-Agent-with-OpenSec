# Tasks: harden-hitl-routing

- [x] Verify route_tools iterates ALL tool_calls (not just index 0)
- [x] Add regression test: mixed [safe, sensitive] routes to sensitive_tools
- [x] Add regression test: rejection injects ToolMessage for every sensitive call
- [x] Run pytest -q and confirm all tests pass
