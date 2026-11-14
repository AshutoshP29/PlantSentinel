// Turns the backend's raw shapes (see Backend* in types.ts) into what the screens use.
// Used for both the live API and demo mode, so the screens never see raw backend fields.

import type {
  Asset,
  AssetType,
  AuditEntry,
  BackendAsset,
  BackendAssetType,
  BackendAuditRow,
  BackendBadActor,
  BackendRisk,
  BadActor,
  BadActorStatus,
  Criticality,
  CriticalityCode,
  Reading,
  RiskPrediction,
} from './types'

const CRITICALITY: Record<CriticalityCode, Criticality> = { A: 'High', B: 'Medium', C: 'Low' }
export const CRITICALITY_CODE: Record<Criticality, CriticalityCode> = { High: 'A', Medium: 'B', Low: 'C' }

const TYPE_LABEL: Record<BackendAssetType, AssetType> = {
  pump: 'Pump',
  compressor: 'Compressor',
  heat_exchanger: 'Heat exchanger',
  motor: 'Motor',
}

/**
 * The assets table has no display name. These cover the demo-story assets;
 * everything else shows its type. (Suggest adding a `name` column to assets.)
 */
const DISPLAY_NAMES: Record<string, string> = {
  'P-101': 'Feed pump',
  'C-203': 'Recycle gas compressor',
  'E-302': 'VDU preheat exchanger',
}

export function toAsset(b: BackendAsset): Asset {
  const type = TYPE_LABEL[b.type] ?? (b.type as AssetType)
  return {
    tag: b.tag,
    name: DISPLAY_NAMES[b.tag] ?? type,
    type,
    location: b.location,
    criticality: CRITICALITY[b.criticality] ?? 'Low',
    install_date: b.install_date,
  }
}

/** Same thresholds as bad_actors.py: flagged = count_180d >= 3 or mtbf_drop_pct > 0.40 */
export function toStatus(b: BackendBadActor): BadActorStatus {
  if (b.count_180d >= 3) return 'recurring'
  if (b.mtbf_drop_pct > 0.4) return 'review'
  return 'watch'
}

export function toBadActor(b: BackendBadActor, asset: Asset | undefined, rank: number): BadActor {
  const a = asset ?? toAsset({ tag: b.tag, type: 'pump', location: '—', criticality: b.criticality, install_date: '' })
  const hasBoth = b.mtbf_current_days != null && b.mtbf_previous_days != null
  return {
    rank,
    tag: b.tag,
    name: a.name,
    asset_type: a.type,
    location: a.location,
    criticality: CRITICALITY[b.criticality] ?? a.criticality,
    failure_mode: b.failure_mode,
    events: b.count_180d,
    events_total: b.count_total,
    last_event: b.last_event,
    mtbf_days: b.mtbf_current_days == null ? null : Math.round(b.mtbf_current_days),
    mtbf_prev_days: b.mtbf_previous_days == null ? null : Math.round(b.mtbf_previous_days),
    mtbf_change_pct: hasBoth ? -Math.round(b.mtbf_drop_pct * 100) : 0,
    cost_inr: b.cost_180d,
    downtime_hrs: b.downtime_180d,
    score: b.bad_actor_score,
    flagged: b.flagged,
    status: toStatus(b),
  }
}

export function toRisk(r: BackendRisk, modelNote: string): RiskPrediction {
  return {
    score: Math.round(r.risk_score * 100),
    level: r.risk_level,
    model_note: modelNote,
    factors: r.reasons.map((x) => ({
      feature: x.feature,
      label: x.label,
      impact: x.impact,
      value: x.value,
      typical: x.typical,
      unit: x.unit,
      text: x.text,
    })),
  }
}

/** Operating condition (AI4I features) → the four reading tiles. */
export function toReadings(c: BackendRisk['operating_condition']): Reading[] {
  return [
    { key: 'process_temp', label: 'Process temp', value: c.process_temp_k, unit: 'K' },
    { key: 'speed', label: 'Speed', value: c.rpm, unit: 'rpm' },
    { key: 'torque', label: 'Torque', value: c.torque_nm, unit: 'Nm' },
    { key: 'wear', label: 'Wear time', value: c.tool_wear_min, unit: 'min' },
  ]
}

export function toAuditEntry(r: BackendAuditRow): AuditEntry {
  return {
    id: String(r.id),
    at: r.ts,
    user: r.user,
    role: r.role,
    tool: r.tool || r.action,
    input: r.input,
    output: r.output,
    status: r.status,
  }
}

/** Matches bad_actors.NON_FAILURE_RE: these modes are not failures. */
export function isFailureMode(name: string | null | undefined): boolean {
  return Boolean(name) && !/routine|preventive|inspection|unclassified|\bpm\b/i.test(name ?? '')
}
