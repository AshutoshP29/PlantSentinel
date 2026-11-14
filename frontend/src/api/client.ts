// Every screen gets its data through this file.
// Demo mode is on by default; set VITE_USE_MOCK=false in frontend/.env.local
// once the FastAPI backend serves these endpoints (see frontend/README.md).

import { runMockAgent, runMockInjection } from './agentMock'
import { emit } from './events'
import * as mock from './mock'
import * as store from './store'
import type {
  AgentEvent,
  AssetDetail,
  AuditEntry,
  BadActor,
  BlockedAttempt,
  ClusterPreview,
  DashboardFilters,
  DashboardSummary,
  DocumentItem,
  FailureModeCount,
  IngestFile,
  IngestKind,
  IngestSummary,
  MtbfPoint,
  PrivacyStatus,
  WorkOrderDraft,
} from './types'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
export const SITE = mock.SITE

const LATENCY = 300
const delay = (ms = LATENCY) => new Promise((r) => setTimeout(r, ms))
async function fromMock<T>(data: T, ms = LATENCY): Promise<T> {
  await delay(ms)
  return structuredClone(data)
}

/** Role/user travel with every request so the backend guard can enforce and log them. */
function headers(extra: Record<string, string> = {}): Record<string, string> {
  const { role, user } = store.getSession()
  return { Accept: 'application/json', 'X-Role': role, 'X-User': user, ...extra }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: headers(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${method} /api${path} failed: ${res.status} ${res.statusText}`)
  return (await res.json()) as T
}
const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body)

function qs(params: Record<string, string | number | undefined>): string {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  return p.length ? `?${p.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')}` : ''
}

/** Mock-only: the demo numbers are for 180 days; scale counts for other windows. */
const scale = (f: DashboardFilters) => f.window_days / 180

export function setSessionRole(role: store.SessionRole) {
  store.setSession(role)
}
export const currentUser = () => store.getSession().user

export const api = {
  // ---------- dashboard ----------

  getSummary(f: DashboardFilters): Promise<DashboardSummary> {
    if (!USE_MOCK) return get(`/dashboard/summary${qs({ ...f })}`)
    const k = scale(f)
    const s = mock.summary
    return fromMock({
      ...s,
      window_days: f.window_days,
      failure_events: Math.round(s.failure_events * k),
      downtime_hrs: Math.round(s.downtime_hrs * k),
    })
  },

  getBadActors(f: DashboardFilters, topN = 10): Promise<BadActor[]> {
    if (!USE_MOCK) return get(`/bad-actors${qs({ top_n: topN, ...f })}`)
    const k = scale(f)
    const rows = mock.badActors
      .filter((b) => !f.unit || b.location === f.unit)
      .filter((b) => !f.asset_type || b.asset_type === f.asset_type)
      .filter((b) => !f.criticality || b.criticality === f.criticality)
      .slice(0, topN)
      .map((b, i) => ({
        ...b,
        rank: i + 1,
        events: Math.max(1, Math.round(b.events * k)),
        cost_inr: Math.round(b.cost_inr * k),
        downtime_hrs: Math.round(b.downtime_hrs * k),
      }))
    return fromMock(rows)
  },

  getFailureModes(f: DashboardFilters): Promise<FailureModeCount[]> {
    if (!USE_MOCK) return get(`/failure-modes${qs({ ...f })}`)
    const k = scale(f)
    return fromMock(mock.failureModes.map((m) => ({ ...m, events: Math.max(1, Math.round(m.events * k)) })))
  },

  getPlantMtbf(): Promise<MtbfPoint[]> {
    return USE_MOCK ? fromMock(mock.plantMtbf) : get('/mtbf-trend')
  },

  // ---------- assets ----------

  getAssets(): Promise<typeof mock.assets> {
    return USE_MOCK ? fromMock(mock.assets, 100) : get('/assets')
  },

  async getAssetDetail(tag: string): Promise<AssetDetail> {
    if (!USE_MOCK) return get(`/assets/${encodeURIComponent(tag)}`)
    const d = tag === 'P-101' ? mock.p101Detail : mock.genericDetail(tag)
    if (!d) {
      await delay()
      throw new Error(`No asset with tag ${tag}`)
    }
    return fromMock(d)
  },

  // ---------- upload ----------

  /**
   * Ingests files and reports per-file progress through onUpdate.
   * Backend: POST /api/ingest (multipart, field "files") → IngestFile[] + IngestSummary.
   */
  async ingest(
    files: { name: string; file?: File }[],
    onUpdate: (files: IngestFile[]) => void,
  ): Promise<IngestSummary> {
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
      item.detail = demo?.detail ?? (item.kind === 'work_orders' ? '47 records' : '1 page')
      onUpdate(items.map((x) => ({ ...x })))
    }
    store.logAudit('ingest', `${items.length} files`, 'parsed and indexed')
    emit('ingest')
    const isDemo = files.length === mock.demoFiles.length
    return isDemo
      ? { ...mock.ingestTotals }
      : {
          records_parsed: items.filter((i) => i.kind === 'work_orders').length * 47,
          scans_ocrd: items.filter((i) => i.kind === 'scan').length,
          manuals_indexed: items.filter((i) => i.kind === 'manual').length,
        }
  },

  demoFileNames(): string[] {
    return mock.demoFiles.map((f) => f.name)
  },

  /** Backend: POST /api/cluster → ClusterPreview[] (top clusters with sample raw texts) */
  async runClustering(): Promise<ClusterPreview[]> {
    if (!USE_MOCK) return post('/cluster')
    await delay(1400)
    store.logAudit('cluster_failures', '512 work orders', `${mock.failureModes.length - 1} failure modes`)
    return structuredClone(mock.clusterPreview)
  },

  /** Backend: DELETE /api/data */
  async clearData(): Promise<void> {
    if (!USE_MOCK) {
      await request('DELETE', '/data')
      return
    }
    await delay(200)
  },

  // ---------- agent ----------

  /**
   * Streams agent events. Backend: POST /api/agent/ask {question, tag?} answering
   * with text/event-stream, one AgentEvent JSON per `data:` line. Returns a cancel fn.
   */
  askAgent(question: string, tag: string | null, onEvent: (e: AgentEvent) => void): () => void {
    if (USE_MOCK) return runMockAgent(question, onEvent)
    return streamSse('/agent/ask', { question, tag }, onEvent)
  },

  /** Plays the poisoned vendor PDF scenario. Backend: POST /api/privacy/injection-test (SSE). */
  runInjectionTest(onEvent: (e: AgentEvent) => void): () => void {
    if (USE_MOCK) return runMockInjection(onEvent)
    return streamSse('/privacy/injection-test', {}, onEvent)
  },

  // ---------- documents ----------

  getDocuments(): Promise<DocumentItem[]> {
    return USE_MOCK ? fromMock(store.listDocuments(), 150) : get('/documents')
  },

  /** Backend: POST /api/documents/work-order {tag} → DocumentItem (writes the .docx) */
  async createWorkOrder(tag: string): Promise<DocumentItem> {
    if (!USE_MOCK) return post('/documents/work-order', { tag })
    await delay(700)
    store.logAudit('generate_work_order', `tag=${tag}`, 'draft created')
    return store.addWorkOrder(tag)
  },

  /** Backend: POST /api/documents/bad-actor-report → DocumentItem (writes the .xlsx) */
  async exportBadActorReport(): Promise<DocumentItem> {
    if (!USE_MOCK) return post('/documents/bad-actor-report')
    await delay(600)
    store.logAudit('export_report', 'type=bad_actors', 'xlsx created')
    return store.addBadActorReport()
  },

  /** Backend: POST /api/documents/:id/approve */
  async approveWorkOrder(docId: string): Promise<void> {
    if (!USE_MOCK) {
      await post(`/documents/${docId}/approve`)
      return
    }
    await delay(300)
    store.approveWorkOrder(docId)
  },

  /** Backend: PUT /api/documents/:id/work-order */
  async saveWorkOrder(docId: string, draft: WorkOrderDraft): Promise<void> {
    if (!USE_MOCK) {
      await request('PUT', `/documents/${docId}/work-order`, draft)
      return
    }
    await delay(250)
    store.updateWorkOrder(docId, draft)
  },

  /** Backend: GET /api/documents/:id/download streams the file. */
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

  getAuditLog(): Promise<AuditEntry[]> {
    return USE_MOCK ? fromMock(store.listAudit(), 120) : get('/audit-log')
  },

  /** Records a client-side permission denial (backend logs its own). */
  logDenied(tool: string, input: string): void {
    if (USE_MOCK) store.logAudit(tool, input, 'Not allowed for this role', 'denied')
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
