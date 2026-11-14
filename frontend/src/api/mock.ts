// Demo data for building the UI before the backend is ready.
//
// The planted story (keep every number consistent with it):
//   P-101 Feed pump has had 4 mechanical seal failures in the last 180 days
//   (02 Jun, 18 Jul, 01 Sep, 15 Oct 2026). MTBF fell from 112 to 45 days (−60%).
//   The 12 Nov 2026 inspection found 0.3 mm shaft misalignment, and the pump
//   manual says misalignment causes seal wear. That's the root cause.

import type {
  Asset,
  AssetDetail,
  BadActor,
  BadActorStatus,
  ClusterPreview,
  DashboardSummary,
  FailureModeCount,
  Inspection,
  MtbfPoint,
  WorkOrder,
} from './types'

export const SITE = 'North Refinery'
export const AS_OF = '2026-11-14'

export const assets: Asset[] = [
  { tag: 'P-101', name: 'Feed pump', type: 'Pump', location: 'Unit 02', criticality: 'High', install_date: '2021-03-12' },
  { tag: 'C-201', name: 'Recycle gas compressor', type: 'Compressor', location: 'Unit 03', criticality: 'High', install_date: '2015-09-15' },
  { tag: 'P-104', name: 'Reflux pump', type: 'Pump', location: 'Unit 01', criticality: 'Medium', install_date: '2016-07-01' },
  { tag: 'E-301', name: 'Crude preheat exchanger', type: 'Heat exchanger', location: 'Unit 01', criticality: 'Medium', install_date: '2011-02-28' },
  { tag: 'M-402', name: 'Cooling water pump motor', type: 'Motor', location: 'Utilities', criticality: 'Medium', install_date: '2017-01-19' },
  { tag: 'P-203', name: 'Condensate pump', type: 'Pump', location: 'Unit 03', criticality: 'Medium', install_date: '2018-11-20' },
  { tag: 'C-202', name: 'Instrument air compressor', type: 'Compressor', location: 'Utilities', criticality: 'High', install_date: '2015-09-15' },
  { tag: 'P-305', name: 'Cooling water pump', type: 'Pump', location: 'Utilities', criticality: 'Medium', install_date: '2012-05-04' },
  { tag: 'E-305', name: 'Overhead condenser', type: 'Heat exchanger', location: 'Unit 01', criticality: 'Medium', install_date: '2013-08-10' },
  { tag: 'M-405', name: 'Fin-fan motor', type: 'Motor', location: 'Unit 03', criticality: 'Low', install_date: '2019-06-03' },
]

export const UNITS = ['Unit 01', 'Unit 02', 'Unit 03', 'Utilities']

export const summary: DashboardSummary = {
  site: SITE,
  assets_monitored: 30,
  work_orders_parsed: 512,
  failure_events: 61,
  bad_actors_flagged: 5,
  plant_mtbf_days: 96,
  plant_mtbf_change_pct: -8,
  downtime_hrs: 214,
  window_days: 180,
  as_of: AS_OF,
}

type Row = Omit<BadActor, 'rank' | 'name' | 'asset_type' | 'location' | 'criticality'>
const rows: Row[] = [
  { tag: 'P-101', failure_mode: 'Mechanical seal leakage', events: 4, mtbf_days: 45, mtbf_prev_days: 112, mtbf_change_pct: -60, cost_inr: 680000, downtime_hrs: 38, score: 92, status: 'recurring' },
  { tag: 'C-201', failure_mode: 'Valve failure', events: 3, mtbf_days: 58, mtbf_prev_days: 101, mtbf_change_pct: -43, cost_inr: 920000, downtime_hrs: 31, score: 81, status: 'recurring' },
  { tag: 'P-104', failure_mode: 'Bearing overheating', events: 3, mtbf_days: 61, mtbf_prev_days: 88, mtbf_change_pct: -31, cost_inr: 240000, downtime_hrs: 22, score: 68, status: 'recurring' },
  { tag: 'E-301', failure_mode: 'Tube fouling', events: 3, mtbf_days: 60, mtbf_prev_days: 70, mtbf_change_pct: -14, cost_inr: 310000, downtime_hrs: 26, score: 61, status: 'recurring' },
  { tag: 'M-402', failure_mode: 'Winding insulation failure', events: 2, mtbf_days: 74, mtbf_prev_days: 140, mtbf_change_pct: -47, cost_inr: 410000, downtime_hrs: 19, score: 57, status: 'review' },
  { tag: 'P-203', failure_mode: 'Mechanical seal leakage', events: 2, mtbf_days: 83, mtbf_prev_days: 97, mtbf_change_pct: -14, cost_inr: 190000, downtime_hrs: 12, score: 44, status: 'watch' },
  { tag: 'C-202', failure_mode: 'Excessive vibration', events: 2, mtbf_days: 88, mtbf_prev_days: 95, mtbf_change_pct: -7, cost_inr: 350000, downtime_hrs: 14, score: 41, status: 'watch' },
  { tag: 'P-305', failure_mode: 'Coupling wear', events: 2, mtbf_days: 90, mtbf_prev_days: 92, mtbf_change_pct: -2, cost_inr: 85000, downtime_hrs: 9, score: 33, status: 'watch' },
  { tag: 'E-305', failure_mode: 'Tube fouling', events: 2, mtbf_days: 95, mtbf_prev_days: 89, mtbf_change_pct: 7, cost_inr: 120000, downtime_hrs: 11, score: 29, status: 'watch' },
  { tag: 'M-405', failure_mode: 'Bearing overheating', events: 2, mtbf_days: 102, mtbf_prev_days: 98, mtbf_change_pct: 4, cost_inr: 60000, downtime_hrs: 6, score: 21, status: 'watch' },
]

export const badActors: BadActor[] = rows.map((r, i) => {
  const a = assets.find((x) => x.tag === r.tag)!
  return { ...r, rank: i + 1, name: a.name, asset_type: a.type, location: a.location, criticality: a.criticality }
})

/** Last 180 days; sums to summary.failure_events (61). */
export const failureModes: FailureModeCount[] = [
  { id: 1, name: 'Mechanical seal leakage', events: 15 },
  { id: 2, name: 'Bearing overheating', events: 12 },
  { id: 3, name: 'Excessive vibration', events: 10 },
  { id: 4, name: 'Valve failure', events: 8 },
  { id: 5, name: 'Tube fouling', events: 6 },
  { id: 6, name: 'Winding insulation failure', events: 4 },
  { id: 7, name: 'Lube oil contamination', events: 3 },
  { id: 8, name: 'Coupling wear', events: 2 },
  { id: 0, name: 'Unclassified', events: 1, is_noise: true },
]

const MONTHS = [
  '2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05',
  '2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11',
]
const series = (values: number[]): MtbfPoint[] =>
  MONTHS.map((month, i) => ({ month, mtbf_days: values[i] }))

export const plantMtbf = series([104, 103, 105, 102, 104, 101, 100, 99, 98, 97, 96, 96])
const p101Mtbf = series([118, 116, 114, 112, 112, 104, 88, 72, 60, 52, 47, 45])

/** All history, as produced by clustering (Upload screen). */
export const clusterPreview: ClusterPreview[] = [
  { name: 'Mechanical seal leakage', events: 23, samples: ['mech seal lkg', 'seal leak hua, replaced', 'seal leaking again'] },
  { name: 'Bearing overheating', events: 17, samples: ['bearing hot', 'brg overheating', 'DE brg temp high'] },
  { name: 'Excessive vibration', events: 14, samples: ['vib high', 'pump vibrating, chkd'] },
]

export const ingestTotals = { records_parsed: 512, scans_ocrd: 3, manuals_indexed: 6 }

export const demoFiles: { name: string; kind: 'work_orders' | 'manual' | 'scan'; detail: string }[] = [
  { name: 'work_orders_2024-2026.xlsx', kind: 'work_orders', detail: '512 records' },
  { name: 'pump_manual.pdf', kind: 'manual', detail: '64 pages' },
  { name: 'compressor_manual.pdf', kind: 'manual', detail: '88 pages' },
  { name: 'sop_seal_replacement.pdf', kind: 'manual', detail: '6 pages' },
  { name: 'sop_shaft_alignment.pdf', kind: 'manual', detail: '8 pages' },
  { name: 'sop_exchanger_cleaning.pdf', kind: 'manual', detail: '5 pages' },
  { name: 'vendor_seal_datasheet.pdf', kind: 'manual', detail: '4 pages' },
  { name: 'inspection_P-101.jpg', kind: 'scan', detail: '1 page' },
  { name: 'inspection_C-201.jpg', kind: 'scan', detail: '1 page' },
  { name: 'inspection_E-301.jpg', kind: 'scan', detail: '1 page' },
]

// ---------- Asset detail ----------

export const p101Inspection: Inspection = {
  id: 'insp-118',
  tag: 'P-101',
  date: '2026-11-12',
  inspector: 'R. Menon',
  report_no: 'IR-2026-118',
  page: 2,
  pages: 6,
  file_path: 'inspections/inspection_P-101.jpg',
  findings: [
    { item: 'Shaft alignment', result: 'Misalignment observed: 0.3 mm', flagged: true },
    { item: 'Seal condition', result: 'Wear (moderate)', flagged: true },
    { item: 'Bearing temperature', result: 'Normal (62 °C)', flagged: false },
    { item: 'Coupling', result: 'No damage', flagged: false },
  ],
}

const p101WorkOrders: WorkOrder[] = [
  { id: 'WO-25117', tag: 'P-101', date: '2026-10-15', description: 'mech seal lkg - 4th time, chk alignment?', action_taken: 'Mech seal replaced', downtime_hrs: 9, cost_inr: 170000, failure_mode: 'Mechanical seal leakage' },
  { id: 'WO-24980', tag: 'P-101', date: '2026-09-01', description: 'seal leaking again, vib high', action_taken: 'Seal replaced', downtime_hrs: 10, cost_inr: 170000, failure_mode: 'Mechanical seal leakage' },
  { id: 'WO-24811', tag: 'P-101', date: '2026-07-18', description: 'mech seal lkg again!!', action_taken: 'Seal replaced', downtime_hrs: 9, cost_inr: 170000, failure_mode: 'Mechanical seal leakage' },
  { id: 'WO-24690', tag: 'P-101', date: '2026-06-02', description: 'seal leak hua, replaced', action_taken: 'Seal replaced', downtime_hrs: 10, cost_inr: 170000, failure_mode: 'Mechanical seal leakage' },
  { id: 'WO-24552', tag: 'P-101', date: '2026-04-20', description: 'PM - lube oil chg', action_taken: 'Lube oil changed', downtime_hrs: 2, cost_inr: 12000, failure_mode: null },
  { id: 'WO-24431', tag: 'P-101', date: '2026-03-16', description: 'P-101 seal replaced, lkg at gland', action_taken: 'Seal replaced', downtime_hrs: 8, cost_inr: 160000, failure_mode: 'Mechanical seal leakage' },
  { id: 'WO-24388', tag: 'P-101', date: '2025-11-24', description: 'seal leaking again DE side', action_taken: 'Seal replaced, flush line cleaned', downtime_hrs: 10, cost_inr: 165000, failure_mode: 'Mechanical seal leakage' },
]

export const p101Detail: AssetDetail = {
  asset: assets[0],
  score: 92,
  status: 'recurring',
  timeline: [
    { date: '2026-04-20', label: 'Lube oil change', kind: 'maintenance' },
    { date: '2026-06-02', label: 'Seal leakage', kind: 'failure' },
    { date: '2026-07-18', label: 'Seal leakage', kind: 'failure' },
    { date: '2026-09-01', label: 'Seal leakage', kind: 'failure' },
    { date: '2026-10-15', label: 'Seal leakage', kind: 'failure' },
    { date: '2026-11-12', label: 'Alignment inspection', kind: 'inspection' },
  ],
  work_orders: p101WorkOrders,
  mtbf_trend: p101Mtbf,
  risk: {
    score: 82,
    predicted_type: 'Overstrain failure',
    model_note: 'Demo model assessment',
    factors: [
      { feature: 'Torque', value: 0.38 },
      { feature: 'Tool wear', value: 0.26 },
      { feature: 'Rotational speed', value: -0.21 },
      { feature: 'Process temperature', value: 0.09 },
    ],
  },
  readings: [
    { key: 'temperature', label: 'Temperature', value: 78, unit: '°C' },
    { key: 'speed', label: 'Speed', value: 1480, unit: 'rpm' },
    { key: 'torque', label: 'Torque', value: 62, unit: 'Nm' },
    { key: 'tool_wear', label: 'Tool wear', value: 212, unit: 'min' },
  ],
  latest_inspection: p101Inspection,
}

/** Plausible detail for the other assets, derived from their bad-actor row. */
export function genericDetail(tag: string): AssetDetail | null {
  const asset = assets.find((a) => a.tag === tag)
  const row = badActors.find((b) => b.tag === tag)
  if (!asset || !row) return null

  const failureDates = ['2026-06-20', '2026-08-28', '2026-10-30'].slice(3 - Math.min(3, row.events))
  const short = row.failure_mode.split(' ').slice(-2).join(' ')
  const work_orders: WorkOrder[] = failureDates
    .slice()
    .reverse()
    .map((date, i) => ({
      id: `WO-${24900 - i * 87 - tag.charCodeAt(2)}`,
      tag,
      date,
      description: `${tag} ${short.toLowerCase()} reported`,
      action_taken: 'Repaired and returned to service',
      downtime_hrs: Math.max(2, Math.round(row.downtime_hrs / row.events)),
      cost_inr: Math.round(row.cost_inr / row.events / 1000) * 1000,
      failure_mode: row.failure_mode,
    }))

  const status: BadActorStatus = row.status
  const decline = row.mtbf_prev_days - row.mtbf_days
  const trend = MONTHS.map((month, i) => ({
    month,
    mtbf_days: Math.round(row.mtbf_prev_days - (decline * Math.max(0, i - 5)) / 6),
  }))

  return {
    asset,
    score: row.score,
    status,
    timeline: failureDates.map((date) => ({ date, label: short, kind: 'failure' as const })),
    work_orders,
    mtbf_trend: trend,
    risk: {
      score: Math.max(12, row.score - 14),
      predicted_type: asset.type === 'Motor' ? 'Power failure' : 'Heat dissipation failure',
      model_note: 'Demo model assessment',
      factors: [
        { feature: 'Process temperature', value: 0.22 },
        { feature: 'Torque', value: 0.14 },
        { feature: 'Rotational speed', value: -0.1 },
      ],
    },
    readings: [
      { key: 'temperature', label: 'Temperature', value: 64, unit: '°C' },
      { key: 'speed', label: 'Speed', value: 1470, unit: 'rpm' },
      { key: 'torque', label: 'Torque', value: 41, unit: 'Nm' },
      { key: 'tool_wear', label: 'Tool wear', value: 96, unit: 'min' },
    ],
    latest_inspection: null,
  }
}
