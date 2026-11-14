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

## Demo mode vs the real backend

Until the backend is ready, the app runs on built-in demo data:
- `src/api/mock.ts` holds the static data.
- `src/api/store.ts` holds the documents, audit log and blocked attempts, which change as you use the app.
- `src/api/agentMock.ts` holds the scripted agent runs.

Every number in the demo data follows the brief's P-101 story:
- 4 seal failures in 180 days
- MTBF down from 112 to 45 days (−60%)
- 0.3 mm misalignment found in the 12 Nov 2026 inspection
- The pump manual links misalignment to seal wear

To switch to the FastAPI backend, create `frontend/.env.local`:

```
VITE_USE_MOCK=false
```

In dev, every `/api/*` request is proxied to `http://127.0.0.1:8000`. Set `VITE_BACKEND_URL` to point somewhere else.
Every request carries `X-Role` and `X-User` headers so the guard can enforce roles and write the audit log.

## API contract

All screens fetch through `src/api/client.ts`. The response shapes are in `src/api/types.ts`.
Formats: dates are `YYYY-MM-DD`, months are `YYYY-MM`, money is in rupees, and MTBF is in days.

| Endpoint | Returns | Screen |
|---|---|---|
| `GET /api/dashboard/summary?window_days=&unit=&asset_type=&criticality=` | `DashboardSummary` | Dashboard |
| `GET /api/bad-actors?top_n=10&…same filters` | `BadActor[]` | Dashboard, report preview |
| `GET /api/failure-modes?window_days=` | `FailureModeCount[]` | Dashboard |
| `GET /api/mtbf-trend` | `MtbfPoint[]` (plant average) | Dashboard |
| `GET /api/assets` | `Asset[]` | Asset switcher, agent context |
| `GET /api/assets/:tag` | `AssetDetail` | Asset detail |
| `POST /api/ingest` (multipart `files`) | `{ files: IngestFile[], summary: IngestSummary }` | Upload |
| `POST /api/cluster` | `ClusterPreview[]` | Upload |
| `DELETE /api/data` | — | Upload |
| `POST /api/agent/ask` `{question, tag}` | Server-Sent Events, one `AgentEvent` JSON per `data:` line | Ask the agent |
| `POST /api/privacy/injection-test` | Server-Sent Events (`AgentEvent`) | Privacy |
| `GET /api/documents` | `DocumentItem[]` | Documents |
| `POST /api/documents/work-order` `{tag}` | `DocumentItem` (writes the .docx) | Asset detail, Agent, Documents |
| `POST /api/documents/bad-actor-report` | `DocumentItem` (writes the .xlsx) | Dashboard, Documents |
| `PUT /api/documents/:id/work-order` | — | Documents (edit draft) |
| `POST /api/documents/:id/approve` | — | Documents (approve draft) |
| `GET /api/documents/:id/download` | the file | Documents |
| `GET /api/privacy/status` | `PrivacyStatus` (polled every 3 s) | Top bar, Privacy |
| `GET /api/privacy/blocked` | `BlockedAttempt[]` | Alert banner, Privacy |
| `GET /api/audit-log` | `AuditEntry[]` | Privacy |

### Agent stream events

The agent endpoint streams these events:

```
data: {"type":"step","step":{"id":"s0","tool":"get_asset_history","summary":"Running…","status":"running"}}
data: {"type":"step","step":{"id":"s0","tool":"get_asset_history","summary":"7 work orders","status":"done","duration_ms":400}}
data: {"type":"token","text":"## Likely root cause: shaft misalignment\n"}
data: {"type":"done","citations":[{"id":1,"kind":"inspection","label":"Inspection · p. 2","title":"…","quote":"…"}],"can_draft_work_order":true}
```

What each event does:
- A `step` event with the same `id` updates that step's row in the activity panel.
- Answer text is markdown-lite: `## ` starts a heading, and `[n]` refers to citation `n`.
- A `blocked` event (`{"type":"blocked","attempt":BlockedAttempt}`) makes the red alert banner appear.

## Screens

| Route | Screen | Design |
|---|---|---|
| `/` | Reliability dashboard: filters, top bad actor, stat tiles, top 10 table, failure modes, MTBF trend | `brief/…dashboard-4.png` |
| `/upload` | Upload: drop zone, file statuses, summary, scan preview, clustering | `brief/…clustering-1.png` |
| `/assets/:tag` | Asset detail: timeline, work orders, MTBF, risk + contributing factors, readings, inspection | `brief/…Insights-2.png` |
| `/agent?q=&tag=` | Ask the agent: streamed steps, cited answer, source preview, draft work order | `brief/…misalignment-3.png` |
| `/documents?doc=` | Documents: list, search/filter, work-order preview and edit, report preview | `brief/…preview-5.png` |
| `/privacy` | Privacy & audit: connections, isolation, redactions, injection test, audit log, permissions | `brief/…blocked request-6.png` |

On every screen:
- The role switch in the top bar changes what you can see and do (see below).
- The theme toggle switches between light (the default) and dark.

## Roles and permissions

Roles follow the plant maintenance reporting line. They're defined in `src/lib/roles.ts`, which is also the single source of truth for permissions.

| Level | Role (id) |
|---|---|
| 1 | Plant Head (`plant_head`) |
| 2 | Maintenance Manager (`maintenance_manager`) |
| 3 | Reliability Engineer (`reliability_engineer`), Maintenance Planner (`maintenance_planner`) |
| 4 | Shift Supervisor (`shift_supervisor`) |
| 5 | Technician (`technician`), Operator (`operator`) |
| Support | System Admin, IT/OT (`system_admin`); Contractor, external (`contractor`) |

How permissions work:
- `GRANTS` in `roles.ts` maps each permission to the roles that hold it. This table is a **draft** for the team to review.
- The UI uses the table to hide screens and repair costs, and to disable buttons.
- **The backend guard must enforce the same table.** The UI only mirrors it. Every request sends the role id in `X-Role`.
- The **Roles & access** screen (`/roles`) shows the hierarchy and the full matrix. Click a role card to view the app as that role.

## Demo path

1. **Upload:** click Load demo dataset, then Run clustering.
2. **Dashboard:** P-101 is the top bad actor. Click "Ask why it keeps failing".
3. **Agent:** steps stream in, then a cited answer appears. Click "Draft work order"; it opens in Documents.
4. **Privacy:** click "Run injection test". The red alert appears and the audit log shows "Blocked".

## Layout

```
src/
  api/          types.ts (contract), client.ts (fetch layer), mock.ts, store.ts, agentMock.ts, events.ts
  components/   Layout, ui (buttons, chips, cards, modal…), SourceDocs (scan/manual "paper"), charts/
  hooks/        useApi, usePrivacy
  lib/          format, theme, role, status, toast
  pages/        one file per screen
```
