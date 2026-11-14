import {
  Check,
  Download,
  IdCard,
  Link2,
  Loader2,
  Lock,
  Minus,
  Network,
  Play,
  Search,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { useTopicVersion } from '../api/events'
import type { AgentStep, AuditStatus } from '../api/types'
import { Button, Card, Chip, ErrorNote, LinkButton, PageHeader, Select, Skeleton } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useBlockedAttempts, usePrivacyStatus } from '../hooks/usePrivacy'
import { formatTime } from '../lib/format'
import { useRole } from '../lib/role'
import { PERMISSIONS, roleLabel } from '../lib/roles'
import { TD, TH, type Tone } from '../lib/status'
import { useToast } from '../lib/toast'

const AUDIT_TONE: Record<AuditStatus, Tone> = { allowed: 'good', blocked: 'critical', denied: 'warning' }

export default function Privacy() {
  const status = usePrivacyStatus()
  const blocked = useBlockedAttempts()
  const latest = blocked[0]

  return (
    <>
      <PageHeader title="Privacy & audit" description="Proof that plant data never leaves this machine." />

      {/* Stat cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <StatCard icon={Link2} title="External connections">
          {status ? (
            <>
              <div className={`text-5xl font-bold ${status.external_connections ? 'text-critical-ink' : 'text-ink'}`}>
                {status.external_connections}
              </div>
              <CheckedAgo iso={status.checked_at} />
            </>
          ) : (
            <Skeleton className="h-16 w-24" />
          )}
        </StatCard>
        <StatCard icon={Network} title="Network isolation">
          <div className="text-base text-ink-2">
            Docker network: <span className="font-semibold text-ink">{status?.network_mode ?? 'none'}</span>
          </div>
          <div className="mt-2">
            <Chip tone="good" icon={ShieldCheck}>
              Isolated
            </Chip>
          </div>
        </StatCard>
        <StatCard icon={IdCard} title="Personal details redacted">
          <div className="text-5xl font-bold text-accent-ink">{status?.redactions ?? '—'}</div>
          <div className="mt-1 text-xs text-muted">Names, phone numbers and emails removed before the model sees them</div>
        </StatCard>
      </div>

      {/* Connections + blocked attempt */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card title="Connections" subtitle="Every open network connection, refreshed every 3 seconds" bodyClassName="p-2 pt-3">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="bg-surface-2">
                  <th className={`${TH} rounded-l-lg`}>Local</th>
                  <th className={TH}>Remote</th>
                  <th className={TH}>Process</th>
                  <th className={`${TH} rounded-r-lg`}>Status</th>
                </tr>
              </thead>
              <tbody>
                {(status?.connections ?? []).map((c) => (
                  <tr key={c.local + c.remote} className="border-b border-line last:border-0">
                    <td className={`${TD} tabular font-mono text-[13px] text-ink`}>{c.local}</td>
                    <td className={`${TD} tabular font-mono text-[13px] text-ink`}>{c.remote}</td>
                    <td className={`${TD} text-ink-2`}>{c.process}</td>
                    <td className={TD}>
                      <Chip tone={c.external ? 'critical' : 'good'}>{c.external ? 'External' : 'Local'}</Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <InjectionCard latest={latest} />
      </div>

      {/* Audit log + permissions */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <AuditLogGate />
        <YourAccess />
      </div>
    </>
  )
}

function StatCard({ icon: Icon, title, children }: { icon: typeof Link2; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-4 rounded-2xl border border-line bg-surface/90 p-5 backdrop-blur">
      <Icon className="mt-0.5 size-6 shrink-0 text-ink-2" aria-hidden />
      <div className="min-w-0">
        <div className="mb-1 text-base font-semibold text-ink">{title}</div>
        {children}
      </div>
    </div>
  )
}

function CheckedAgo({ iso }: { iso: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  return <div className="mt-1 text-sm text-ink-2">{s < 2 ? 'Checked just now' : `Checked ${s} s ago`}</div>
}

function InjectionCard({ latest }: { latest?: { at: string; tool: string; target: string; source: string; reason: string } }) {
  const [steps, setSteps] = useState<AgentStep[]>([])
  const [running, setRunning] = useState(false)
  const cancelRef = useRef<(() => void) | null>(null)
  const toast = useToast()
  const { deny } = useRole()

  useEffect(() => () => cancelRef.current?.(), [])

  const run = () => {
    setSteps([])
    setRunning(true)
    cancelRef.current = api.runInjectionTest((e) => {
      if (e.type === 'step') {
        setSteps((list) => {
          const i = list.findIndex((s) => s.id === e.step.id)
          return i === -1 ? [...list, e.step] : list.map((s, j) => (j === i ? e.step : s))
        })
      } else if (e.type === 'blocked') {
        setRunning(false)
        toast({ title: 'Exfiltration blocked', body: `Request to ${e.attempt.target} stopped by the guard.`, tone: 'critical' })
      } else if (e.type === 'error') {
        setRunning(false)
        toast({ title: 'Test failed', body: e.message, tone: 'critical' })
      }
    })
  }

  return (
    <section
      className={`rounded-2xl border p-5 ${latest ? 'border-critical/40 bg-critical-soft' : 'border-line bg-surface/90'}`}
    >
      <div className="flex items-start gap-3">
        {latest ? (
          <ShieldAlert className="size-7 shrink-0 text-critical" aria-hidden />
        ) : (
          <ShieldCheck className="size-7 shrink-0 text-good" aria-hidden />
        )}
        <div className="min-w-0">
          <h2 className={`text-lg font-semibold ${latest ? 'text-critical-ink' : 'text-ink'}`}>
            {latest ? 'Blocked attempt' : 'No blocked attempts'}
          </h2>
          <div className="text-sm text-ink-2">
            {latest ? `${formatTime(latest.at)} · ${latest.tool}` : 'Run the test to try a poisoned vendor PDF.'}
          </div>
        </div>
      </div>

      {latest && (
        <dl className="mt-4 grid grid-cols-[5rem_1fr] gap-y-1.5 text-sm">
          <dt className="font-semibold text-ink">Target:</dt>
          <dd className="font-mono text-ink">{latest.target}</dd>
          <dt className="font-semibold text-ink">Source:</dt>
          <dd className="truncate text-ink">{latest.source}</dd>
          <dt className="font-semibold text-ink">Reason:</dt>
          <dd className="text-ink">{latest.reason}</dd>
        </dl>
      )}

      {steps.length > 0 && (
        <ol className="mt-4 space-y-1.5">
          {steps.map((s) => (
            <li key={s.id} className="flex items-center gap-2 text-sm">
              {s.status === 'running' ? (
                <Loader2 className="size-4 animate-spin text-ink-2" aria-hidden />
              ) : s.status === 'blocked' ? (
                <ShieldAlert className="size-4 text-critical" aria-hidden />
              ) : (
                <Check className="size-4 text-accent-ink" aria-hidden />
              )}
              <span className="font-mono text-xs font-semibold text-ink">{s.tool}</span>
              <span className={`truncate text-xs ${s.status === 'blocked' ? 'font-medium text-critical-ink' : 'text-ink-2'}`}>
                {s.summary}
              </span>
            </li>
          ))}
        </ol>
      )}

      <Button className="mt-4" variant={latest ? 'secondary' : 'primary'} icon={running ? Loader2 : Play} onClick={run} disabled={running} disabledReason={deny('run_security_tests')}>
        {running ? 'Running test…' : 'Run injection test'}
      </Button>
    </section>
  )
}

type StatusFilter = 'all' | AuditStatus

function AuditLog() {
  const version = useTopicVersion('audit')
  const log = useApi(() => api.getAuditLog(), [version])
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const { deny } = useRole()
  const toast = useToast()

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (log.data ?? [])
      .filter((r) => status === 'all' || r.status === status)
      .filter((r) => !q || `${r.user} ${r.role} ${r.tool} ${r.input} ${r.output}`.toLowerCase().includes(q))
  }, [log.data, query, status])

  const exportCsv = () => {
    const header = 'time,user,role,tool,input,output,status'
    const body = rows.map((r) => [r.at, r.user, r.role, r.tool, r.input, r.output, r.status].map((v) => `"${v.replace(/"/g, '""')}"`).join(','))
    const blob = new Blob([[header, ...body].join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'audit-log.csv'
    a.click()
    URL.revokeObjectURL(a.href)
    toast({ title: 'Audit log exported', body: `${rows.length} rows · audit-log.csv`, tone: 'good' })
  }

  return (
    <Card title="Audit log" subtitle="Every tool call: who, what, and whether the guard allowed it">
      <div className="mb-3 flex flex-wrap gap-2">
        <label className="relative flex min-w-48 flex-1 items-center">
          <span className="sr-only">Search audit log</span>
          <Search className="pointer-events-none absolute left-3 size-4 text-ink-2" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search audit log…"
            className="h-10 w-full rounded-xl border border-line bg-surface pr-3 pl-9 text-sm text-ink outline-none placeholder:text-muted focus:border-accent"
          />
        </label>
        <Select<StatusFilter>
          label="Status"
          value={status}
          onChange={setStatus}
          options={[
            { value: 'all', label: 'All statuses' },
            { value: 'allowed', label: 'Allowed' },
            { value: 'blocked', label: 'Blocked' },
            { value: 'denied', label: 'Denied' },
          ]}
          className="w-40"
        />
        <Button variant="soft" icon={Download} onClick={exportCsv} disabledReason={deny('export_audit_log')}>
          Export
        </Button>
      </div>

      {log.error ? (
        <ErrorNote message={log.error} />
      ) : (
        <div className="max-h-80 overflow-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead className="sticky top-0 z-10">
              <tr className="bg-surface-2">
                <th className={`${TH} rounded-l-lg`}>Time</th>
                <th className={TH}>User</th>
                <th className={TH}>Role</th>
                <th className={TH}>Tool</th>
                <th className={TH}>Input</th>
                <th className={`${TH} rounded-r-lg`}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0">
                  <td className={`${TD} tabular py-2.5 text-ink`}>{formatTime(r.at)}</td>
                  <td className={`${TD} py-2.5 whitespace-nowrap text-ink`}>{r.user}</td>
                  <td className={`${TD} py-2.5 whitespace-nowrap text-ink-2`}>{roleLabel(r.role)}</td>
                  <td className={`${TD} py-2.5 font-mono text-[13px] text-ink`}>{r.tool}</td>
                  <td className={`${TD} max-w-40 truncate py-2.5 text-ink-2`} title={`${r.input} → ${r.output}`}>
                    {r.input}
                  </td>
                  <td className={`${TD} py-2.5`}>
                    <Chip tone={AUDIT_TONE[r.status]}>{r.status[0].toUpperCase() + r.status.slice(1)}</Chip>
                  </td>
                </tr>
              ))}
              {log.data && rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sm text-muted">
                    No entries match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function AuditLogGate() {
  const { can, def } = useRole()
  if (can('view_audit_log')) return <AuditLog />
  return (
    <Card title="Audit log" subtitle="Every tool call: who, what, and whether the guard allowed it">
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <Lock className="size-5 text-ink-2" aria-hidden />
        <div className="text-sm font-medium text-ink">The audit log isn't visible to {def.label}s</div>
        <div className="max-w-xs text-xs text-muted">Plant Head, Maintenance Manager and System Admin can review it.</div>
      </div>
    </Card>
  )
}

/** What the signed-in role can do, from the permission matrix in lib/roles.ts. */
function YourAccess() {
  const { def, can } = useRole()
  return (
    <Card
      title="Your access"
      subtitle={`Signed in as ${def.user} · ${def.label}`}
      actions={
        <LinkButton to="/roles" size="sm" variant="soft">
          All roles
        </LinkButton>
      }
    >
      <ul className="divide-y divide-line text-sm">
        {PERMISSIONS.map((p) => {
          const ok = can(p.id)
          return (
            <li key={p.id} className="flex items-center justify-between gap-3 py-2">
              <span className={ok ? 'text-ink' : 'text-muted'}>{p.label}</span>
              {ok ? (
                <Check className="size-[18px] text-accent-ink" aria-label="Allowed" />
              ) : (
                <Minus className="size-4 text-axis" aria-label="Not allowed" />
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
