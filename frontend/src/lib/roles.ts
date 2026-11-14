// Roles follow the usual reporting line of a plant maintenance organisation.
// Level 1 is the top of the hierarchy. Support roles sit outside the line.
//
// GRANTS is the single source of truth for what each role may do. It is a
// DRAFT for the team to review; change it here and the whole UI follows.
// The backend guard must enforce the same table (the UI only mirrors it).

export type RoleId =
  | 'plant_head'
  | 'maintenance_manager'
  | 'reliability_engineer'
  | 'maintenance_planner'
  | 'shift_supervisor'
  | 'technician'
  | 'operator'
  | 'system_admin'
  | 'contractor'

export type RoleGroup = 'Plant leadership' | 'Maintenance & reliability' | 'Shop floor' | 'Support'

export interface RoleDef {
  id: RoleId
  label: string
  short: string // column header in the permission matrix
  level: number | null // 1 = top; null = outside the reporting line
  group: RoleGroup
  reportsTo: RoleId | null
  user: string // demo user signed in under this role
  description: string
}

export const ROLES: RoleDef[] = [
  {
    id: 'plant_head',
    label: 'Plant Head',
    short: 'Plant Head',
    level: 1,
    group: 'Plant leadership',
    reportsTo: null,
    user: 'V. Iyer',
    description: 'Runs the site. Needs the big picture: bad actors, downtime and cost.',
  },
  {
    id: 'maintenance_manager',
    label: 'Maintenance Manager',
    short: 'Maint. Mgr',
    level: 2,
    group: 'Maintenance & reliability',
    reportsTo: 'plant_head',
    user: 'S. Kulkarni',
    description: 'Owns the maintenance budget and approves work orders.',
  },
  {
    id: 'reliability_engineer',
    label: 'Reliability Engineer',
    short: 'Rel. Eng.',
    level: 3,
    group: 'Maintenance & reliability',
    reportsTo: 'maintenance_manager',
    user: 'A. Rao',
    description: 'Finds root causes of repeat failures. The main PlantSentinel user.',
  },
  {
    id: 'maintenance_planner',
    label: 'Maintenance Planner',
    short: 'Planner',
    level: 3,
    group: 'Maintenance & reliability',
    reportsTo: 'maintenance_manager',
    user: 'N. Desai',
    description: 'Plans and schedules work orders, parts and shutdown jobs.',
  },
  {
    id: 'shift_supervisor',
    label: 'Shift Supervisor',
    short: 'Supervisor',
    level: 4,
    group: 'Shop floor',
    reportsTo: 'maintenance_manager',
    user: 'P. Nair',
    description: 'Runs the maintenance crew on shift and assigns jobs.',
  },
  {
    id: 'technician',
    label: 'Technician',
    short: 'Technician',
    level: 5,
    group: 'Shop floor',
    reportsTo: 'shift_supervisor',
    user: 'K. Singh',
    description: 'Mechanical, electrical or instrument technician who does the work.',
  },
  {
    id: 'operator',
    label: 'Operator',
    short: 'Operator',
    level: 5,
    group: 'Shop floor',
    reportsTo: 'shift_supervisor',
    user: 'M. Khan',
    description: 'Runs the process units and reports abnormal equipment behaviour.',
  },
  {
    id: 'system_admin',
    label: 'System Admin (IT/OT)',
    short: 'Admin',
    level: null,
    group: 'Support',
    reportsTo: null,
    user: 'D. Shah',
    description: 'Manages users, data and security. Sees the audit trail, not plant costs.',
  },
  {
    id: 'contractor',
    label: 'Contractor (external)',
    short: 'Contractor',
    level: null,
    group: 'Support',
    reportsTo: null,
    user: 'J. Thomas',
    description: 'Outside vendor staff. Sees only the work orders they are given.',
  },
]

export type Permission =
  | 'view_dashboard'
  | 'view_costs'
  | 'upload_data'
  | 'ask_agent'
  | 'view_documents'
  | 'draft_work_order'
  | 'edit_work_order'
  | 'approve_work_order'
  | 'export_reports'
  | 'view_audit_log'
  | 'export_audit_log'
  | 'run_security_tests'
  | 'clear_data'
  | 'manage_users'

export interface PermissionDef {
  id: Permission
  label: string
  area: 'Data & analysis' | 'Work orders & reports' | 'Security & admin'
}

export const PERMISSIONS: PermissionDef[] = [
  { id: 'view_dashboard', label: 'View dashboards & assets', area: 'Data & analysis' },
  { id: 'view_costs', label: 'See repair costs', area: 'Data & analysis' },
  { id: 'upload_data', label: 'Upload data & run clustering', area: 'Data & analysis' },
  { id: 'ask_agent', label: 'Ask the agent', area: 'Data & analysis' },
  { id: 'view_documents', label: 'View & download documents', area: 'Work orders & reports' },
  { id: 'draft_work_order', label: 'Draft work orders', area: 'Work orders & reports' },
  { id: 'edit_work_order', label: 'Edit work-order drafts', area: 'Work orders & reports' },
  { id: 'approve_work_order', label: 'Approve work orders', area: 'Work orders & reports' },
  { id: 'export_reports', label: 'Export reports (.xlsx)', area: 'Work orders & reports' },
  { id: 'view_audit_log', label: 'View audit log', area: 'Security & admin' },
  { id: 'export_audit_log', label: 'Export audit log', area: 'Security & admin' },
  { id: 'run_security_tests', label: 'Run security tests', area: 'Security & admin' },
  { id: 'clear_data', label: 'Clear plant data', area: 'Security & admin' },
  { id: 'manage_users', label: 'Add people below you', area: 'Security & admin' },
]

const ALL_LINE: RoleId[] = [
  'plant_head',
  'maintenance_manager',
  'reliability_engineer',
  'maintenance_planner',
  'shift_supervisor',
  'technician',
  'operator',
]

/** DRAFT permission matrix — review with the team. */
export const GRANTS: Record<Permission, RoleId[]> = {
  view_dashboard: [...ALL_LINE, 'system_admin'],
  view_costs: ['plant_head', 'maintenance_manager', 'reliability_engineer', 'maintenance_planner'],
  upload_data: ['reliability_engineer', 'maintenance_planner', 'system_admin'],
  ask_agent: ALL_LINE,
  view_documents: ['plant_head', 'maintenance_manager', 'reliability_engineer', 'maintenance_planner', 'shift_supervisor', 'technician', 'contractor'],
  draft_work_order: ['maintenance_manager', 'reliability_engineer', 'maintenance_planner', 'shift_supervisor'],
  edit_work_order: ['maintenance_manager', 'reliability_engineer', 'maintenance_planner'],
  approve_work_order: ['plant_head', 'maintenance_manager'],
  export_reports: ['plant_head', 'maintenance_manager', 'reliability_engineer', 'maintenance_planner'],
  view_audit_log: ['plant_head', 'maintenance_manager', 'system_admin'],
  export_audit_log: ['system_admin'],
  run_security_tests: ['system_admin'],
  clear_data: ['system_admin'],
  manage_users: ['plant_head', 'maintenance_manager', 'shift_supervisor', 'system_admin'],
}

/**
 * Who may add (and remove) accounts for which roles.
 * Line roles manage everyone below them in the reporting line (via reportsTo).
 * Plant Head and Maintenance Manager also onboard contractors; the System Admin manages everyone.
 */
export function manageableRoles(manager: RoleId): RoleId[] {
  if (manager === 'system_admin') return ROLES.map((r) => r.id)
  const below = (id: RoleId): RoleId[] =>
    ROLES.filter((r) => r.reportsTo === id).flatMap((r) => [r.id, ...below(r.id)])
  const out = below(manager)
  if (manager === 'plant_head' || manager === 'maintenance_manager') out.push('contractor')
  return [...new Set(out)]
}

export function canManageRole(manager: RoleId, target: RoleId): boolean {
  return manageableRoles(manager).includes(target)
}

export const ROLE_BY_ID = Object.fromEntries(ROLES.map((r) => [r.id, r])) as Record<RoleId, RoleDef>

export const DEFAULT_ROLE: RoleId = 'reliability_engineer'

export function can(role: RoleId, permission: Permission): boolean {
  return GRANTS[permission].includes(role)
}

export function roleLabel(id: string): string {
  return ROLE_BY_ID[id as RoleId]?.label ?? id
}
