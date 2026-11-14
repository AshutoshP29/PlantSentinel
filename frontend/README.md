# PlantSentinel frontend

React + TypeScript + Vite, styled with Tailwind CSS v4, with charts from Recharts.
Everything is bundled locally (including the Inter font), so the UI works with no internet connection.

## Run it

```bash
cd frontend
npm install
npm run dev          # demo data, http://localhost:5173
npm run dev:live     # every feature whose backend endpoint exists (backend on :8000)
```

Other scripts: `npm run build` / `npm run build:live` (type-check + production build), `npm run lint`.

Sign in with a demo account, e.g. `a.rao` / `demo123` (Reliability Engineer). The user menu has **Switch role (demo)**.

## In the Docker stack

The compose `gateway` serves `frontend/dist` and forwards `/api` to the backend (`deploy/gateway/nginx.conf`):

```powershell
cd frontend; npm run build:live; cd ..     # writes frontend/dist against the live backend
docker compose up -d --build               # then open http://127.0.0.1:8080
```

## Going live, screen by screen

| Feature | Endpoint(s) | Backend |
|---|---|---|
| `agent` | `POST /api/agent/ask`, `GET /api/agent/status` | B ✓ |
| `documents` | `GET /api/documents`, `POST /api/documents/work-order`, `POST /api/documents/bad-actor-report`, `GET /api/documents/{id}/download` | B ✓ |
| `inspections` | `GET /api/assets/{tag}/inspection` | B ✓ |
| `assets` · `bad_actors` · `risk` · `work_orders` | `/api/assets`, `/api/bad-actors`, `/api/risk/{tag}`, `/api/assets/{tag}/work-orders` | A ✓ |
| `summary` · `failure_modes` · `mtbf` · `upload` | `/api/dashboard/summary`, `/api/failure-modes`, `/api/mtbf-trend`, `/api/cluster`, `/api/ingest/work-orders` | A ✓ |
| `privacy` · `audit` | `/api/privacy/status` (every 2 s), `/api/privacy/blocked`, `/api/privacy/injection-test`, `/api/audit-log` | C, pending |

How to switch:
- `npm run dev:live` and `build:live` turn on every feature marked ✓.
- To pick features yourself, set `VITE_LIVE=agent,documents,…` in `frontend/.env.local`.
- Once C's endpoints exist, use `VITE_USE_MOCK=false`, which makes everything live.

The top bar shows **Demo data**, **Partly live** or nothing (fully live). If the privacy status endpoint doesn't answer, the network badge says "Network status unavailable" rather than "0 external".

Every request carries three headers:
- `X-Role`: the spec role, `engineer` or `technician`.
- `X-Plant-Role`: the detailed role id.
- `X-User`: the person's name.

## Agent stream (`POST /api/agent/ask`)

The request is `{question, tag, history}`. The response is server-sent events, one JSON per `data:` line, produced by `backend/app/agent/frontend_events.py`:

| Event | Screen |
|---|---|
| `{type: "step", step: {id, tool, summary, status, duration_ms}}` | **Agent activity** row, updated in place by `id`. `blocked` status → red step |
| `{type: "token", text}` | answer text, streamed (markdown-lite). Citations appear as `[1]`, `[2]` … |
| `{type: "blocked", attempt: {id, at, tool, target, source, reason}}` | red alert banner on every screen |
| `{type: "done", citations: [{id, kind, label, title, quote}], can_draft_work_order}` | `[n]` refs become clickable. The source card renders a **manual** page, an **inspection** report (findings table, misalignment highlighted) or a **work order** |
| `{type: "error", message}` | error under the answer |

More agent behaviour:
- **Draft work order** calls `POST /api/documents/work-order` and shows a .docx download. If the agent drafted one itself (`generate_work_order` step), the matching document is fetched from `GET /api/documents` and shown with its download.
- **Readiness:** `GET /api/agent/status` drives the "Agent ready" chip and a warning banner (Ollama, missing models, no manual passages).
- **Demo mode** (`src/api/agentMock.ts`) emits the same events, with the agent's tool names and summaries, the demo inspections (INSP-003, INSP-004) and real manual passages.

## Documents and inspections

- **Documents:** list, preview, download and creation use B's endpoints. Draft fields (`recommended_steps`, `parts`, `safety`, `references`) keep their line breaks.
  - **Edit** and **Approve** have no backend endpoints yet. When documents are live, they're disabled with that reason.
- **Inspection** (asset page): B's `to_api()` matches the `Inspection` type.
  - The report number falls back to the id (`INSP-P101-20261106`) until B switches to report numbers (`INSP-004`).
  - An empty `inspector` is hidden, and `summary` is shown when present.

## Demo data

Demo mode follows the teammates' committed data, read-only:
- `src/api/fixtures/demo-data.json` holds the assets, operating conditions and all 491 work orders, converted from `data/synthetic/`.
- `src/api/mock.ts` holds the bad actors and risk in the backend's format, plus the metrics from `models/metrics.json`.
  - The P-101 inspection matches `data/scans/INSP-004_P-101.jpg`.
  - **Optional:** add `src/api/fixtures/risk.json`, containing the real `predict_risk()` output for all assets. It's used automatically.
- `src/api/store.ts` holds accounts, documents, the audit log and blocked attempts.

## Rehearsal checklist (demo laptop)

1. **Models:** pull the models, including `qwen2.5:7b-instruct-q3_K_M`. Quit the host Ollama app before starting the stack.
2. **Data:** run `.\make.ps1 seed` (or `scripts/seed_demo.py --reset`). It verifies that P-101, C-203 and E-302 are the top bad actors.
3. **Start:** run `npm run build:live` in `frontend/`, then `docker compose up -d --build`, and open http://127.0.0.1:8080.
4. **Before the audience:** sign in as `a.rao` and confirm the agent chip says **Agent ready · N manual passages**. Turn Wi-Fi off.
5. **Demo path** (brief §12):
   1. **Upload:** load work orders → Run clustering.
   2. **Dashboard:** P-101 is the top bad actor → "Ask why it keeps failing".
   3. **Agent:** steps stream in, the answer cites the INSP-004 inspection and the pump manual. Open `[1]`, then **Draft work order** → Download .docx.
   4. **Switch role** to Maintenance Manager → Documents.
   5. **Privacy:** 0 external connections → Run injection test → red alert, "Blocked" in the audit log (needs C's endpoints).
6. **Timing:** time each step. The 7B q3 model is the slow part, so check the agent answer fits the 60 s slot.

## Sign-in, roles and accounts

- The backend gets the role from the `X-Role` header. Sign-in and user management run in the browser and never wait on a backend.
  - If the team adds real auth (`/api/auth/login`, `/api/auth/me`, `/api/users`), set `VITE_AUTH=server`.
  - Hide the demo switcher with `VITE_DEMO_SWITCHER=false`.
- **Users** screen: people add accounts for roles below them in the reporting line. The rule is `manageableRoles()` in `src/lib/roles.ts`.
- `GRANTS` in `roles.ts` is the draft permission matrix.

| Level | Role (id) | Demo account |
|---|---|---|
| 1 | Plant Head (`plant_head`) | `v.iyer` |
| 2 | Maintenance Manager (`maintenance_manager`) | `s.kulkarni` |
| 3 | Reliability Engineer (`reliability_engineer`), Maintenance Planner (`maintenance_planner`) | `a.rao`, `n.desai` |
| 4 | Shift Supervisor (`shift_supervisor`) | `p.nair` |
| 5 | Technician (`technician`), Operator (`operator`) | `k.singh`, `m.khan` |
| Support | System Admin (`system_admin`), Contractor (`contractor`) | `d.shah`, `j.thomas` |

Every demo account uses the password `demo123`.

## Layout

```
src/
  api/          types.ts (screen + backend + /agent/ask types), adapters.ts, client.ts (live/demo per feature),
                mock.ts, store.ts, agentMock.ts, events.ts, fixtures/demo-data.json
  components/   Layout, AuthProvider, Gate, ui, SourceDocs (inspection + citation papers), charts/
  hooks/        useApi, usePrivacy
  lib/          roles, role, auth, format, theme, status, toast, gaps, sha256
  pages/        one file per screen
```
