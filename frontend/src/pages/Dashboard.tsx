import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  Clock,
  Download,
  Flag,
  MessageSquare,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { UNITS } from '../api/mock'
import type { AssetType, BadActor, Criticality, DashboardFilters } from '../api/types'
import { FailureModesChart } from '../components/charts/FailureModesChart'
import { TrendChart } from '../components/charts/TrendChart'
import {
  Button,
  Card,
  Chip,
  DataTable,
  ErrorNote,
  LinkButton,
  PageHeader,
  Restricted,
  Segmented,
  Select,
  Skeleton,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { formatDate, formatInr, formatMonth, formatNumber, formatPct } from '../lib/format'
import { useRole } from '../lib/role'
import { criticalityTone, STATUS_INFO, TD, TH } from '../lib/status'
import { useToast } from '../lib/toast'

type WindowOpt = '90' | '180' | '365'

export default function Dashboard() {
  const [win, setWin] = useState<WindowOpt>('180')
  const [unit, setUnit] = useState('')
  const [type, setType] = useState('')
  const [crit, setCrit] = useState('')

  const filters: DashboardFilters = {
    window_days: Number(win) as DashboardFilters['window_days'],
    unit: unit || undefined,
    asset_type: (type || undefined) as AssetType | undefined,
    criticality: (crit || undefined) as Criticality | undefined,
  }
  const key = [win, unit, type, crit]

  const summary = useApi(() => api.getSummary(filters), key)
  const actors = useApi(() => api.getBadActors(filters, 10), key)
  const modes = useApi(() => api.getFailureModes(filters), key)
  const trend = useApi(() => api.getPlantMtbf(), [])

  const { deny } = useRole()
  const toast = useToast()
  const [exporting, setExporting] = useState(false)

  const exportReport = async () => {
    setExporting(true)
    try {
      const doc = await api.exportBadActorReport()
      toast({ title: 'Bad-actor report created', body: doc.file_name, tone: 'good', action: { label: 'Open documents', to: `/documents?doc=${doc.id}` } })
    } catch (e) {
      toast({ title: 'Export failed', body: e instanceof Error ? e.message : String(e), tone: 'critical' })
    } finally {
      setExporting(false)
    }
  }

  const s = summary.data
  const top = actors.data?.[0]

  return (
    <>
      <PageHeader
        title="Reliability dashboard"
        description={
          s
            ? `Last ${s.window_days} days · ${formatNumber(s.work_orders_parsed)} work orders parsed · as of ${formatDate(s.as_of)}`
            : 'Recurring failures, ranked'
        }
        actions={
          <Button
            variant="primary"
            icon={Download}
            onClick={exportReport}
            disabled={exporting}
            disabledReason={deny('export_reports')}
          >
            {exporting ? 'Exporting…' : 'Export report .xlsx'}
          </Button>
        }
      />

      {/* Filters */}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Select<WindowOpt>
          label="Time window"
          icon={CalendarDays}
          value={win}
          onChange={setWin}
          options={[
            { value: '90', label: '90 days' },
            { value: '180', label: '180 days' },
            { value: '365', label: '365 days' },
          ]}
        />
        <Select
          label="Unit"
          value={unit}
          onChange={setUnit}
          options={[{ value: '', label: 'All units' }, ...UNITS.map((u) => ({ value: u, label: u }))]}
        />
        <Select
          label="Asset type"
          value={type}
          onChange={setType}
          options={[
            { value: '', label: 'All asset types' },
            ...['Pump', 'Compressor', 'Heat exchanger', 'Motor'].map((t) => ({ value: t, label: t })),
          ]}
        />
        <Select
          label="Criticality"
          value={crit}
          onChange={setCrit}
          options={[
            { value: '', label: 'All criticalities' },
            ...['High', 'Medium', 'Low'].map((c) => ({ value: c, label: c })),
          ]}
        />
      </div>

      {/* Top bad actor */}
      {actors.data && !top ? null : top ? <TopActorBanner actor={top} windowDays={filters.window_days} /> : <Skeleton className="h-24" />}

      {/* Stat tiles */}
      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {s ? (
          <>
            <StatTile
              icon={Clock}
              label="Plant MTBF"
              value={`${s.plant_mtbf_days} days`}
              foot={
                s.plant_mtbf_change_pct != null ? (
                  <span className={s.plant_mtbf_change_pct < 0 ? 'text-critical-ink' : 'text-good-ink'}>
                    {formatPct(s.plant_mtbf_change_pct)} <span className="text-muted">vs previous period</span>
                  </span>
                ) : (
                  `${s.assets_monitored} assets, last ${s.window_days} days`
                )
              }
            />
            <StatTile icon={AlertTriangle} label="Failure events" value={formatNumber(s.failure_events)} foot={`Last ${s.window_days} days`} />
            <StatTile
              icon={Flag}
              label="Bad actors flagged"
              value={formatNumber(s.bad_actors_flagged)}
              foot={`of ${s.assets_monitored} assets monitored`}
              tint="critical"
            />
            <StatTile icon={Wrench} label="Downtime" value={`${formatNumber(s.downtime_hrs)} h`} foot={`Unplanned, last ${s.window_days} days`} tint="warning" />
          </>
        ) : (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[112px]" />)
        )}
      </div>

      {/* Ranked bad actors */}
      <Card
        className="mt-4"
        title="Top 10 bad actors"
        subtitle="Ranked by the backend bad-actor score · Recurring = 3+ events of one failure mode in 180 days · Review = MTBF fell more than 40%"
        bodyClassName="pt-3 pb-2"
      >
        {actors.error ? (
          <div className="px-5 pb-3">
            <ErrorNote message={actors.error} />
          </div>
        ) : actors.data ? (
          actors.data.length ? (
            <BadActorTable rows={actors.data} />
          ) : (
            <p className="px-5 pb-4 text-sm text-ink-2">No assets match these filters.</p>
          )
        ) : (
          <div className="px-5 pb-3">
            <Skeleton className="h-72" />
          </div>
        )}
      </Card>

      {/* Charts */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartCard
          title="Failure modes"
          subtitle="Work orders grouped by clustering their free text"
          chart={modes.data && <FailureModesChart data={modes.data} windowDays={filters.window_days} />}
          table={
            modes.data && (
              <DataTable
                columns={[
                  { key: 'name', label: 'Failure mode' },
                  { key: 'events', label: 'Events', numeric: true },
                ]}
                rows={modes.data.map((m) => ({ name: m.name, events: m.events }))}
              />
            )
          }
        />
        <ChartCard
          title="Plant MTBF trend"
          subtitle="Mean time between failures, all assets, by month"
          chart={trend.data && <TrendChart data={trend.data} name="Plant MTBF" />}
          table={
            trend.data && (
              <DataTable
                columns={[
                  { key: 'month', label: 'Month' },
                  { key: 'mtbf', label: 'MTBF (days)', numeric: true },
                ]}
                rows={trend.data.map((p) => ({ month: formatMonth(p.month), mtbf: p.mtbf_days }))}
              />
            )
          }
        />
      </div>
    </>
  )
}

function TopActorBanner({ actor, windowDays }: { actor: BadActor; windowDays: number }) {
  const q = `Why does ${actor.tag} keep failing and what should we do?`
  return (
    <section className="relative flex flex-wrap items-center gap-4 overflow-hidden rounded-2xl border border-line bg-surface/90 py-4 pr-5 pl-7 backdrop-blur">
      <span className="absolute inset-y-3 left-3 w-1 rounded-full bg-critical" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-lg font-bold text-ink md:text-xl">Top bad actor · {actor.tag}</span>
          <span className="text-sm text-ink-2">
            {actor.name} · {actor.location}
          </span>
        </div>
        <div className="mt-0.5 text-sm text-ink-2 md:text-base">
          {actor.events} {actor.failure_mode.toLowerCase()} events in {windowDays} days
          {actor.mtbf_change_pct !== 0 && (
            <>
              {' '}
              · MTBF{' '}
              <span className={`font-semibold ${actor.mtbf_change_pct < 0 ? 'text-critical-ink' : 'text-good-ink'}`}>
                {actor.mtbf_change_pct < 0 ? 'down' : 'up'} {Math.abs(actor.mtbf_change_pct)}%
              </span>{' '}
              ({actor.mtbf_prev_days} → {actor.mtbf_days} days)
            </>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <LinkButton to={`/agent?q=${encodeURIComponent(q)}&tag=${actor.tag}`} variant="primary" icon={MessageSquare}>
          Ask why it keeps failing
        </LinkButton>
        <LinkButton to={`/assets/${actor.tag}`} icon={ArrowRight}>
          View asset
        </LinkButton>
      </div>
    </section>
  )
}

function StatTile({
  icon: Icon,
  label,
  value,
  foot,
  tint,
}: {
  icon: LucideIcon
  label: string
  value: string
  foot?: ReactNode
  tint?: 'critical' | 'warning'
}) {
  const bg = tint === 'critical' ? 'bg-critical-soft/70' : tint === 'warning' ? 'bg-warning-soft/70' : 'bg-surface/90'
  const iconColor = tint === 'critical' ? 'text-critical' : tint === 'warning' ? 'text-warning-ink' : 'text-accent-ink'
  return (
    <div className={`rounded-2xl border border-line px-4 py-4 backdrop-blur ${bg}`}>
      <div className="flex items-center gap-2 text-sm text-ink-2">
        <Icon className={`size-[18px] ${iconColor}`} aria-hidden />
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold text-ink md:text-3xl">{value}</div>
      {foot && <div className="mt-1 text-xs text-muted">{foot}</div>}
    </div>
  )
}

function ChartCard({
  title,
  subtitle,
  chart,
  table,
}: {
  title: string
  subtitle: string
  chart: ReactNode
  table: ReactNode
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <Card
      title={title}
      subtitle={subtitle}
      actions={
        <Segmented
          label={`${title} view`}
          value={view}
          onChange={setView}
          options={[
            { value: 'chart', label: 'Chart' },
            { value: 'table', label: 'Table' },
          ]}
        />
      }
    >
      {chart ? (view === 'chart' ? chart : table) : <Skeleton className="h-72" />}
    </Card>
  )
}

function BadActorTable({ rows }: { rows: BadActor[] }) {
  const navigate = useNavigate()
  const showCost = useRole().can('view_costs')
  const maxScore = Math.max(...rows.map((r) => r.score), 1)
  return (
    <div className="overflow-x-auto px-2">
      <table className="w-full min-w-[920px] text-sm">
        <thead>
          <tr className="bg-surface-2">
            <th className={`${TH} rounded-l-lg`}>Asset</th>
            <th className={TH}>Criticality</th>
            <th className={TH}>Failure mode</th>
            <th className={`${TH} text-right`}>Events</th>
            <th className={`${TH} text-right`}>MTBF</th>
            <th className={`${TH} text-right`}>Change</th>
            <th className={`${TH} text-right`}>Cost</th>
            <th className={`${TH} pl-6`}>Score</th>
            <th className={`${TH} rounded-r-lg`}>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const st = STATUS_INFO[r.status]
            return (
              <tr
                key={`${r.tag}|${r.failure_mode}`}
                onClick={() => navigate(`/assets/${r.tag}`)}
                className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2/60"
              >
                <td className={TD}>
                  <Link
                    to={`/assets/${r.tag}`}
                    onClick={(e) => e.stopPropagation()}
                    className="font-semibold text-accent-ink hover:underline"
                  >
                    {r.tag}
                  </Link>
                  <div className="text-xs text-muted">{r.name}</div>
                </td>
                <td className={TD}>
                  <Chip tone={criticalityTone(r.criticality)}>{r.criticality}</Chip>
                </td>
                <td className={`${TD} text-ink`}>{r.failure_mode}</td>
                <td className={`${TD} tabular text-right text-ink`}>{r.events}</td>
                <td className={`${TD} tabular text-right text-ink`} title={r.mtbf_days == null ? 'Needs 2+ events in the window' : undefined}>
                  {r.mtbf_days == null ? <span className="text-muted">—</span> : `${r.mtbf_days} d`}
                </td>
                <td className={`${TD} text-right`}>
                  {r.mtbf_change_pct === 0 ? (
                    <span className="text-muted">—</span>
                  ) : (
                    <Chip tone={r.mtbf_change_pct < 0 ? 'critical' : 'good'}>{formatPct(r.mtbf_change_pct)}</Chip>
                  )}
                </td>
                <td className={`${TD} tabular text-right text-ink-2`}>{showCost ? formatInr(r.cost_inr) : <Restricted />}</td>
                <td className={`${TD} pl-6`}>
                  <ScoreMeter score={r.score} max={maxScore} />
                </td>
                <td className={TD}>
                  <Chip tone={st.tone} title={st.title}>
                    {st.label}
                  </Chip>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** The backend score is unbounded, so the bar is relative to the top row. */
function ScoreMeter({ score, max }: { score: number; max: number }) {
  const rel = score / max
  const fill = rel >= 0.66 ? 'bg-critical' : rel >= 0.33 ? 'bg-serious' : 'bg-warning'
  return (
    <div className="flex items-center gap-2" title={`Bad-actor score ${score} (events × criticality weight × (1 + MTBF drop))`}>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-3">
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${Math.max(4, rel * 100)}%` }} />
      </div>
      <span className="tabular w-9 text-right font-semibold text-ink">{score.toFixed(1)}</span>
    </div>
  )
}
