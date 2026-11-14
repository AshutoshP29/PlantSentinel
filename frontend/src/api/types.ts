// Shared API contract between the frontend and the FastAPI backend.
// Field names follow the SQLite schema in docs/PROJECT_BRIEF.md (section 9).
// Dates are ISO strings (YYYY-MM-DD), months are YYYY-MM, money is in rupees.

export type Criticality = 'High' | 'Medium' | 'Low'
export type AssetType = 'Pump' | 'Compressor' | 'Heat exchanger' | 'Motor'

export interface Asset {
  tag: string
  name: string // e.g. "Feed pump"
  type: AssetType
  location: string // plant unit, e.g. "Unit 02"
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

/** GET /api/dashboard/summary */
export interface DashboardSummary {
  site: string
  assets_monitored: number
  work_orders_parsed: number
  failure_events: number
  bad_actors_flagged: number
  plant_mtbf_days: number
  plant_mtbf_change_pct: number // vs previous window; negative = worse
  downtime_hrs: number
  window_days: number
  as_of: string
}

/** recurring = 3+ events of one mode in 180 d; review = MTBF fell > 40%; watch = neither */
export type BadActorStatus = 'recurring' | 'review' | 'watch'

/** GET /api/bad-actors?top_n=10&window_days=180&unit=&asset_type=&criticality= */
export interface BadActor {
  rank: number
  tag: string
  name: string
  asset_type: AssetType
  location: string
  criticality: Criticality
  failure_mode: string
  events: number
  mtbf_days: number
  mtbf_prev_days: number
  mtbf_change_pct: number
  cost_inr: number
  downtime_hrs: number
  score: number // 0–100
  status: BadActorStatus
}

/** GET /api/failure-modes?window_days=180 */
export interface FailureModeCount {
  id: number
  name: string
  events: number
  is_noise?: boolean // HDBSCAN noise bucket
}

/** GET /api/mtbf-trend?tag=P-101 (omit tag for the plant average) */
export interface MtbfPoint {
  month: string
  mtbf_days: number
}

// ---------- Asset detail ----------

export interface WorkOrder {
  id: string
  tag: string
  date: string
  description: string // original free text, untouched
  action_taken: string
  downtime_hrs: number
  cost_inr: number
  failure_mode: string | null
}

export type TimelineKind = 'failure' | 'inspection' | 'maintenance'

export interface TimelineEvent {
  date: string
  label: string
  kind: TimelineKind
}

export interface ShapFactor {
  feature: string
  /** SHAP contribution; positive pushes risk up */
  value: number
}

export interface RiskPrediction {
  score: number // 0–100
  predicted_type: string
  model_note: string
  factors: ShapFactor[]
}

export interface Reading {
  key: 'temperature' | 'speed' | 'torque' | 'tool_wear'
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

/** GET /api/assets/:tag */
export interface AssetDetail {
  asset: Asset
  score: number
  status: BadActorStatus
  timeline: TimelineEvent[]
  work_orders: WorkOrder[]
  mtbf_trend: MtbfPoint[]
  risk: RiskPrediction
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

export interface ClusterPreview {
  name: string
  events: number
  samples: string[] // raw work-order text
}

// ---------- Agent ----------

export interface Citation {
  id: number
  kind: 'inspection' | 'manual' | 'work_orders'
  label: string // e.g. "Inspection · p. 2"
  title: string // e.g. "Inspection report · page 2"
  quote: string
}

export type AgentStepStatus = 'running' | 'done' | 'blocked' | 'error'

export interface AgentStep {
  id: string
  tool: string
  summary: string
  status: AgentStepStatus
  duration_ms?: number
}

/**
 * Events streamed by POST /api/agent/ask (Server-Sent Events, one JSON per `data:` line).
 * step   → a tool call started or finished (same id = update)
 * token  → a chunk of answer text (markdown-lite: "## " headings, [n] citation refs)
 * done   → final citations + optional suggested action
 * blocked→ the guard stopped a tool call
 */
export type AgentEvent =
  | { type: 'step'; step: AgentStep }
  | { type: 'token'; text: string }
  | { type: 'done'; citations: Citation[]; can_draft_work_order: boolean }
  | { type: 'blocked'; attempt: BlockedAttempt }
  | { type: 'error'; message: string }

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

export type AuditStatus = 'allowed' | 'blocked' | 'denied'

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
