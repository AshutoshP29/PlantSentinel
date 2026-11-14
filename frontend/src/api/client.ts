// Every screen gets its data through this file.
//
// Live vs demo, per screen:
//   VITE_USE_MOCK=false            everything talks to the FastAPI backend
//   VITE_LIVE=agent,bad_actors     only these features are live; the rest stay on demo data
// Features: agent, assets, bad_actors, risk, work_orders, inspections, summary, failure_modes,
//           mtbf, documents, upload, privacy, audit.  `npm run dev:live` = everything that exists today.
// Raw backend shapes go through adapters.ts in both modes, so the screens never see raw fields.

import { can, type RoleId } from '../lib/roles'
import { specRole, toAsset, toAuditEntry, toBadActor, toReadings, toRisk } from './adapters'
import { runMockAgent, runMockInjection } from './agentMock'
import { emit } from './events'
import * as mock from './mock'
import * as store from './store'
import type {
  AgentEvent,
  AgentStatus,
  Asset,
  AssetDetail,
  AuditEntry,
  AuthSession,
  BackendAsset,
  BackendAuditRow,
  BackendBadActor,
  BackendRisk,
  BackendWorkOrder,
  BadActor,
  BlockedAttempt,
  ChatTurn,
  ClusterRun,
  DashboardFilters,
  DashboardSummary,
  DocumentItem,
  FailureModeCount,
  IngestFile,
  IngestKind,
  IngestSummary,
  Inspection,
  MtbfPoint,
  NewUser,
  PrivacyStatus,
  UserAccount,
  WorkOrderDraft,
  WorkOrderIngestResult,
} from './types'

export type Feature =
  | 'agent'
  | 'assets'
  | 'bad_actors'
  | 'risk'
  | 'work_orders'
  | 'inspections'
  | 'summary'
  | 'failure_modes'
  | 'mtbf'
  | 'privacy'
  | 'audit'
  | 'documents'
  | 'upload'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const LIVE = new Set(
  String(import.meta.env.VITE_LIVE ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
)
export const isLive = (f: Feature) => !USE_MOCK || LIVE.has(f) || LIVE.has('all')
/** What the top bar shows: all demo, partly live, or fully live. */
export const DATA_MODE: 'demo' | 'mixed' | 'live' = !USE_MOCK ? 'live' : LIVE.size ? 'mixed' : 'demo'

/** Sign-in is local (browser) unless the team adds auth endpoints: VITE_AUTH=server. */
export const AUTH_SERVER = import.meta.env.VITE_AUTH === 'server'
/** Quick "switch user" for demos (demo accounts only). Set VITE_DEMO_SWITCHER=false to hide. */
export const DEMO_SWITCHER = !AUTH_SERVER && import.meta.env.VITE_DEMO_SWITCHER !== 'false'

export const SITE = mock.SITE
export const DEMO_PASSWORD = store.DEMO_PASSWORD

const LATENCY = 300
const delay = (ms = LATENCY) => new Promise((r) => setTimeout(r, ms))
async function fromMock<T>(data: T, ms = LATENCY): Promise<T> {
  await delay(ms)
  return structuredClone(data)
}

// ---------- session ----------

let token: string | null = null

/** Called by AuthProvider whenever the signed-in user changes. */
export function setSessionUser(session: AuthSession | null) {
  token = session?.token ?? null
  store.setCurrentUser(session?.user ?? null)
}

/**
 * Every request says who is asking:
 *   X-Role        the spec's role: engineer | technician (what the backend guard checks)
 *   X-Plant-Role  the detailed plant role id (lib/roles.ts)
 *   X-User        display name, for the audit log
 */
function headers(extra: Record<string, string> = {}): Record<string, string> {
  const { role, user } = store.getSession()
  const h: Record<string, string> = {
    Accept: 'application/json',
    'X-Role': role ? specRole(can(role as RoleId, 'export_reports')) : '',
    'X-Plant-Role': role,
    'X-User': user,
    ...extra,
  }
  if (token && AUTH_SERVER) h.Authorization = `Bearer ${token}`
  return h
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: headers(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = (await res.json()) as { detail?: unknown }
      if (typeof j.detail === 'string') detail = j.detail
    } catch {
      /* not JSON */
    }
    throw new Error(`${detail} (${res.status})`)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}
const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body)

function qs(params: Record<string, string | number | undefined>): string {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  return p.length ? `?${p.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')}` : ''
}

// ---------- shared lookups ----------

let assetCache: Promise<Asset[]> | null = null
function loadAssets(): Promise<Asset[]> {
  assetCache ??= (isLive('assets') ? get<BackendAsset[]>('/assets') : fromMock(mock.assets, 100))
    .then((rows) => rows.map(toAsset))
    .catch((e: unknown) => {
      assetCache = null
      throw e
    })
  return assetCache
}

async function loadBadActorsRaw(windowDays = 180): Promise<BackendBadActor[]> {
  return isLive('bad_actors') ? get(`/bad-actors${qs({ top_n: 50, window_days: windowDays })}`) : fromMock(mock.badActors)
}

/** Demo-only: demo counts are for 180 days; scale them for the other windows. */
const scale = (f: DashboardFilters) => f.window_days / 180

// ---------- blocked attempts seen in agent streams ----------

const streamBlocked: BlockedAttempt[] = []

/** A guard `blocked` event from any agent stream becomes the red alert. */
function noteBlocked(attempt: BlockedAttempt) {
  if (streamBlocked.some((b) => b.id && b.id === attempt.id)) return
  streamBlocked.push({ ...attempt, id: attempt.id || `s-${Date.now()}`, at: attempt.at || new Date().toISOString() })
  if (!isLive('audit')) store.logAudit(attempt.tool, attempt.target, attempt.reason, 'blocked')
  emit('blocked')
}

/**
 * Wraps an agent event handler: forwards guard `blocked` events to the alert, and (if the
 * backend only marked a step as blocked) raises one from the step when the run ends.
 */
function watchBlocked(onEvent: (e: AgentEvent) => void): (e: AgentEvent) => void {
  let sawBlocked = false
  const blockedSteps = new Map<string, { tool: string; summary: string }>()
  return (e) => {
    if (e.type === 'blocked') {
      sawBlocked = true
      noteBlocked(e.attempt)
    } else if (e.type === 'step' && (e.step.status === 'blocked' || /^blocked\b/i.test(e.step.summary))) {
      blockedSteps.set(e.step.id, { tool: e.step.tool, summary: e.step.summary })
    } else if (e.type === 'done' && !sawBlocked) {
      for (const [id, b] of blockedSteps) {
        noteBlocked({ id, at: new Date().toISOString(), tool: b.tool, target: b.tool, source: 'agent run', reason: b.summary })
      }
    }
    onEvent(e)
  }
}

export const api = {
  // ---------- auth & users (local unless VITE_AUTH=server) ----------

  async login(username: string, password: string): Promise<AuthSession> {
    if (AUTH_SERVER) return post('/auth/login', { username, password })
    await delay(350)
    const user = store.signIn(username, password)
    if (!user) throw new Error('Wrong username or password')
    return { token: `local-${user.username}`, user }
  },

  /** Demo switcher: sign in as a seeded demo account without a password. */
  async switchUser(username: string): Promise<AuthSession> {
    if (!DEMO_SWITCHER) throw new Error('Switching users is turned off')
    const user = store.switchTo(username)
    if (!user) throw new Error('Only demo accounts can be switched to')
    return { token: `local-${user.username}`, user }
  },

  async logout(): Promise<void> {
    if (AUTH_SERVER) await post('/auth/logout').catch(() => undefined)
    else store.signOut()
  },

  /** Re-validates a saved session on page load. */
  async resume(saved: AuthSession): Promise<AuthSession | null> {
    if (!AUTH_SERVER) {
      const user = store.findUser(saved.user.username)
      return user ? { token: saved.token, user } : null
    }
    token = saved.token
    try {
      return { token: saved.token, user: await get<UserAccount>('/auth/me') }
    } catch {
      return null
    }
  },

  listUsers(): Promise<UserAccount[]> {
    return AUTH_SERVER ? get('/users') : fromMock(store.listUsers(), 120)
  },

  async createUser(input: NewUser): Promise<UserAccount> {
    if (AUTH_SERVER) return post('/users', input)
    await delay(300)
    return store.createUser(input)
  },

  async removeUser(username: string): Promise<void> {
    if (AUTH_SERVER) return request('DELETE', `/users/${encodeURIComponent(username)}`)
    await delay(200)
    store.removeUser(username)
  },

  demoUsernames(): { username: string; role: string }[] {
    return store.listUsers().filter((u) => u.added_by === null).map((u) => ({ username: u.username, role: u.role }))
  },

  // ---------- dashboard ----------

  /** Backend: GET /api/dashboard/summary?window_days= */
  getSummary(f: DashboardFilters): Promise<DashboardSummary> {
    if (isLive('summary')) return get(`/dashboard/summary${qs({ window_days: f.window_days })}`)
    const k = scale(f)
    const s = mock.summary
    return fromMock({
      ...s,
      window_days: f.window_days,
      failure_events: Math.round(s.failure_events * k),
      downtime_hrs: Math.round(s.downtime_hrs * k),
    })
  },

  /** Backend: GET /api/bad-actors → bad_actors.score_bad_actors(). Unit/type/criticality filters run here. */
  async getBadActors(f: DashboardFilters, topN = 10): Promise<BadActor[]> {
    const [raw, assets] = await Promise.all([loadBadActorsRaw(f.window_days), loadAssets()])
    const byTag = new Map(assets.map((a) => [a.tag, a]))
    return raw
      .map((b) => toBadActor(b, byTag.get(b.tag), 0))
      .filter((b) => !f.unit || b.location === f.unit)
      .filter((b) => !f.asset_type || b.asset_type === f.asset_type)
      .filter((b) => !f.criticality || b.criticality === f.criticality)
      .slice(0, topN)
      .map((b, i) => ({ ...b, rank: i + 1 }))
  },

  /** Backend: GET /api/failure-modes?window_days= */
  getFailureModes(f: DashboardFilters): Promise<FailureModeCount[]> {
    if (isLive('failure_modes')) return get(`/failure-modes${qs({ window_days: f.window_days })}`)
    const k = scale(f)
    return fromMock(mock.failureModes.map((m) => ({ ...m, events: Math.max(1, Math.round(m.events * k)) })))
  },

  /** Backend: GET /api/mtbf-trend (plant MTBF, trailing 90 days, by month) */
  getPlantMtbf(): Promise<MtbfPoint[]> {
    return isLive('mtbf') ? get('/mtbf-trend') : fromMock(mock.plantMtbf)
  },

  // ---------- assets ----------

  getAssets(): Promise<Asset[]> {
    return loadAssets()
  },

  /**
   * Backend: GET /api/assets/:tag/work-orders, GET /api/risk/:tag (risk.predict_risk) and
   * GET /api/assets/:tag/inspection (404 when none), plus the bad-actor list.
   */
  async getAssetDetail(tag: string): Promise<AssetDetail> {
    const assets = await loadAssets()
    const asset = assets.find((a) => a.tag === tag)
    if (!asset) throw new Error(`No asset with tag ${tag}`)
    const t = encodeURIComponent(tag)
    let riskError: string | null = null

    const [workOrders, riskRaw, badRaw, inspection] = await Promise.all([
      isLive('work_orders') ? get<BackendWorkOrder[]>(`/assets/${t}/work-orders`) : fromMock(mock.workOrders.filter((w) => w.tag === tag)),
      isLive('risk')
        ? get<BackendRisk>(`/risk/${t}`).catch((e: unknown) => ((riskError = e instanceof Error ? e.message : String(e)), null))
        : fromMock(mock.riskFor(tag)),
      loadBadActorsRaw(),
      isLive('inspections')
        ? get<Inspection>(`/assets/${t}/inspection`).catch(() => null)
        : fromMock(tag === 'P-101' ? mock.p101Inspection : null),
    ])

    const worst = badRaw.find((b) => b.tag === tag)
    return {
      asset,
      bad_actor: worst ? toBadActor(worst, asset, badRaw.indexOf(worst) + 1) : null,
      work_orders: [...workOrders].sort((a, b) => b.date.localeCompare(a.date)),
      risk: riskRaw ? toRisk(riskRaw, mock.RISK_MODEL_NOTE) : null,
      risk_error: riskError,
      readings: riskRaw ? toReadings(riskRaw.operating_condition) : [],
      latest_inspection: inspection,
    }
  },

  // ---------- upload ----------

  /** Backend: POST /api/ingest/work-orders per work-order file (manuals/scans: not yet). */
  async ingest(files: { name: string; file?: File }[], onUpdate: (files: IngestFile[]) => void): Promise<IngestSummary> {
    const items: IngestFile[] = files.map((f, i) => ({
      id: `f${Date.now()}-${i}`,
      name: f.name,
      kind: kindFor(f.name),
      status: 'queued',
    }))
    onUpdate(items.map((x) => ({ ...x })))

    if (isLive('upload')) {
      // Backend: POST /api/ingest/work-orders, one file per request (field "file").
      // Manuals and scans have no upload endpoint yet; they're indexed by scripts/agent_cli.py.
      let records = 0
      for (const item of items) {
        const f = files.find((x) => x.name === item.name)?.file
        if (item.kind !== 'work_orders' || !f) {
          item.status = 'failed'
          item.detail = item.kind === 'manual' ? 'No upload endpoint yet (run agent_cli ingest)' : 'No scan upload endpoint yet'
          onUpdate(items.map((x) => ({ ...x })))
          continue
        }
        item.status = 'parsing'
        onUpdate(items.map((x) => ({ ...x })))
        const form = new FormData()
        form.append('file', f)
        const res = await fetch('/api/ingest/work-orders', { method: 'POST', headers: headers(), body: form })
        if (res.ok) {
          const r = (await res.json()) as WorkOrderIngestResult
          records += r.rows
          item.status = 'done'
          item.detail = `${r.inserted} new · ${r.duplicates_skipped} duplicates${r.rejected ? ` · ${r.rejected} rejected` : ''}`
        } else {
          item.status = 'failed'
          item.detail = `Rejected (${res.status})`
        }
        onUpdate(items.map((x) => ({ ...x })))
      }
      emit('ingest')
      return {
        records_parsed: records,
        scans_ocrd: 0,
        manuals_indexed: 0,
      }
    }

    for (const item of items) {
      item.status = item.kind === 'scan' ? 'ocr' : 'parsing'
      onUpdate(items.map((x) => ({ ...x })))
      await delay(item.kind === 'work_orders' ? 700 : 350)
      const demo = mock.demoFiles.find((d) => d.name === item.name)
      item.status = item.kind === 'manual' ? 'indexed' : 'done'
      item.detail = demo?.detail ?? (item.kind === 'work_orders' ? 'parsed' : '1 page')
      onUpdate(items.map((x) => ({ ...x })))
    }
    store.logAudit('ingest', `${items.length} files`, 'parsed and indexed')
    emit('ingest')
    const isDemo = files.length === mock.demoFiles.length
    return isDemo
      ? { ...mock.ingestTotals }
      : {
          records_parsed: 0,
          scans_ocrd: items.filter((i) => i.kind === 'scan').length,
          manuals_indexed: items.filter((i) => i.kind === 'manual').length,
        }
  },

  demoFileNames(): string[] {
    return mock.demoFiles.map((f) => f.name)
  },

  /** Backend: POST /api/cluster → {clusters, metrics} */
  async runClustering(): Promise<ClusterRun> {
    if (isLive('upload')) return post('/cluster')
    await delay(1400)
    store.logAudit('cluster_failures', '491 work orders', '15 failure modes')
    return structuredClone(mock.clusterRun)
  },

  /** Backend (proposed): DELETE /api/data */
  async clearData(): Promise<void> {
    if (isLive('upload')) return request('DELETE', '/data')
    await delay(200)
  },

  // ---------- agent ----------

  /**
   * Streams one agent run. Backend: POST /api/agent/ask {question, tag, history} → SSE,
   * one AgentEvent JSON per `data:` line (frontend_events.FrontendStream). Returns a cancel fn.
   */
  askAgent(question: string, tag: string | null, history: ChatTurn[], onEvent: (e: AgentEvent) => void): () => void {
    const watch = watchBlocked(onEvent)
    if (!isLive('agent')) return runMockAgent(question, tag, watch)
    return streamSse('/agent/ask', { question, tag, history: history.slice(-20) }, watch)
  },

  /** Backend: GET /api/agent/status (Ollama, models, indexed manual passages). */
  getAgentStatus(): Promise<AgentStatus> {
    if (isLive('agent')) return get('/agent/status')
    return fromMock(
      {
        ollama: { reachable: true, host: 'http://ollama:11434', missing_models: [], error: null },
        manual_chunks: 38,
        manual_store_error: null,
        ready: true,
      },
      150,
    )
  },

  /** Plays the poisoned vendor bulletin. Backend (C, proposed): POST /api/privacy/injection-test, same events. */
  runInjectionTest(onEvent: (e: AgentEvent) => void): () => void {
    const watch = watchBlocked(onEvent)
    if (!isLive('privacy')) return runMockInjection(watch)
    return streamSse('/privacy/injection-test', {}, watch)
  },

  // ---------- documents ----------

  /** Edit and approve are demo-only until the backend has endpoints for them. */
  documentsEditable(): boolean {
    return !isLive('documents')
  },

  /** Backend: GET /api/documents */
  getDocuments(): Promise<DocumentItem[]> {
    return isLive('documents') ? get('/documents') : fromMock(store.listDocuments(), 150)
  },

  /** Backend: POST /api/documents/work-order {tag, issue?, requested_by} → DocumentItem (+ download_url) */
  async createWorkOrder(tag: string, issue?: string): Promise<DocumentItem> {
    if (isLive('documents')) return post('/documents/work-order', { tag, issue, requested_by: store.getSession().user })
    await delay(700)
    store.logAudit('generate_work_order', `tag=${tag}`, 'draft created')
    return store.addWorkOrder(tag)
  },

  /** Backend: POST /api/documents/bad-actor-report {top_n, requested_by} → DocumentItem (.xlsx) */
  async exportBadActorReport(): Promise<DocumentItem> {
    if (isLive('documents')) return post('/documents/bad-actor-report', { top_n: 20, requested_by: store.getSession().user })
    await delay(600)
    store.logAudit('export_report', 'type=bad_actors', 'xlsx created')
    return store.addBadActorReport()
  },

  async approveWorkOrder(docId: string): Promise<void> {
    if (isLive('documents')) throw new Error('Approving is not supported by the backend yet')
    await delay(300)
    store.approveWorkOrder(docId)
  },

  async saveWorkOrder(docId: string, draft: WorkOrderDraft): Promise<void> {
    if (isLive('documents')) throw new Error('Editing is not supported by the backend yet')
    await delay(250)
    store.updateWorkOrder(docId, draft)
  },

  /** Backend: GET /api/documents/{id}/download */
  downloadUrl(doc: DocumentItem): string | null {
    return isLive('documents') ? (doc.download_url ?? `/api/documents/${encodeURIComponent(doc.id)}/download`) : null
  },

  // ---------- privacy ----------

  /** Backend (C): GET /api/privacy/status, polled every 2 s */
  getPrivacyStatus(): Promise<PrivacyStatus> {
    if (isLive('privacy')) return get('/privacy/status')
    return fromMock(
      {
        external_connections: 0,
        network_mode: 'none',
        redactions: 12,
        checked_at: new Date().toISOString(),
        connections: [
          { local: '127.0.0.1:8000', remote: '127.0.0.1:51420', process: 'API (uvicorn)', external: false },
          { local: '127.0.0.1:11434', remote: '127.0.0.1:52210', process: 'Models (Ollama)', external: false },
          { local: '127.0.0.1:5173', remote: '127.0.0.1:53108', process: 'Web UI', external: false },
        ],
      },
      120,
    )
  },

  /** Blocked attempts: from the backend (C, proposed) plus anything blocked in this browser's agent runs. */
  async getBlockedAttempts(): Promise<BlockedAttempt[]> {
    const server = isLive('privacy') ? await get<BlockedAttempt[]>('/privacy/blocked').catch(() => []) : await fromMock(store.listBlocked(), 80)
    const local = isLive('privacy') ? [] : streamBlocked // live: the server list already has them
    return [...local, ...server].sort((a, b) => b.at.localeCompare(a.at))
  },

  /** Backend (proposed): GET /api/audit-log → audit_log rows */
  async getAuditLog(): Promise<AuditEntry[]> {
    if (!isLive('audit')) return fromMock(store.listAudit(), 120)
    return (await get<BackendAuditRow[]>('/audit-log')).map(toAuditEntry)
  },
}

function kindFor(name: string): IngestKind {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') return 'work_orders'
  if (ext === 'pdf') return 'manual'
  return 'scan'
}

/**
 * POST + read a text/event-stream response. /agent/ask sends data-only events, one JSON
 * AgentEvent per `data:` line; named events (`event: x`) are passed as {type: x, ...data}.
 * CRLF line breaks and `: ping` comments are handled.
 */
function streamSse(path: string, body: unknown, onEvent: (e: AgentEvent) => void): () => void {
  const ctrl = new AbortController()
  void (async () => {
    try {
      const res = await fetch(`/api${path}`, {
        method: 'POST',
        headers: headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) throw new Error(`${path} failed: ${res.status}`)
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += value.replace(/\r\n?/g, '\n')
        let cut: number
        while ((cut = buf.indexOf('\n\n')) !== -1) {
          const block = buf.slice(0, cut)
          buf = buf.slice(cut + 2)
          let name = ''
          const data: string[] = []
          for (const line of block.split('\n')) {
            if (!line || line.startsWith(':')) continue
            const i = line.indexOf(':')
            const field = i === -1 ? line : line.slice(0, i)
            const val = i === -1 ? '' : line.slice(i + 1).replace(/^ /, '')
            if (field === 'event') name = val
            else if (field === 'data') data.push(val)
          }
          if (!data.length) continue
          try {
            const parsed = JSON.parse(data.join('\n')) as Record<string, unknown>
            onEvent((name && name !== 'message' ? { type: name, ...parsed } : parsed) as AgentEvent)
          } catch {
            /* skip a malformed event rather than end the run */
          }
        }
      }
      emit('audit')
      emit('documents')
    } catch (e) {
      if (!ctrl.signal.aborted) onEvent({ type: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  })()
  return () => ctrl.abort()
}
