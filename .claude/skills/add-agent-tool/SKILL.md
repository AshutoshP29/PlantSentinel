---
name: add-agent-tool
description: Add or change a tool of the PlantSentinel agent so the guard, roles, audit log, prompt, UI step list and tests all stay consistent. Use when asked to give the agent a new capability, rename or restrict a tool, or change what a tool returns.
---

# Add an agent tool

A tool is more than a function: the guard allow-list, role permissions, audit log, system
prompt and UI summary all key off its name. Miss one and the tool is silently unavailable,
unaudited, or blocked for everyone. Read `docs/ARCHITECTURE.md` (Privacy and security) first.

## Checklist

1. **Input schema** in `backend/app/agent/schemas.py`: a pydantic model with field
   descriptions (the model reads them). Validate tags with the existing `TagInput`.
2. **Body** in `backend/app/agent/tools.py`: `def _my_tool(ctx: AgentContext, args: MyInput) -> dict`.
   - Read data through `app.agent.data` or the analytics functions; never write to the DB
     except through existing helpers.
   - Raise `ToolError("...")` for user-facing failures (unknown tag, nothing found); the
     agent sees the message and can recover.
   - Return ids the answer can cite (`INSP-…`, `WO-…`, manual refs via `ctx.remember`).
   - Never accept or return URLs or e-mail addresses: the guard blocks arguments that contain them.
3. **Register** it in `TOOL_SPECS` in `tools.py`: `(name, InputModel, _my_tool, description)`.
   That registration is the allow-list; nothing else enables a tool.
4. **UI summary**: add a `case "my_tool":` to `summarise()` in `tools.py` (the one line the
   step list shows; the live UI renders any tool name). If the tool should appear in demo mode
   too, add it to `frontend/src/api/agentMock.ts`.
5. **Roles**: if the tool writes files or exports data, add it to `TOOL_PERMISSION` in
   `backend/app/guard/roles.py` with `"generate"` or `"export"`. Read-only tools need nothing.
6. **Prompt**: list the tool and when to use it in `SYSTEM_PROMPT`
   (`backend/app/agent/prompts.py`). Keep the citation rules intact.
7. **Tests** in `backend/tests/test_agent_tools.py` using `tests.agent_helpers.make_context`:
   the happy path, an unknown tag (`ToolError`), and the returned ids. Graph-level behaviour
   uses `ScriptedChatModel` + `tool_call(...)` in `test_agent_graph.py`. If the tool is
   restricted, add a role case to `backend/tests/test_roles.py`.
8. **Verify**: `.\make.ps1 lint`, `.\make.ps1 test`, then on the demo laptop
   `agent_cli.py rehearse -n 3` (inside the backend container) to confirm the demo question
   still passes.

## Don'ts

- Don't add network access of any kind to a tool; the stack is offline by design.
- Don't hard-code model names; use `get_settings()`.
- Don't rename a tool without updating `TOOL_PERMISSION`, `test_roles.py` and the demo-mode
  mock in `frontend/src/api/agentMock.ts`; all of them key off tool names.
