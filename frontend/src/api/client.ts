// Every screen gets its data through this file.
// Demo mode is on by default; set VITE_USE_MOCK=false in frontend/.env.local to use the
// FastAPI backend (see frontend/README.md for the endpoints). Raw backend shapes go
// through adapters.ts in both modes, so the screens never see raw fields.

import { toAsset, toAuditEntry, toBadActor, toReadings, toRisk } from './adapters'
import { runMockAgent, runMockInjection } from './agentMock'
import { emit } from './events'
import * as mock from './mock'
import * as store from './store'
import type {
  AgentEvent,
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
} from './types'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
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

/** Every request carries the token plus role/user so the backend guard can enforce and audit. */
function headers(extra: Record<string, string> = {}): Record<string, string> {
  const { role, user } = store.getSession()
  const h: Record<string, string> = { Accept: 'application/json', 'X-Role': role, 'X-User': user, ...extra }
  if (token) h.Authorization = `Bearer ${token}`
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
      detail = ((await res.json()) as { detail?: string }).detail ?? detail
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
  assetCache ??= (USE_MOCK ? fromMock(mock.assets, 100) : get<BackendAsset[]>('/assets'))
    .then((rows) => rows.map(toAsset))
    .catch((e: unknown) => {
      assetCache = null
      throw e
    })
  return assetCache
}

async function loadBadActorsRaw(windowDays = 180): Promise<BackendBadActor[]> {
  return USE_MOCK ? fromMock(mock.badActors) : get(`/bad-actors${qs({ top_n: 50, window_days: windowDays })}`)
}

/** Mock-only: demo counts are for 180 days; scale them for the other windows. */
const scale = (f: DashboardFilters) => f.window_days / 180

export const api = {
  // ---------- auth & users ----------

  /** Backend (proposed): POST /api/auth/login {username, password} → AuthSession */
  async login(username: string, password: string): Promise<AuthSession> {
    if (!USE_MOCK) return post('/auth/login', { username, password })
    await delay(350)
    const user = store.signIn(username, password)
    if (!user) throw new Error('Wrong username or password')
    return { token: `demo-${user.username}`, user }
  },

  /** Backend (proposed): POST /api/auth/logout */
  async logout(): Promise<void> {
    if (USE_MOCK) store.signOut()
    else await post('/auth/logout').catch(() => undefined)
  },

  /** Re-validates a saved session on page load. Backend (proposed): GET /api/auth/me → UserAccount */
  async resume(saved: AuthSession): Promise<AuthSession | null> {
    if (USE_MOCK) {
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

  /** Backend (proposed): GET /api/users */
  listUsers(): Promise<UserAccount[]> {
    return USE_MOCK ? fromMock(store.listUsers(), 120) : get('/users')
  },

  /** Backend (proposed): POST /api/users — must apply the same hierarchy rule (lib/roles.ts) */
  async createUser(input: NewUser): Promise<UserAccount> {
    if (!USE_MOCK) return post('/users', input)
    await delay(300)
    return store.createUser(input)
  },

  /** Backend (proposed): DELETE /api/users/:username */
  async removeUser(username: string): Promise<void> {
    if (!USE_MOCK) return request('DELETE', `/users/${encodeURIComponent(username)}`)
    await delay(200)
    store.removeUser(username)
  },

  // ---------- dashboard ----------

  /** Backend (proposed): GET /api/dashboard/summary?window_days= */
  getSummary(f: DashboardFilters): Promise<DashboardSummary> {
    if (!USE_MOCK) return get(`/dashboard/summary${qs({ window_days: f.window_days })}`)
    const k = scale(f)
    const s = mock.summary
    return fromMock({
      ...s,
      window_days: f.window_days,
      failure_events: Math.round(s.failure_events * k),
      downtime_hrs: Math.round(s.downtime_hrs * k),
    })
  },

  /** Backend: GET /api/bad-actors → bad_actors.get_bad_actors(). Unit/type/criticality filters run here. */
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

  /** Backend (proposed): GET /api/failure-modes?window_days= */
  getFailureModes(f: DashboardFilters): Promise<FailureModeCount[]> {
    if (!USE_MOCK) return get(`/failure-modes${qs({ window_days: f.window_days })}`)
    const k = scale(f)
    return fromMock(mock.failureModes.map((m) => ({ ...m, events: Math.max(1, Math.round(m.events * k)) })))
  },

  /** Backend (proposed): GET /api/mtbf-trend */
  getPlantMtbf(): Promise<MtbfPoint[]> {
    return USE_MOCK ? fromMock(mock.plantMtbf) : get('/mtbf-trend')
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

    const [workOrders, riskRaw, badRaw, inspection] = await Promise.all([
      USE_MOCK
        ? fromMock(mock.workOrders.filter((w) => w.tag === tag))
        : get<BackendWorkOrder[]>(`/assets/${encodeURIComponent(tag)}/work-orders`),
      USE_MOCK
        ? fromMock(mock.riskFor(tag))
        : get<BackendRisk>(`/risk/${encodeURIComponent(tag)}`).catch(() => null),
      loadBadActorsRaw(),
      USE_MOCK
        ? fromMock(tag === 'P-101' ? mock.p101Inspection : null)
        : get<Inspection>(`/assets/${encodeURIComponent(tag)}/inspection`).catch(() => null),
    ])

    const worst = badRaw.find((b) => b.tag === tag)
    return {
      asset,
      bad_actor: worst ? toBadActor(worst, asset, badRaw.indexOf(worst) + 1) : null,
      work_orders: [...workOrders].sort((a, b) => b.date.localeCompare(a.date)),
      risk: riskRaw ? toRisk(riskRaw, mock.RISK_MODEL_NOTE) : null,
      readings: riskRaw ? toReadings(riskRaw.operating_condition) : [],
      latest_inspection: inspection,
    }
  },

  // ---------- upload ----------

  /**
   * Ingests files and reports per-file progress through onUpdate.
   * Backend (proposed): POST /api/ingest (multipart, field "files") → { files: IngestFile[], summary }.
   */
  async ingest(files: { name: string; file?: File }[], onUpdate: (files: IngestFile[]) => void): Promise<IngestSummary> {
    const items: IngestFile[] = files.map((f, i) => ({
      id: `f${Date.now()}-${i}`,
      name: f.name,
      kind: kindFor(f.name),
      status: 'queued',
    }))
    onUpdate(items.map((x) => ({ ...x })))

    if (!USE_MOCK) {
      const form = new FormData()
      files.forEach((f) => f.file && form.append('files', f.file))
      const res = await fetch('/api/ingest', { method: 'POST', headers: headers(), body: form })
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
      const out = (await res.json()) as { files: IngestFile[]; summary: IngestSummary }
      onUpdate(out.files)
      emit('ingest')
      return out.summary
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

  /** Backend (proposed): POST /api/cluster → ClusterRun (cluster.recluster + models/metrics.json) */
  async runClustering(): Promise<ClusterRun> {
    if (!USE_MOCK) return post('/cluster')
    await delay(1400)
    store.logAudit('cluster_failures', '491 work orders', '15 failure modes')
    return structuredClone(mock.clusterRun)
  },

  /** Backend (proposed): DELETE /api/data */
  async clearData(): Promise<void> {
    if (!USE_MOCK) return request('DELETE', '/data')
    await delay(200)
  },

  // ---------- agent ----------

  /** Streams agent events (SSE). Backend: POST /api/agent/ask {question, tag}. Returns a cancel fn. */
  askAgent(question: string, tag: string | null, onEvent: (e: AgentEvent) => void): () => void {
    if (USE_MOCK) return runMockAgent(question, onEvent)
    return streamSse('/agent/ask', { question, tag }, onEvent)
  },

  /** Plays the poisoned vendor PDF scenario. Backend (proposed): POST /api/privacy/injection-test (SSE). */
  runInjectionTest(onEvent: (e: AgentEvent) => void): () => void {
    if (USE_MOCK) return runMockInjection(onEvent)
    return streamSse('/privacy/injection-test', {}, onEvent)
  },

  // ---------- documents ----------

  getDocuments(): Promise<DocumentItem[]> {
    return USE_MOCK ? fromMock(store.listDocuments(), 150) : get('/documents')
  },

  /** Backend (proposed): POST /api/documents/work-order {tag} → DocumentItem (writes the .docx) */
  async createWorkOrder(tag: string): Promise<DocumentItem> {
    if (!USE_MOCK) return post('/documents/work-order', { tag })
    await delay(700)
    store.logAudit('generate_work_order', `tag=${tag}`, 'draft created')
    return store.addWorkOrder(tag)
  },

  /** Backend (proposed): POST /api/documents/bad-actor-report → DocumentItem (writes the .xlsx) */
  async exportBadActorReport(): Promise<DocumentItem> {
    if (!USE_MOCK) return post('/documents/bad-actor-report')
    await delay(600)
    store.logAudit('export_report', 'type=bad_actors', 'xlsx created')
    return store.addBadActorReport()
  },

  /** Backend (proposed): POST /api/documents/:id/approve */
  async approveWorkOrder(docId: string): Promise<void> {
    if (!USE_MOCK) {
      await post(`/documents/${docId}/approve`)
      return
    }
    await delay(300)
    store.approveWorkOrder(docId)
  },

  /** Backend (proposed): PUT /api/documents/:id/work-order */
  async saveWorkOrder(docId: string, draft: WorkOrderDraft): Promise<void> {
    if (!USE_MOCK) {
      await request('PUT', `/documents/${docId}/work-order`, draft)
      return
    }
    await delay(250)
    store.updateWorkOrder(docId, draft)
  },

  /** Backend (proposed): GET /api/documents/:id/download streams the file. */
  downloadUrl(doc: DocumentItem): string | null {
    return USE_MOCK ? null : `/api/documents/${doc.id}/download`
  },

  // ---------- privacy ----------

  getPrivacyStatus(): Promise<PrivacyStatus> {
    if (!USE_MOCK) return get('/privacy/status')
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

  getBlockedAttempts(): Promise<BlockedAttempt[]> {
    return USE_MOCK ? fromMock(store.listBlocked(), 80) : get('/privacy/blocked')
  },

  /** Backend (proposed): GET /api/audit-log → audit_log rows */
  async getAuditLog(): Promise<AuditEntry[]> {
    if (USE_MOCK) return fromMock(store.listAudit(), 120)
    return (await get<BackendAuditRow[]>('/audit-log')).map(toAuditEntry)
  },
}

function kindFor(name: string): IngestKind {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') return 'work_orders'
  if (ext === 'pdf') return 'manual'
  return 'scan'
}

/** POST + read a text/event-stream response, calling onEvent per JSON `data:` line. */
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
        buf += value
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const evt = JSON.parse(line.slice(5).trim()) as AgentEvent
          if (evt.type === 'blocked') emit('blocked')
          onEvent(evt)
        }
      }
      emit('audit')
    } catch (e) {
      if (!ctrl.signal.aborted) onEvent({ type: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  })()
  return () => ctrl.abort()
}
