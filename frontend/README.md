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

Sign in with a demo account, e.g. `a.rao` / `demo123` (Reliability Engineer). The sign-in screen lists one demo account per role.

### In the Docker stack

The `gateway` service in `docker-compose.yml` serves the frontend build and forwards `/api` to the backend. It's the only host port: http://127.0.0.1:8080.

1. Build the frontend against the real backend:

   ```bash
   cd frontend
   VITE_USE_MOCK=false npm run build    # writes frontend/dist
   ```

   In PowerShell, set the variable first: `$env:VITE_USE_MOCK='false'; npm run build`.
2. Mount the build into the gateway. This needs one volume line in `docker-compose.yml`, owned by the compose author:

   ```yaml
   gateway:
     volumes:
       - ./deploy/gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro
       - ./frontend/dist:/usr/share/nginx/html:ro
   ```

The gateway's `nginx.conf` already sends every non-API path to `index.html`, which the app needs. It also turns buffering off on `/api`, so the agent's live event stream arrives as it happens.

## Demo mode vs the real backend

Until the backend is ready, the app runs on demo data that follows the teammates' data, read-only:
- `src/api/fixtures/demo-data.json` holds the assets, operating conditions and all 491 work orders. They're converted from `data/synthetic/*.csv`, with failure modes taken from `clusters_fallback.json`.
- `src/api/mock.ts` holds the bad actors and risk scores in the backend's own output format. It also holds the plant summary and the clustering metrics from `models/metrics.json`.
- `src/api/store.ts` holds accounts, documents, the audit log and blocked attempts. These change as you use the app.
- `src/api/agentMock.ts` holds the scripted agent runs.

The demo follows the story planted in `scripts/generate_synthetic.py`:
- **P-101:** 4 mechanical-seal failures in the last 180 days (2 Jun, 22 Jul, 15 Sep, 2 Nov 2026). The gap between failures fell from 150 to 51 days (−66%), and the risk model scores it 96/100 for overstrain.
- **C-203:** bearing overheating 3 times; the gap fell from 300 to 60 days.
- **E-302:** fouling 3 times.

To switch to the FastAPI backend, create `frontend/.env.local`:

```
VITE_USE_MOCK=false
```

In dev, every `/api/*` request is proxied to `http://127.0.0.1:8000`. Set `VITE_BACKEND_URL` to point somewhere else.
Every request carries `Authorization: Bearer <token>`, `X-Role` and `X-User`, so the guard can enforce roles and write the audit log.

## API contract

All screens fetch through `src/api/client.ts`.
- Where the backend already has code, the frontend takes its output **as is**. These raw shapes are the `Backend*` types in `src/api/types.ts`, and `src/api/adapters.ts` converts them for the screens.
- The other endpoints are proposals.

Formats: dates are `YYYY-MM-DD`, money is in rupees, and MTBF is in days.

**Uses the backend's existing code (return it unchanged):**

| Endpoint | Return exactly | Screen |
|---|---|---|
| `GET /api/assets` | rows of the `assets` table (A/B/C criticality, `pump`/`compressor`/…) | everywhere |
| `GET /api/bad-actors?top_n=50` | `bad_actors.get_bad_actors()` | Dashboard, asset header, report |
| `GET /api/risk/:tag` | `risk.predict_risk(tag)` | Asset detail (score, SHAP reasons, readings) |
| `GET /api/assets/:tag/work-orders` | `work_orders` rows + `failure_mode` name | Asset detail (timeline, gaps chart, table) |
| `GET /api/audit-log` | `audit_log` rows (`allowed` / `blocked` / `error`) | Privacy |

The unit, asset type and criticality filters run in the browser, so `/bad-actors` doesn't need them.

**Proposed (no backend code yet):**

| Endpoint | Returns | Screen |
|---|---|---|
| `POST /api/auth/login` `{username, password}` | `AuthSession` (`token` + `UserAccount`) | Sign-in |
| `GET /api/auth/me` · `POST /api/auth/logout` | `UserAccount` · — | Sign-in |
| `GET /api/users` · `POST /api/users` · `DELETE /api/users/:username` | `UserAccount[]` · `UserAccount` · — | Users |
| `GET /api/dashboard/summary?window_days=` | `DashboardSummary` | Dashboard |
| `GET /api/failure-modes?window_days=` | `FailureModeCount[]` | Dashboard |
| `GET /api/mtbf-trend` | `MtbfPoint[]` (plant average by month) | Dashboard |
| `GET /api/assets/:tag/inspection` | `Inspection` (404 when none) | Asset detail |
| `POST /api/ingest` (multipart `files`) | `{ files: IngestFile[], summary: IngestSummary }` | Upload |
| `POST /api/cluster` | `ClusterRun` (top clusters + `metrics.json` clustering section) | Upload |
| `DELETE /api/data` | — | Upload |
| `POST /api/agent/ask` `{question, tag}` | Server-Sent Events (see below) | Ask the agent |
| `POST /api/privacy/injection-test` | Server-Sent Events | Privacy |
| `GET /api/documents` | `DocumentItem[]` | Documents |
| `POST /api/documents/work-order` `{tag}` | `DocumentItem` (writes the .docx) | Asset detail, Agent, Documents |
| `POST /api/documents/bad-actor-report` | `DocumentItem` (writes the .xlsx) | Dashboard, Documents |
| `PUT /api/documents/:id/work-order` · `POST /api/documents/:id/approve` | — | Documents |
| `GET /api/documents/:id/download` | the file | Documents |
| `GET /api/privacy/status` | `PrivacyStatus` (polled every 3 s) | Top bar, Privacy |
| `GET /api/privacy/blocked` | `BlockedAttempt[]` | Alert banner, Privacy |

### Agent stream events

The event names and fields will follow the agent's `graph.EVENT_TYPES` once it's shared. Until then the screen understands these events:

```
data: {"type":"step","step":{"id":"s0","tool":"get_asset_history","summary":"Running…","status":"running"}}
data: {"type":"token","text":"## Likely root cause: shaft misalignment\n"}
data: {"type":"done","citations":[{"id":1,"kind":"inspection","label":"Inspection · p. 2","title":"…","quote":"…"}],"can_draft_work_order":true}
data: {"type":"blocked","attempt":{"id":"b1","at":"…","tool":"external_request","target":"evil.com","source":"…","reason":"Not on allow-list"}}
```

## Sign-in and accounts

- Everything except `/login` needs a signed-in user. Opening a page while signed out goes to sign-in and then back to that page.
- **People add accounts for roles below them in the reporting line**, on the **Users** screen:
  - Plant Head → everyone in the line, plus contractors
  - Maintenance Manager → engineers, planners, supervisors, technicians, operators and contractors
  - Shift Supervisor → technicians and operators
  - System Admin → anyone

  The rule is `manageableRoles()` in `src/lib/roles.ts`.
- **Demo mode only:** accounts live in the browser. Passwords are salted and SHA-256 hashed, and added accounts survive a refresh. This is enough for the demo but isn't real security.
- **The backend must do the real check.** It should verify passwords (bcrypt/argon2), issue the token, apply the same hierarchy rule in `POST /api/users`, and check the role on every request.

## Roles and permissions

Roles follow the plant maintenance reporting line. `src/lib/roles.ts` is the single source of truth for roles, permissions and who can add whom.

| Level | Role (id) | Demo account |
|---|---|---|
| 1 | Plant Head (`plant_head`) | `v.iyer` |
| 2 | Maintenance Manager (`maintenance_manager`) | `s.kulkarni` |
| 3 | Reliability Engineer (`reliability_engineer`), Maintenance Planner (`maintenance_planner`) | `a.rao`, `n.desai` |
| 4 | Shift Supervisor (`shift_supervisor`) | `p.nair` |
| 5 | Technician (`technician`), Operator (`operator`) | `k.singh`, `m.khan` |
| Support | System Admin, IT/OT (`system_admin`); Contractor, external (`contractor`) | `d.shah`, `j.thomas` |

Every demo account uses the password `demo123`.

How permissions work:
- `GRANTS` in `roles.ts` maps each permission to the roles that hold it. This table is a **draft** for the team to review.
- The UI uses it to lock screens, hide repair costs and disable buttons.
- **The backend guard must enforce the same table**; the UI only mirrors it.
- The **Roles & access** screen (`/roles`) shows the hierarchy, who can add whom, and the full matrix.

## Screens

| Route | Screen | Design |
|---|---|---|
| `/login` | Sign-in, with demo accounts in demo mode | — |
| `/` | Reliability dashboard: filters, top bad actor, stat tiles, top 10 table, failure modes, MTBF trend | `brief/…dashboard-4.png` |
| `/upload` | Upload: drop zone, file statuses, summary, scan preview, clustering + metrics | `brief/…clustering-1.png` |
| `/assets/:tag` | Asset detail: timeline, days between failures, work orders, risk + SHAP reasons, readings, inspection | `brief/…Insights-2.png` |
| `/agent?q=&tag=` | Ask the agent: streamed steps, cited answer, source preview, draft work order | `brief/…misalignment-3.png` |
| `/documents?doc=` | Documents: list, search/filter, work-order preview, edit, approve, report preview | `brief/…preview-5.png` |
| `/privacy` | Privacy & audit: connections, isolation, redactions, injection test, audit log, your access | `brief/…blocked request-6.png` |
| `/users` | Users: add and remove people below you | — |
| `/roles` | Roles & access: hierarchy and permission matrix | — |

## Demo path

1. Sign in as `a.rao` (Reliability Engineer).
2. **Upload:** click Load demo dataset, then Run clustering.
3. **Dashboard:** P-101 is the top bad actor. Click "Ask why it keeps failing".
4. **Agent:** steps stream in, then a cited answer appears. Click "Draft work order".
5. Sign in as `s.kulkarni` (Maintenance Manager) and **approve** the work order in Documents.
6. Sign in as `d.shah` (System Admin). On **Privacy**, click "Run injection test": the red alert appears and the audit log shows "Blocked".

## Layout

```
src/
  api/          types.ts (screen + raw backend types), adapters.ts, client.ts, mock.ts, store.ts,
                agentMock.ts, events.ts, fixtures/demo-data.json
  components/   Layout, AuthProvider, Gate, ui (buttons, chips, cards, modal…), SourceDocs, charts/
  hooks/        useApi, usePrivacy
  lib/          roles (roles, permissions, hierarchy), role, auth, format, theme, status, toast,
                gaps, sha256
  pages/        one file per screen
```
