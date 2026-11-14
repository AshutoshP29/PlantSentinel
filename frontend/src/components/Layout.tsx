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
  LogOut,
  UserPlus,
  Users,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, DATA_MODE, DEMO_SWITCHER, SITE } from '../api/client'
import { useAuth } from '../lib/auth'
import { ROLE_BY_ID, type RoleId } from '../lib/roles'
import { useBlockedAttempts, usePrivacyFeed } from '../hooks/usePrivacy'
import { useRole } from '../lib/role'
import type { Permission } from '../lib/roles'
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
  { to: '/users', label: 'Users', icon: UserPlus, perm: 'manage_users' },
  { to: '/roles', label: 'Roles & access', icon: Users },
]

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
  const { status, failed } = usePrivacyFeed()
  if (failed && !status) {
    return (
      <NavLink
        to="/privacy"
        title="The privacy status endpoint isn't answering"
        className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm whitespace-nowrap text-muted"
      >
        <span className="inline-flex size-2.5 rounded-full bg-axis" />
        <span className="hidden sm:inline">Network status unavailable</span>
      </NavLink>
    )
  }
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

/** Signed-in person: name + role, with links and sign-out. */
function UserMenu() {
  const { account, def, can, signOut } = useRole()
  const { switchUser } = useAuth()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const initials = account.name
    .split(/[\s.]+/)
    .filter(Boolean)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()

  const go = (to: string) => {
    setOpen(false)
    navigate(to)
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex h-10 items-center gap-2.5 rounded-xl border border-line bg-surface pr-2.5 pl-1.5 hover:bg-surface-2"
      >
        <span className="flex size-7 items-center justify-center rounded-lg bg-accent-soft text-xs font-semibold text-accent-ink">
          {initials}
        </span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block max-w-40 truncate text-sm font-medium text-ink">{account.name}</span>
          <span className="block max-w-40 truncate text-[11px] text-ink-2">{def.label}</span>
        </span>
        <ChevronDown className="size-4 text-ink-2" aria-hidden />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div role="menu" className="absolute right-0 z-40 mt-2 w-64 overflow-hidden rounded-xl border border-line bg-surface shadow-xl">
            <div className="border-b border-line px-4 py-3">
              <div className="text-sm font-semibold text-ink">{account.name}</div>
              <div className="text-xs text-ink-2">
                <span className="font-mono">{account.username}</span> · {def.label}
              </div>
            </div>
            <div className="p-1.5">
              <MenuItem icon={ShieldCheck} label="Roles & access" onClick={() => go('/roles')} />
              {can('manage_users') && <MenuItem icon={UserPlus} label="Add people" onClick={() => go('/users')} />}
              <MenuItem
                icon={LogOut}
                label="Sign out"
                onClick={async () => {
                  setOpen(false)
                  await signOut()
                  navigate('/login', { replace: true })
                }}
              />
            </div>
            {DEMO_SWITCHER && (
              <div className="border-t border-line p-1.5">
                <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-medium tracking-wide text-muted uppercase">Switch role (demo)</div>
                <div className="max-h-64 overflow-y-auto">
                  {api.demoUsernames().map((d) => (
                    <button
                      key={d.username}
                      type="button"
                      role="menuitemradio"
                      aria-checked={d.username === account.username}
                      onClick={async () => {
                        setOpen(false)
                        await switchUser(d.username)
                      }}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-surface-2 ${
                        d.username === account.username ? 'bg-accent-soft/60 font-medium text-accent-ink' : 'text-ink'
                      }`}
                    >
                      <span className="truncate">{ROLE_BY_ID[d.role as RoleId]?.label ?? d.role}</span>
                      <span className="font-mono text-[11px] text-muted">{d.username}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function MenuItem({ icon: Icon, label, onClick }: { icon: LucideIcon; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-ink hover:bg-surface-2"
    >
      <Icon className="size-4 text-ink-2" aria-hidden />
      {label}
    </button>
  )
}

function TopBar() {
  const [theme, toggleTheme] = useTheme()
  const { can } = useRole()

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
        {DATA_MODE !== 'live' && (
          <span
            className="hidden rounded-lg bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent-ink md:inline"
            title={DATA_MODE === 'mixed' ? 'Some screens use the live backend, the rest demo data' : 'All screens use built-in demo data'}
          >
            {DATA_MODE === 'mixed' ? 'Partly live' : 'Demo data'}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <OfflinePill />
          <UserMenu />
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
        {NAV.map((item) => {
          const locked = item.perm ? !can(item.perm) : false
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                [
                  'flex shrink-0 items-center gap-1 rounded-lg px-3 py-1.5 text-xs',
                  isActive ? 'bg-accent-soft font-semibold text-accent-ink' : locked ? 'text-muted' : 'text-ink-2',
                ].join(' ')
              }
            >
              {item.label}
              {locked && <Lock className="size-3" aria-label="No access" />}
            </NavLink>
          )
        })}
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
