# PlantSentinel: notes for AI coding assistants

Private, offline AI for industrial failure diagnosis. Read `README.md` for setup and
`docs/ARCHITECTURE.md` before changing how components talk to each other.

## Hard rules

- **No AI attribution** in commit messages, PR titles or PR bodies: no `Co-authored-by`
  lines naming an AI, no "Generated with" lines. The `commit-msg` hook and the
  `commit-policy` workflow reject them.
- **Offline at runtime.** The app may only talk to Ollama (and Chroma) on the internal
  network. No cloud APIs, telemetry or CDN assets; Chroma telemetry stays off.
- **Model names come from `backend/app/config.py`** (env-overridable), never hard-coded.
- **Ask before** adding dependencies, changing the SQLite schema (`backend/app/db.py`) or
  changing public API routes; the frontend's types in `frontend/src/api/types.ts` mirror them.
- Every change goes through a PR from a fresh branch off `main`; CI must be green.

## Commands (Windows: `.\make.ps1 <target>`, elsewhere `make <target>`)

| Target | Does |
|---|---|
| `setup` | `uv sync --group dev` + git hooks |
| `lint` / `format` | ruff check + format check / auto-fix |
| `test` | pytest without integration tests (no Ollama or GPU needed) |
| `seed` | fresh demo database; fails if the planted story doesn't verify |
| `demo-check` / `offline-check` | every demo beat through the gateway / plus the isolation check |

Run `lint` and `test` before every commit. Tests that need a real model are marked
`@pytest.mark.integration`.

## Where things live

- `backend/app/analytics/`: clustering, bad actors, risk model, dashboard (Person A)
- `backend/app/agent/`: LangGraph agent, tools, RAG, inspections, prompts (Person B)
- `backend/app/guard/`, `privacy/`, `docker-compose.yml`: guard, roles, audit, network (Person C)
- `frontend/`: React + Vite + TypeScript (Person D)
- `scripts/`: seeding, training, demo checks, generators

## Things that bite

- Windows Git Bash rewrites `/app/...` paths in `docker compose exec`; prefix with
  `MSYS_NO_PATHCONV=1`.
- The host Ollama app grabs the GPU; quit it before `docker compose up`, or the container
  runs on CPU.
- Analysis windows end at the latest work order (2026-11-13) or `ANALYSIS_AS_OF`, never today.
- The small LLM sometimes answers early or cites tool names; `agent/graph.py` enforces a
  checklist and rewrites citations. Re-run `agent_cli.py rehearse -n 3` after prompt changes.
- Skills for common tasks: `.claude/skills/run-demo`, `.claude/skills/add-agent-tool`.
