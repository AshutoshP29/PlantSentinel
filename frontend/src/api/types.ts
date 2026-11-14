// Types used by the screens, plus the raw shapes the backend already produces.
// Dates are ISO strings (YYYY-MM-DD), months are YYYY-MM, money is in rupees, MTBF in days.
//
// The Backend* types mirror the teammates' code exactly (read-only reference):
//   assets / work_orders / audit_log tables   backend/app/db.py
//   bad actors                                backend/app/analytics/bad_actors.py  get_bad_actors()
//   risk                                      backend/app/analytics/risk.py        predict_risk()
// src/api/adapters.ts turns them into the screen types below.

// =====================================================================================
// Backend shapes (as returned by the teammates' code)
// =====================================================================================

export type CriticalityCode = 'A' | 'B' | 'C'
export type BackendAssetType = 'pump' | 'compressor' | 'heat_exchanger' | 'motor'

/** Row of the `assets` table. */
export interface BackendAsset {
  tag: string
  type: BackendAssetType
  location: string
  criticality: CriticalityCode
  install_date: string
}

/** Row of `work_orders` joined with `failure_modes.name`. */
export interface BackendWorkOrder {
  id: string
  tag: string
  date: string
  description: string
  action_taken: string
  downtime_hrs: number
  cost_inr: number
  failure_mode: string | null
}

/** One (asset, failure mode) pair from bad_actors.get_bad_actors(). */
export interface BackendBadActor {
  tag: string
  failure_mode: string
  criticality: CriticalityCode
  count_180d: number
  count_total: number
  last_event: string
  mtbf_current_days: number | null
  mtbf_previous_days: number | null
  /** 1 - current/previous; 0.66 means MTBF fell 66% */
  mtbf_drop_pct: number
  cost_180d: number
  cost_prev_180d: number
  cost_trend_pct: number | null
  downtime_180d: number
  /** count_180d × criticality weight (A3/B2/C1) × (1 + drop) */
  bad_actor_score: number
  flagged: boolean
}

export interface BackendRiskReason {
  feature: string
  label: string
  value: number
  typical: number
  unit: string
  /** SHAP contribution; positive pushes risk up */
  impact: number
  text: string
}

/** risk.predict_risk(tag) */
export interface BackendRisk {
  tag: string
  risk_score: number // 0–1
  risk_level: 'high' | 'medium' | 'low'
  reasons: BackendRiskReason[]
  operating_condition: {
    air_temp_k: number
    process_temp_k: number
    rpm: number
    torque_nm: number
    tool_wear_min: number
    duty_class: string
  }
  source: string
}

/** Row of the `audit_log` table. */
export interface BackendAuditRow {
  id: number
  ts: string
  user: string
  role: string
  action: string
  tool: string
  input: string
  output: string
  status: 'allowed' | 'blocked' | 'error'
}

// =====================================================================================
// Screen types
// =====================================================================================

export type Criticality = 'High' | 'Medium' | 'Low'
export type AssetType = 'Pump' | 'Compressor' | 'Heat exchanger' | 'Motor'

export interface Asset {
  tag: string
  name: string // display name, e.g. "Feed pump" (falls back to the type)
  type: AssetType
  location: string // plant unit, e.g. "CDU-1"
  criticality: Criticality
  install_date: string
}

// ---------- Dashboard ----------

export interface DashboardFilters {
  window_days: 90 | 180 | 365
  unit?: string
  asset_type?: AssetType
  criticality?: Criticality
}

/** GET /api/dashboard/summary (proposed; not in the backend yet) */
export interface DashboardSummary {
  site: string
  assets_monitored: number
  work_orders_parsed: number
  failure_events: number
  bad_actors_flagged: number
  plant_mtbf_days: number
  /** vs previous window; negative = worse. Omitted when unknown. */
  plant_mtbf_change_pct?: number
  downtime_hrs: number
  window_days: number
  as_of: string
}

/** recurring = 3+ events in 180 d · review = MTBF fell > 40% · watch = not flagged */
export type BadActorStatus = 'recurring' | 'review' | 'watch'

export interface BadActor {
  rank: number
  tag: string
  name: string
  asset_type: AssetType
  location: string
  criticality: Criticality
  failure_mode: string
  events: number
  events_total: number
  last_event: string
  mtbf_days: number | null
  mtbf_prev_days: number | null
  /** % change, current vs previous (negative = worse); 0 when either is unknown */
  mtbf_change_pct: number
  cost_inr: number
  downtime_hrs: number
  /** backend bad_actor_score (unbounded; compare within the list) */
  score: number
  flagged: boolean
  status: BadActorStatus
}

/** GET /api/failure-modes (proposed): events per failure mode in the window */
export interface FailureModeCount {
  id: number
  name: string
  events: number
  is_noise?: boolean // HDBSCAN noise bucket ("Unclassified")
}

/** GET /api/mtbf-trend (proposed): plant MTBF by month */
export interface MtbfPoint {
  month: string
  mtbf_days: number
}

// ---------- Asset detail ----------

export type WorkOrder = BackendWorkOrder

export type TimelineKind = 'failure' | 'inspection' | 'maintenance'

export interface TimelineEvent {
  date: string
  label: string
  kind: TimelineKind
}

export interface RiskFactor {
  feature: string
  label: string
  /** SHAP contribution; positive pushes risk up */
  impact: number
  value: number
  typical: number
  unit: string
  text: string
}

export interface RiskPrediction {
  score: number // 0–100
  level: 'high' | 'medium' | 'low'
  model_note: string
  factors: RiskFactor[]
}

export interface Reading {
  key: 'process_temp' | 'speed' | 'torque' | 'wear'
  label: string
  value: number
  unit: string
}

export interface InspectionFinding {
  item: string
  result: string
  flagged: boolean
}

export interface Inspection {
  id: string
  tag: string
  date: string
  inspector: string
  report_no: string
  page: number
  pages: number
  findings: InspectionFinding[]
  file_path: string
}

export interface AssetDetail {
  asset: Asset
  /** the asset's worst bad-actor row, if it has one */
  bad_actor: BadActor | null
  work_orders: WorkOrder[]
  risk: RiskPrediction | null
  /** why risk is missing, e.g. the backend's 503 "Risk model not trained…" */
  risk_error?: string | null
  readings: Reading[]
  latest_inspection: Inspection | null
}

// ---------- Upload ----------

export type IngestKind = 'work_orders' | 'manual' | 'scan'
export type IngestStatus = 'queued' | 'parsing' | 'ocr' | 'indexed' | 'done' | 'failed'

export interface IngestFile {
  id: string
  name: string
  kind: IngestKind
  status: IngestStatus
  detail?: string
}

export interface IngestSummary {
  records_parsed: number
  scans_ocrd: number
  manuals_indexed: number
}

/** POST /api/ingest/work-orders (ingestion/work_orders.py) */
export interface WorkOrderIngestResult {
  file: string
  rows: number
  inserted: number
  duplicates_skipped: number
  rejected: number
  errors: string[]
  new_assets: string[]
}

export interface ClusterPreview {
  name: string
  events: number
  samples: string[] // raw work-order text
}

export interface ClusterRun {
  clusters: ClusterPreview[]
  /** from models/metrics.json "clustering" */
  metrics: { n_clusters?: number; n_failure_modes?: number; silhouette?: number | null; ari_vs_truth?: number; n_work_orders?: number }
}

// ---------- Agent ----------

// Mirrors backend/app/agent/graph.py EVENT_TYPES and backend/app/api/agent.py exactly.
// POST /api/agent/chat {message, history} streams named SSE events: `event: <type>`,
// `data: <json payload>`.

/** One retrieved manual passage; the answer cites it as [S1], [S2] … */
export interface AgentSource {
  ref: string // "S1"
  title: string
  source: string // file name, e.g. "centrifugal_pump_om_manual.md"
  page: number
  section: string
  score: number
  snippet: string
}

export interface AgentWorkOrder {
  work_order_id: string
  tag: string
  priority: string
  file: string
  download_url: string // e.g. /api/agent/work-orders/<file>.docx
}

export type AgentStreamEvent =
  | { type: 'run_started'; data: { run_id: string; question: string } }
  | { type: 'status'; data: { stage: string; message: string } }
  | { type: 'tool_started'; data: { call_id: string; tool: string; args: Record<string, unknown> } }
  | { type: 'tool_completed'; data: { call_id: string; tool: string; status: string; summary: string } }
  | { type: 'sources'; data: { sources: AgentSource[] } }
  | { type: 'work_order'; data: AgentWorkOrder }
  | { type: 'answer'; data: { text: string; cited_refs: string[]; unknown_refs: string[]; work_orders: AgentWorkOrder[] } }
  | { type: 'error'; data: { message: string } }
  | { type: 'done'; data: { run_id: string; iterations: number; elapsed_s: number } }

export type AgentEventType = AgentStreamEvent['type']

/** One prior turn, sent as `history` with the next message (max 20). */
export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

/** GET /api/agent/status */
export interface AgentStatus {
  ollama: { reachable: boolean; host: string; missing_models: string[]; error: string | null }
  manual_chunks: number
  manual_store_error: string | null
  ready: boolean
}

// ----- screen-side agent types -----

export type AgentStepStatus = 'running' | 'done' | 'blocked' | 'error'

export interface AgentStep {
  id: string // call_id
  tool: string
  args: Record<string, unknown>
  summary: string
  status: AgentStepStatus
  started_at: number
  duration_ms?: number
}

// ---------- Documents ----------

export type DocKind = 'work_order' | 'bad_actor_report'

export interface WorkOrderDraft {
  wo_number: string
  tag: string
  asset_name: string
  priority: 'High' | 'Medium' | 'Low'
  problem: string
  suspected_cause: string
  recommended_steps: string
  parts: string
  safety: string
  references: string
  requested_by: string
  date: string
  status: 'draft' | 'approved'
  approved_by?: string
}

export interface DocumentItem {
  id: string
  file_name: string
  kind: DocKind
  tag: string | null // null = all assets
  created_by: string
  created_at: string // ISO datetime
  work_order?: WorkOrderDraft
}

// ---------- Privacy ----------

export interface Connection {
  local: string
  remote: string
  process: string
  external: boolean
}

export interface PrivacyStatus {
  external_connections: number
  network_mode: string
  redactions: number
  checked_at: string // ISO datetime
  connections: Connection[]
}

export interface BlockedAttempt {
  id: string
  at: string // ISO datetime
  tool: string
  target: string
  source: string
  reason: string
}

// ---------- Accounts ----------

/** GET /api/users (proposed) */
export interface UserAccount {
  username: string
  name: string
  role: string // role id, see lib/roles.ts
  added_by: string | null // username of the person who added them
  created_at: string // ISO datetime
}

/** POST /api/auth/login (proposed) → token + the signed-in user */
export interface AuthSession {
  token: string
  user: UserAccount
}

export interface NewUser {
  name: string
  username: string
  password: string
  role: string
}

/** Same values as the backend audit_log.status column. */
export type AuditStatus = BackendAuditRow['status']

export interface AuditEntry {
  id: string
  at: string // ISO datetime
  user: string
  role: string // role id, see lib/roles.ts
  tool: string
  input: string
  output: string
  status: AuditStatus
}
