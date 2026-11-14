import {
  Building2,
  ChevronDown,
  FileText,
  LayoutDashboard,
  Lock,
  MessageSquare,
  Moon,
  ShieldAlert,
  ShieldCheck,
  Sun,
  Upload,
  UserRound,
  Users,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { SITE, USE_MOCK } from '../api/client'
import { useBlockedAttempts, usePrivacyStatus } from '../hooks/usePrivacy'
import { useRole } from '../lib/role'
import { ROLES, type Permission, type RoleGroup, type RoleId } from '../lib/roles'
import { useTheme } from '../lib/theme'
import { Select } from './ui'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  perm?: Permission
}

const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, perm: 'view_dashboard' },
  { to: '/upload', label: 'Upload', icon: Upload, perm: 'upload_data' },
  { to: '/assets/P-101', label: 'Asset detail', icon: Wrench, perm: 'view_dashboard' },
  { to: '/agent', label: 'Ask the agent', icon: MessageSquare, perm: 'ask_agent' },
  { to: '/documents', label: 'Documents', icon: FileText, perm: 'view_documents' },
  { to: '/privacy', label: 'Privacy', icon: ShieldCheck },
  { to: '/roles', label: 'Roles & access', icon: Users },
]

const GROUP_ORDER: RoleGroup[] = ['Plant leadership', 'Maintenance & reliability', 'Shop floor', 'Support']

export default function Layout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8">
          <BlockedBanner />
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function Logo({ withName = true }: { withName?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="PlantSentinel" className="size-9" />
      {withName && <span className="text-lg font-bold tracking-tight text-ink">PlantSentinel</span>}
    </div>
  )
}

function Sidebar() {
  const { can } = useRole()
  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-surface/70 px-4 py-6 backdrop-blur lg:flex">
      <div className="px-2">
        <Logo />
      </div>
      <nav className="mt-9 flex flex-col gap-1" aria-label="Main">
        {NAV.map((item) => {
          const locked = item.perm ? !can(item.perm) : false
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              title={locked ? 'Your role has no access to this screen' : undefined}
              className={({ isActive }) =>
                [
                  'flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition-colors',
                  isActive
                    ? 'bg-accent-soft font-semibold text-accent-ink'
                    : locked
                      ? 'text-muted hover:bg-surface-2'
                      : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
                ].join(' ')
              }
            >
              <item.icon className="size-5 shrink-0" aria-hidden />
              {item.label}
              {locked && <Lock className="ml-auto size-3.5" aria-label="No access" />}
            </NavLink>
          )
        })}
      </nav>
      <div className="mt-auto rounded-xl border border-line bg-surface-2/70 p-3.5 text-xs text-ink-2">
        <div className="font-medium text-ink">Runs fully offline</div>
        <p className="mt-1 leading-relaxed">Models, plant data and documents never leave this machine.</p>
      </div>
    </aside>
  )
}

function OfflinePill() {
  const status = usePrivacyStatus()
  const external = status?.external_connections ?? 0
  const ok = external === 0
  return (
    <NavLink
      to="/privacy"
      title="Outbound network connections"
      className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm whitespace-nowrap text-ink-2 hover:text-ink"
    >
      <span className="relative flex size-2.5">
        {ok && <span className="absolute inline-flex size-full animate-ping rounded-full bg-good opacity-50" />}
        <span className={`relative inline-flex size-2.5 rounded-full ${ok ? 'bg-good' : 'bg-critical'}`} />
      </span>
      <span className="hidden sm:inline">{ok ? 'Offline ·' : 'Online ·'}</span>
      <span className="tabular font-semibold text-ink">{external}</span>
      <span className="hidden sm:inline">external</span>
    </NavLink>
  )
}

/** Role switcher grouped by level of the plant hierarchy (demo: stands in for sign-in). */
function RoleSelect() {
  const { role, setRole, user } = useRole()
  return (
    <label className="relative flex w-44 items-center sm:w-60" title={`Signed in as ${user}`}>
      <span className="sr-only">Role</span>
      <UserRound className="pointer-events-none absolute left-3 size-4 text-ink-2" aria-hidden />
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as RoleId)}
        className="h-10 w-full cursor-pointer appearance-none truncate rounded-xl border border-line bg-surface pr-9 pl-9 text-sm text-ink hover:bg-surface-2"
      >
        {GROUP_ORDER.map((g) => (
          <optgroup key={g} label={g}>
            {ROLES.filter((r) => r.group === g).map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 size-4 text-ink-2" aria-hidden />
    </label>
  )
}

function TopBar() {
  const [theme, toggleTheme] = useTheme()

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-page/80 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-[1400px] items-center gap-3 px-4 md:px-8">
        <div className="lg:hidden">
          <Logo withName={false} />
        </div>

        <Select
          label="Site"
          icon={Building2}
          value={SITE}
          onChange={() => {}}
          options={[{ value: SITE, label: SITE }]}
          className="hidden w-44 sm:flex"
        />
        {USE_MOCK && (
          <span className="hidden rounded-lg bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent-ink md:inline">
            Demo data
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <OfflinePill />
          <RoleSelect />
          <button
            type="button"
            onClick={toggleTheme}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-ink-2 hover:text-ink"
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
          </button>
        </div>
      </div>

      {/* Compact nav below the large-screen breakpoint */}
      <nav className="flex gap-1 overflow-x-auto border-t border-line px-3 py-2 lg:hidden" aria-label="Main">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              [
                'shrink-0 rounded-lg px-3 py-1.5 text-xs',
                isActive ? 'bg-accent-soft font-semibold text-accent-ink' : 'text-ink-2',
              ].join(' ')
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}

/** The memorable moment: shows on every screen when the guard blocks an outbound request. */
function BlockedBanner() {
  const attempts = useBlockedAttempts()
  const [dismissed, setDismissed] = useState<string | null>(null)
  const latest = attempts[0]
  if (!latest || latest.id === dismissed) return null

  return (
    <div
      role="alert"
      className="mb-5 flex items-start gap-3 rounded-2xl border border-critical/40 bg-critical-soft px-5 py-4"
    >
      <ShieldAlert className="mt-0.5 size-6 shrink-0 text-critical" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-critical-ink">External request blocked · Unapproved tool destination</div>
        <div className="mt-0.5 text-sm text-ink-2">
          An attempted request to <span className="font-medium text-ink">{latest.target}</span> from{' '}
          <span className="font-medium text-ink">{latest.source}</span> was blocked. 0 active external connections.
        </div>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(latest.id)}
        className="rounded-lg p-1 text-ink-2 hover:bg-surface/60 hover:text-ink"
        aria-label="Dismiss alert"
      >
        <X className="size-5" />
      </button>
    </div>
  )
}
