// Demo-mode data. It follows the teammates' synthetic data and outputs, read-only:
//   fixtures/demo-data.json   assets, operating conditions and all 491 work orders, converted
//                             from data/synthetic/*.csv + clusters_fallback.json
//   bad actors                the backend's get_bad_actors() shape; the top rows match the
//                             story planted in scripts/generate_synthetic.py
//   risk                      predict_risk() shape; P-101/C-203/E-302 follow the story in risk.py,
//                             other assets get a calm placeholder
//   metrics                   models/metrics.json
//
// The story: P-101 has 4 mechanical seal failures in the last 180 days (02 Jun, 22 Jul,
// 15 Sep, 02 Nov 2026). The gap between failures fell from ~150 to ~51 days (−66%).

import demo from './fixtures/demo-data.json'
import type {
  BackendAsset,
  BackendBadActor,
  BackendRisk,
  BackendRiskReason,
  BackendWorkOrder,
  ClusterRun,
  DashboardSummary,
  FailureModeCount,
  Inspection,
  MtbfPoint,
} from './types'

export const SITE = 'North Refinery'
export const AS_OF = '2026-11-14'

export const assets = demo.assets as BackendAsset[]
export const workOrders = demo.work_orders as BackendWorkOrder[]
const conditions = demo.asset_conditions as {
  tag: string
  type: string
  air_temp_k: number
  process_temp_k: number
  rpm: number
  torque_nm: number
  tool_wear_min: number
}[]

export const UNITS = ['CDU-1', 'VDU', 'FCC', 'Hydrotreater', 'Utilities', 'Offsites']

/** models/metrics.json (committed by the ML teammate) */
export const metrics = {
  clustering: { n_clusters: 19, n_failure_modes: 15, silhouette: 0.6346, ari_vs_truth: 0.9338, n_work_orders: 491 },
  risk_model: { f1: 0.8397, roc_auc: 0.9754, dataset: 'AI4I 2020', model: 'xgboost' },
}
export const RISK_MODEL_NOTE = `XGBoost on AI4I 2020 · F1 ${metrics.risk_model.f1.toFixed(2)} · ROC-AUC ${metrics.risk_model.roc_auc.toFixed(2)}`

// ---------- Dashboard ----------

export const summary: DashboardSummary = {
  site: SITE,
  assets_monitored: 30,
  work_orders_parsed: 491,
  failure_events: 60,
  bad_actors_flagged: 3,
  plant_mtbf_days: 90, // 30 assets × 180 days / 60 failures
  downtime_hrs: 918,
  window_days: 180,
  as_of: AS_OF,
}

/** get_bad_actors(top_n=10) shape. Rows 1–4 are worked out from the work orders. */
export const badActors: BackendBadActor[] = [
  { tag: 'P-101', failure_mode: 'Mechanical Seal Leakage', criticality: 'A', count_180d: 4, count_total: 9, last_event: '2026-11-02', mtbf_current_days: 51.0, mtbf_previous_days: 150.0, mtbf_drop_pct: 0.66, cost_180d: 412400, cost_prev_180d: 67800, cost_trend_pct: 5.083, downtime_180d: 37.3, bad_actor_score: 19.92, flagged: true },
  { tag: 'C-203', failure_mode: 'Bearing Overheating', criticality: 'A', count_180d: 3, count_total: 5, last_event: '2026-10-15', mtbf_current_days: 60.0, mtbf_previous_days: 300.0, mtbf_drop_pct: 0.8, cost_180d: 664000, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 38.3, bad_actor_score: 16.2, flagged: true },
  { tag: 'E-302', failure_mode: 'Fouling', criticality: 'B', count_180d: 3, count_total: 4, last_event: '2026-10-05', mtbf_current_days: 65.0, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 348900, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 91.5, bad_actor_score: 6.0, flagged: true },
  { tag: 'E-302', failure_mode: 'Gasket Leakage', criticality: 'B', count_180d: 2, count_total: 6, last_event: '2026-11-02', mtbf_current_days: 119.0, mtbf_previous_days: 120.3, mtbf_drop_pct: 0.011, cost_180d: 355700, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 41.2, bad_actor_score: 4.04, flagged: false },
  { tag: 'C-201', failure_mode: 'Bearing Noisy', criticality: 'A', count_180d: 1, count_total: 3, last_event: '2026-07-10', mtbf_current_days: null, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 47500, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 11.7, bad_actor_score: 3.0, flagged: false },
  { tag: 'C-201', failure_mode: 'Valve Plate Cracked', criticality: 'A', count_180d: 1, count_total: 3, last_event: '2026-09-21', mtbf_current_days: null, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 139100, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 10.7, bad_actor_score: 3.0, flagged: false },
  { tag: 'C-203', failure_mode: 'Bearing Noisy', criticality: 'A', count_180d: 1, count_total: 1, last_event: '2026-07-29', mtbf_current_days: null, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 82500, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 7.4, bad_actor_score: 3.0, flagged: false },
  { tag: 'C-203', failure_mode: 'Lube Oil Leakage', criticality: 'A', count_180d: 1, count_total: 7, last_event: '2026-07-29', mtbf_current_days: null, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 17200, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 2.7, bad_actor_score: 3.0, flagged: false },
  { tag: 'C-204', failure_mode: 'Bearing Noisy', criticality: 'A', count_180d: 1, count_total: 2, last_event: '2026-09-10', mtbf_current_days: null, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 44600, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 7.9, bad_actor_score: 3.0, flagged: false },
  { tag: 'C-204', failure_mode: 'Bearing Overheating', criticality: 'A', count_180d: 1, count_total: 2, last_event: '2026-08-19', mtbf_current_days: null, mtbf_previous_days: null, mtbf_drop_pct: 0, cost_180d: 208300, cost_prev_180d: 0, cost_trend_pct: null, downtime_180d: 22.2, bad_actor_score: 3.0, flagged: false },
]

/** Failure events per cluster in the last 180 days (from the work orders + saved clusters). */
export const failureModes: FailureModeCount[] = [
  { id: 1, name: 'Mechanical Seal Leakage', events: 8 },
  { id: 2, name: 'Impeller Wear', events: 8 },
  { id: 3, name: 'Cavitation', events: 7 },
  { id: 4, name: 'Bearing Noisy', events: 7 },
  { id: 5, name: 'Gasket Leakage', events: 6 },
  { id: 6, name: 'Bearing Overheating', events: 5 },
  { id: 7, name: 'Fouling', events: 4 },
  { id: 8, name: 'Lube Oil Leakage', events: 3 },
  { id: 9, name: 'Winding Insulation Degradation', events: 3 },
  { id: 10, name: 'Valve Plate Cracked', events: 3 },
  { id: 11, name: 'Motor Overload', events: 2 },
  { id: 12, name: 'Bearing Failure', events: 2 },
  { id: 13, name: 'High Vibration', events: 1 },
  { id: 14, name: 'Motor Winding Overheating', events: 1 },
  { id: 0, name: 'Unclassified', events: 1, is_noise: true },
]

/** Placeholder until the backend serves a plant MTBF trend. */
const MONTHS = ['2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11']
export const plantMtbf: MtbfPoint[] = MONTHS.map((month, i) => ({
  month,
  mtbf_days: [104, 102, 101, 99, 98, 97, 95, 94, 93, 92, 91, 90][i],
}))

// ---------- Upload ----------

/** All-history cluster sizes from clusters_fallback.json, with real sample texts. */
export const clusterRun: ClusterRun = {
  clusters: [
    { name: 'Mechanical Seal Leakage', events: 51, samples: ['mech seal lkg', 'seal leak hua', 'Pump seal leaking, product dripping'] },
    { name: 'Bearing Overheating', events: 17, samples: ['brg temp badh gaya', 'high bearing temperature alarm', 'Brg temp high'] },
    { name: 'Fouling', events: 17, samples: ['high dp due to foulign', 'FOULING, POOR HEAT TRANSFER', 'fouling, poor heat transfre'] },
  ],
  metrics: metrics.clustering,
}

export const ingestTotals = { records_parsed: 491, scans_ocrd: 3, manuals_indexed: 6 }

export const demoFiles: { name: string; kind: 'work_orders' | 'manual' | 'scan'; detail: string }[] = [
  { name: 'work_orders.csv', kind: 'work_orders', detail: '491 records' },
  { name: 'pump_manual.pdf', kind: 'manual', detail: '64 pages' },
  { name: 'compressor_manual.pdf', kind: 'manual', detail: '88 pages' },
  { name: 'sop_seal_replacement.pdf', kind: 'manual', detail: '6 pages' },
  { name: 'sop_shaft_alignment.pdf', kind: 'manual', detail: '8 pages' },
  { name: 'sop_exchanger_cleaning.pdf', kind: 'manual', detail: '5 pages' },
  { name: 'vendor_seal_datasheet.pdf', kind: 'manual', detail: '4 pages' },
  { name: 'inspection_P-101.jpg', kind: 'scan', detail: '1 page' },
  { name: 'inspection_C-203.jpg', kind: 'scan', detail: '1 page' },
  { name: 'inspection_E-302.jpg', kind: 'scan', detail: '1 page' },
]

// ---------- Asset detail ----------

/** Demo inspection for P-101 (scans in data/scans/ are still to come). */
export const p101Inspection: Inspection = {
  id: 'insp-118',
  tag: 'P-101',
  date: '2026-11-12',
  inspector: 'R. Menon',
  report_no: 'IR-2026-118',
  page: 2,
  pages: 6,
  file_path: 'data/scans/inspection_P-101.jpg',
  findings: [
    { item: 'Shaft alignment', result: 'Misalignment observed: 0.3 mm', flagged: true },
    { item: 'Seal condition', result: 'Wear (moderate)', flagged: true },
    { item: 'Bearing temperature', result: 'Normal (62 °C)', flagged: false },
    { item: 'Coupling', result: 'Slight vibration at coupling end', flagged: false },
  ],
}

// Typical values (AI4I medians) used in the explanations below
const TYPICAL = { air_temp_k: 300.1, process_temp_k: 310.1, rpm: 1503, torque_nm: 40.1, tool_wear_min: 108 }

const r = (feature: string, label: string, value: number, typical: number, unit: string, impact: number): BackendRiskReason => ({
  feature,
  label,
  value,
  typical,
  unit,
  impact,
  text: `${label} ${value} ${unit} is ${value > typical ? 'above' : value < typical ? 'below' : 'at'} typical (${typical} ${unit})`,
})

/** predict_risk() for the story assets, matching STORY_ROWS in risk.py. */
const STORY_RISK: Record<string, Pick<BackendRisk, 'risk_score' | 'risk_level' | 'reasons'>> = {
  'P-101': {
    // overstrain: torque × wear, the load a misaligned shaft puts on the seal
    risk_score: 0.96,
    risk_level: 'high',
    reasons: [
      r('strain_nm_min', 'Overstrain (torque x wear)', 12538, 4331, 'Nm.min', 2.41),
      r('torque_nm', 'Torque', 65.3, TYPICAL.torque_nm, 'Nm', 1.32),
      r('tool_wear_min', 'Component wear time', 192, TYPICAL.tool_wear_min, 'min', 0.87),
    ],
  },
  'C-203': {
    // heat-dissipation problem → bearing overheating
    risk_score: 0.93,
    risk_level: 'high',
    reasons: [
      r('temp_diff_k', 'Heat-dissipation margin (process - air temp)', 8.1, 9.8, 'K', 1.94),
      r('rpm', 'Rotational speed', 1284, TYPICAL.rpm, 'rpm', 1.12),
      r('torque_nm', 'Torque', 68.2, TYPICAL.torque_nm, 'Nm', 0.74),
    ],
  },
  'E-302': {
    risk_score: 0.45,
    risk_level: 'medium',
    reasons: [
      r('tool_wear_min', 'Component wear time', 206, TYPICAL.tool_wear_min, 'min', 0.91),
      r('rpm', 'Rotational speed', 1566, TYPICAL.rpm, 'rpm', 0.08),
      r('air_temp_k', 'Air temperature', 296.5, TYPICAL.air_temp_k, 'K', -0.21),
    ],
  },
}

export function riskFor(tag: string): BackendRisk | null {
  const c = conditions.find((x) => x.tag === tag)
  if (!c) return null
  const story = STORY_RISK[tag]
  const operating_condition = {
    air_temp_k: c.air_temp_k,
    process_temp_k: c.process_temp_k,
    rpm: c.rpm,
    torque_nm: c.torque_nm,
    tool_wear_min: c.tool_wear_min,
    duty_class: c.type,
  }
  if (story) return { tag, ...story, operating_condition, source: 'AI4I 2020 model' }
  // Calm placeholder: biggest deviations from typical, small contributions
  const reasons = [
    r('tool_wear_min', 'Component wear time', c.tool_wear_min, TYPICAL.tool_wear_min, 'min', +((c.tool_wear_min - 108) / 400).toFixed(2)),
    r('torque_nm', 'Torque', c.torque_nm, TYPICAL.torque_nm, 'Nm', +((c.torque_nm - 40.1) / 60).toFixed(2)),
    r('rpm', 'Rotational speed', c.rpm, TYPICAL.rpm, 'rpm', +((1503 - c.rpm) / 2000).toFixed(2)),
  ].sort((a, b) => b.impact - a.impact)
  return { tag, risk_score: 0.03, risk_level: 'low', reasons, operating_condition, source: 'AI4I 2020 model' }
}
