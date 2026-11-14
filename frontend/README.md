# PlantSentinel frontend

React + TypeScript + Vite, styled with Tailwind CSS v4, with charts from Recharts.
Everything is bundled locally (including the Inter font), so the UI works with no internet connection.

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Other scripts: `npm run build` (type-check + production build), `npm run lint`.

Sign in with a demo account, e.g. `a.rao` / `demo123` (Reliability Engineer). The sign-in screen lists one demo account per role. In the app, the user menu has a **Switch role (demo)** list.

## Going live, screen by screen

Every screen starts on built-in demo data. Switch features to the backend as their endpoints land, in `frontend/.env.local`:

```
VITE_LIVE=agent,bad_actors,risk,work_orders   # only these talk to the backend
# VITE_USE_MOCK=false                          # or: everything live
```

| Feature | Endpoint(s) | Screens |
|---|---|---|
| `agent` | `POST /api/agent/chat`, `GET /api/agent/status`, `GET /api/agent/work-orders/{file}` | Ask the agent |
| `assets` | `GET /api/assets` | everywhere |
| `bad_actors` | `GET /api/bad-actors?top_n=50` | Dashboard, asset header |
| `risk` | `GET /api/risk/:tag` | Asset detail |
| `work_orders` | `GET /api/assets/:tag/work-orders`, `GET /api/assets/:tag/inspection` | Asset detail |
| `summary` · `failure_modes` · `mtbf` | `GET /api/dashboard/summary` · `/api/failure-modes` · `/api/mtbf-trend` | Dashboard |
| `privacy` | `GET /api/privacy/status` (every 2 s), `GET /api/privacy/blocked`, `POST /api/privacy/injection-test` | Top bar, alert, Privacy |
| `audit` | `GET /api/audit-log` | Privacy |
| `upload` | `POST /api/ingest/work-orders`, `POST /api/cluster` | Upload |
| `documents` | see the table below | Documents |

The top bar shows **Demo data**, **Partly live** or nothing (fully live). In dev, `/api/*` is proxied to `http://127.0.0.1:8000` (`VITE_BACKEND_URL` to change).

Every request says who is asking:
- `X-Role`: the spec's role, `engineer` for roles that can export and `technician` for the rest. This is what the backend guard checks.
- `X-Plant-Role`: the detailed plant role id from `src/lib/roles.ts`.
- `X-User`: the person's name, for the audit log.

## Agent stream

The screen follows `backend/app/agent/graph.py` `EVENT_TYPES` exactly. `POST /api/agent/chat {message, history}` streams named server-sent events (`event: <type>` then `data: <json>`):

| Event | Payload | Screen |
|---|---|---|
| `run_started` | `{run_id, question}` | — |
| `status` | `{stage, message}` | "Planning the investigation…" while waiting |
| `tool_started` | `{call_id, tool, args}` | new row in **Agent activity** (running) |
| `tool_completed` | `{call_id, tool, status, summary}` | row done with summary and duration; `error` status or a summary starting "Blocked" → red step + red alert banner |
| `sources` | `{sources: [{ref, title, source, page, section, score, snippet}]}` | `[S1]` refs in the answer become clickable; the source card shows title, page, section and snippet |
| `work_order` | `{work_order_id, tag, priority, file, download_url}` | download button for the .docx |
| `answer` | `{text, cited_refs, unknown_refs, work_orders}` | answer text (markdown-lite); unknown refs are struck through |
| `error` | `{message}` | error under the answer |
| `done` | `{run_id, iterations, elapsed_s}` | "Answered in 4.2 s" |

More agent behaviour:
- Earlier turns are sent as `history`, the last 20.
- **Draft work order** asks the agent to generate one. The `work_order` event then brings the download link.
- **Readiness:** `GET /api/agent/status` drives a chip ("Agent ready · N manual passages") and a warning banner before the demo. The banner lists the problem: Ollama unreachable, a model missing, or no manual passages indexed.
- **Demo mode** (`src/api/agentMock.ts`) emits the same events, with the agent's real tool names and summary wording. It cites real passages from `data/docs/manuals/`.

## In the Docker stack

`frontend/Dockerfile` is the proposed build stage for the compose `gateway`. It runs `npm ci` and `npm run build` with `VITE_USE_MOCK=false`, then copies the result into `nginx:1.27-alpine`.

The gateway keeps its own `deploy/gateway/nginx.conf`, mounted as today. That config already handles `/api` with unbuffered SSE and the SPA fallback. The only compose change:

```yaml
gateway:
  build: ./frontend            # instead of image: nginx:1.27-alpine
  volumes:
    - ./deploy/gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

Then open http://127.0.0.1:8080. Pass `--build-arg VITE_USE_MOCK=true` to ship the demo data instead.

## Demo data

Demo mode follows the teammates' committed data, read-only:
- `src/api/fixtures/demo-data.json` holds the assets, operating conditions and all 491 work orders. They're converted from `data/synthetic/*.csv`, with failure modes from `clusters_fallback.json`.
- `src/api/mock.ts` holds the bad actors and risk in the backend's own output format, plus the clustering metrics from `models/metrics.json`.
  - **Optional:** drop `src/api/fixtures/risk.json` there, containing the real `predict_risk()` output for every asset (an array, or an object keyed by tag). It's used automatically, so demo risk equals live risk.
- `src/api/store.ts` holds accounts, documents, the audit log and blocked attempts. These change as you use the app.

The story:
- **P-101:** 4 seal failures in 180 days; the mean gap fell from 150 to 51 days.
- **C-203:** bearing overheating, with gaps down from 300 to 60 days.
- **E-302:** fouling.

## API contract

`src/api/types.ts` has two kinds of types:
- the screen types
- the `Backend*` and agent types, which mirror the teammates' code exactly

`src/api/adapters.ts` converts the backend types for the screens.

**In the backend now** (`backend/app/api/agent.py`, `backend/app/api/analytics.py`):

| Endpoint | Returns | Feature |
|---|---|---|
| `POST /api/agent/chat` · `GET /api/agent/status` · `GET /api/agent/work-orders/{file}` | agent stream, readiness, .docx | `agent` |
| `GET /api/assets` | `assets` rows | `assets` |
| `GET /api/bad-actors?top_n=&window_days=` | `score_bad_actors()` rows | `bad_actors` |
| `GET /api/risk/:tag` | `predict_risk(tag)`; 503 with a message when the model isn't trained (shown on the asset page) | `risk` |
| `GET /api/assets/:tag/work-orders` | `work_orders` rows + `failure_mode` | `work_orders` |
| `GET /api/dashboard/summary` · `GET /api/failure-modes` · `GET /api/mtbf-trend` | `DashboardSummary` · `FailureModeCount[]` · `MtbfPoint[]` | `summary` · `failure_modes` · `mtbf` |
| `POST /api/cluster` | `{clusters, metrics}` | `upload` |
| `POST /api/ingest/work-orders` (multipart `file`, one per request) | `{rows, inserted, duplicates_skipped, rejected, errors, new_assets}` | `upload` |

So `VITE_LIVE=agent,assets,bad_actors,risk,work_orders,summary,failure_modes,mtbf,upload` can be switched on today.

**Still proposed:**

| Endpoint | Returns | Feature |
|---|---|---|
| `GET /api/assets/:tag/inspection` | `Inspection` (404 when none). Demo mode shows `data/scans/INSP-004_P-101.jpg`'s content | `work_orders` |
| manual and scan upload | — (manuals are indexed with `scripts/agent_cli.py ingest`) | `upload` |
| `GET /api/documents` and the work-order/report actions | Documents | `documents` |
| `GET /api/privacy/status` · `GET /api/privacy/blocked` · `POST /api/privacy/injection-test` (same SSE events) | Privacy | `privacy` |
| `GET /api/audit-log` | `audit_log` rows | `audit` |

## Sign-in, roles and accounts

- The spec puts the role in a request header, and that's what the backend sees (`X-Role`). Sign-in and user management run **in the browser** and never block on a backend.
  - Demo passwords are salted SHA-256, and added accounts are kept in the browser.
  - If the team adds real auth (`/api/auth/login`, `/api/auth/me`, `/api/users`), set `VITE_AUTH=server`.
- **Switch role (demo)** in the user menu signs in as any seeded demo account without a password. Hide it with `VITE_DEMO_SWITCHER=false`.
- **Users** screen: people add accounts for roles below them in the reporting line. The rule is `manageableRoles()` in `src/lib/roles.ts`.
  - Plant Head → everyone in the line, plus contractors
  - Maintenance Manager → engineers, planners, supervisors, technicians, operators, contractors
  - Shift Supervisor → technicians, operators
  - System Admin → anyone
- `GRANTS` in `roles.ts` is the draft permission matrix. The UI uses it to lock screens, hide repair costs and disable buttons.

| Level | Role (id) | Demo account |
|---|---|---|
| 1 | Plant Head (`plant_head`) | `v.iyer` |
| 2 | Maintenance Manager (`maintenance_manager`) | `s.kulkarni` |
| 3 | Reliability Engineer (`reliability_engineer`), Maintenance Planner (`maintenance_planner`) | `a.rao`, `n.desai` |
| 4 | Shift Supervisor (`shift_supervisor`) | `p.nair` |
| 5 | Technician (`technician`), Operator (`operator`) | `k.singh`, `m.khan` |
| Support | System Admin (`system_admin`), Contractor (`contractor`) | `d.shah`, `j.thomas` |

Every demo account uses the password `demo123`.

## Screens

| Route | Screen | Design |
|---|---|---|
| `/login` | Sign-in (demo accounts listed when auth is local) | — |
| `/` | Dashboard: filters, top bad actor, stat tiles, top 10, failure modes, MTBF trend | `brief/…dashboard-4.png` |
| `/upload` | Upload: drop zone, file statuses, scan preview, clustering + metrics | `brief/…clustering-1.png` |
| `/assets/:tag` | Asset detail: timeline, days between failures, work orders, risk + SHAP reasons, readings, inspection | `brief/…Insights-2.png` |
| `/agent?q=&tag=` | Ask the agent: readiness, live tool steps, cited answer, source passage, work-order download | `brief/…misalignment-3.png` |
| `/documents?doc=` | Documents: list, preview, edit, approve, report preview | `brief/…preview-5.png` |
| `/privacy` | Privacy & audit: connections, isolation, redactions, injection test, audit log, your access | `brief/…blocked request-6.png` |
| `/users` · `/roles` | Add people below you · hierarchy and permission matrix | — |

## Demo path

1. Sign in as `a.rao`. Check the agent chip says **Agent ready**.
2. **Upload:** Load demo dataset → Run clustering.
3. **Dashboard:** P-101 is the top bad actor → "Ask why it keeps failing".
4. **Agent:** tool steps stream in, then a cited answer. Click `[S1]` to see the manual passage, then **Draft work order** to download the .docx.
5. **Switch role** to Maintenance Manager and approve the work order in Documents.
6. **Switch role** to System Admin. On **Privacy**, Run injection test → the red alert appears and the audit log shows "Blocked".

## Layout

```
src/
  api/          types.ts (screen + backend + agent types), adapters.ts, client.ts (live/demo per feature),
                mock.ts, store.ts, agentMock.ts, events.ts, fixtures/demo-data.json
  components/   Layout, AuthProvider, Gate, ui, SourceDocs (scan + manual passage), charts/
  hooks/        useApi, usePrivacy
  lib/          roles, role, auth, format, theme, status, toast, gaps, sha256
  pages/        one file per screen
```
