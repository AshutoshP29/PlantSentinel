import {
  AlertTriangle,
  CalendarDays,
  ChevronDown,
  Crosshair,
  FilePlus2,
  Gauge,
  Layers,
  MessageSquare,
  RefreshCw,
  Settings2,
  Thermometer,
  type LucideIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { isFailureMode } from '../api/adapters'
import { api } from '../api/client'
import { AS_OF } from '../api/mock'
import type { AssetDetail as Detail, Reading, TimelineEvent } from '../api/types'
import { GapChart } from '../components/charts/GapChart'
import { ShapBars } from '../components/charts/ShapBars'
import { Timeline } from '../components/charts/Timeline'
import { InspectionPaper } from '../components/SourceDocs'
import { Button, Card, Chip, EmptyState, ErrorNote, LinkButton, Modal, PageHeader, Restricted, Skeleton } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { formatDate, formatInr, formatNumber } from '../lib/format'
import { gapsFor } from '../lib/gaps'
import { useRole } from '../lib/role'
import { criticalityTone, STATUS_INFO, TD, TH } from '../lib/status'
import { useToast } from '../lib/toast'

const READING_ICON: Record<Reading['key'], LucideIcon> = {
  process_temp: Thermometer,
  speed: Gauge,
  torque: Settings2,
  wear: Layers,
}

const LEVEL_TONE = { high: 'critical', medium: 'warning', low: 'good' } as const

export default function AssetDetail() {
  const { tag = 'P-101' } = useParams()
  const navigate = useNavigate()
  const assets = useApi(() => api.getAssets(), [])
  const detail = useApi(() => api.getAssetDetail(tag), [tag])

  if (detail.error) return <ErrorNote message={detail.error} />
  if (!detail.data)
    return (
      <div className="grid gap-4 xl:grid-cols-3">
        <Skeleton className="h-24 xl:col-span-3" />
        <Skeleton className="h-96 xl:col-span-2" />
        <Skeleton className="h-96" />
      </div>
    )
  return (
    <DetailView
      d={detail.data}
      assetOptions={assets.data?.map((a) => ({ tag: a.tag, name: a.name })) ?? []}
      onSwitch={(t) => navigate(`/assets/${t}`)}
    />
  )
}

/** Main failure mode: the bad-actor row's, else the most frequent one in the history. */
function mainMode(d: Detail): string | null {
  if (d.bad_actor) return d.bad_actor.failure_mode
  const counts = new Map<string, number>()
  for (const w of d.work_orders) if (isFailureMode(w.failure_mode)) counts.set(w.failure_mode!, (counts.get(w.failure_mode!) ?? 0) + 1)
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
}

/** Last few work orders (and the latest inspection) as timeline events, oldest first. */
function timelineFor(d: Detail): TimelineEvent[] {
  const events: TimelineEvent[] = d.work_orders.slice(0, 6).map((w) => ({
    date: w.date,
    label: w.failure_mode ?? 'Work order',
    kind: isFailureMode(w.failure_mode) ? 'failure' : 'maintenance',
  }))
  if (d.latest_inspection) events.unshift({ date: d.latest_inspection.date, label: 'Inspection', kind: 'inspection' })
  return events.sort((a, b) => a.date.localeCompare(b.date)).slice(-6)
}

function DetailView({
  d,
  assetOptions,
  onSwitch,
}: {
  d: Detail
  assetOptions: { tag: string; name: string }[]
  onSwitch: (tag: string) => void
}) {
  const { asset, bad_actor: ba, risk } = d
  const { deny, can } = useRole()
  const showCost = can('view_costs')
  const toast = useToast()
  const navigate = useNavigate()
  const [scanOpen, setScanOpen] = useState(false)
  const [drafting, setDrafting] = useState(false)

  const mode = mainMode(d)
  const gaps = useMemo(() => (mode ? gapsFor(d.work_orders, mode, AS_OF) : []), [d.work_orders, mode])
  const timeline = useMemo(() => timelineFor(d), [d])

  const draft = async () => {
    setDrafting(true)
    try {
      const doc = await api.createWorkOrder(asset.tag)
      toast({ title: `${doc.file_name} drafted`, tone: 'good', action: { label: 'Open in documents', to: `/documents?doc=${doc.id}` } })
      navigate(`/documents?doc=${doc.id}`)
    } finally {
      setDrafting(false)
    }
  }

  const q = `Why does ${asset.tag} keep failing and what should we do?`
  const st = ba ? STATUS_INFO[ba.status] : null

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {asset.tag} · {asset.name}
            <label
              className="relative inline-flex size-9 items-center justify-center rounded-lg border border-line bg-surface text-ink-2 hover:bg-surface-2"
              title="Switch asset"
            >
              <ChevronDown className="size-5" aria-hidden />
              <select
                value={asset.tag}
                onChange={(e) => onSwitch(e.target.value)}
                className="absolute inset-0 cursor-pointer opacity-0"
                aria-label="Switch asset"
              >
                {assetOptions.map((a) => (
                  <option key={a.tag} value={a.tag}>
                    {a.tag} · {a.name}
                  </option>
                ))}
              </select>
            </label>
          </span>
        }
        description={
          <>
            <div>
              {asset.location} · {asset.type} · Installed {formatDate(asset.install_date)}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Chip size="md" tone={criticalityTone(asset.criticality)} icon={AlertTriangle}>
                {asset.criticality} criticality
              </Chip>
              {ba && (
                <Chip size="md" tone={ba.flagged ? 'critical' : 'neutral'} title="Bad-actor score: events × criticality weight × (1 + MTBF drop)">
                  Bad-actor score{' '}
                  <span className={`rounded-md px-1.5 ${ba.flagged ? 'bg-critical text-white' : 'bg-surface-3 text-ink'}`}>{ba.score.toFixed(1)}</span>
                </Chip>
              )}
              {st && ba?.flagged && (
                <Chip size="md" tone="warning" icon={RefreshCw} title={st.title}>
                  {ba.status === 'recurring' ? 'Recurring failures' : 'MTBF dropping'}
                </Chip>
              )}
            </div>
          </>
        }
        actions={
          <>
            <LinkButton to={`/agent?q=${encodeURIComponent(q)}&tag=${asset.tag}`} variant="primary" icon={MessageSquare}>
              Ask the agent
            </LinkButton>
            <Button icon={FilePlus2} onClick={draft} disabled={drafting} disabledReason={deny('draft_work_order')}>
              {drafting ? 'Drafting…' : 'Draft work order'}
            </Button>
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Left column */}
        <div className="flex min-w-0 flex-col gap-4 xl:col-span-2">
          <Card title="Failure timeline" subtitle="Most recent work orders and inspections">
            {timeline.length ? <Timeline events={timeline} /> : <p className="text-sm text-muted">No work orders yet.</p>}
          </Card>

          <Card
            title={mode ? `Days between failures · ${mode}` : 'Days between failures'}
            subtitle="One bar per failure: how long the asset ran since the previous one"
          >
            {gaps.length ? (
              <GapChart gaps={gaps} />
            ) : (
              <p className="py-6 text-sm text-muted">Needs at least two failures of the same kind.</p>
            )}
          </Card>

          <Card title="Work orders" subtitle={`${d.work_orders.length} records · original free text as written by the technician`} bodyClassName="p-2 pt-3">
            <div className="max-h-[26rem] overflow-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-2">
                    <th className={`${TH} rounded-l-lg`}>Date</th>
                    <th className={TH}>Original text</th>
                    <th className={TH}>Action</th>
                    <th className={`${TH} text-right`}>Downtime</th>
                    <th className={`${TH} rounded-r-lg text-right`}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {d.work_orders.map((w) => (
                    <tr key={w.id} className="border-b border-line last:border-0">
                      <td className={`${TD} tabular whitespace-nowrap text-ink`}>{formatDate(w.date)}</td>
                      <td className={TD}>
                        <span className="font-mono text-[13px] text-ink">{w.description}</span>
                        {w.failure_mode && <div className="mt-0.5 text-xs text-muted">→ {w.failure_mode}</div>}
                      </td>
                      <td className={`${TD} text-ink-2`}>{w.action_taken}</td>
                      <td className={`${TD} tabular text-right whitespace-nowrap text-ink`}>{w.downtime_hrs} h</td>
                      <td className={`${TD} tabular text-right whitespace-nowrap text-ink`}>{showCost ? formatInr(w.cost_inr) : <Restricted />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        {/* Right column */}
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Risk score" subtitle="Failure risk from current operating conditions">
            {risk ? (
              <>
                <div className="flex items-center gap-4">
                  <div className={`shrink-0 rounded-2xl px-4 py-2 whitespace-nowrap ${risk.level === 'high' ? 'bg-critical-soft' : risk.level === 'medium' ? 'bg-warning-soft' : 'bg-good-soft'}`}>
                    <span
                      className={`text-5xl font-bold ${risk.level === 'high' ? 'text-critical-ink' : risk.level === 'medium' ? 'text-warning-ink' : 'text-good-ink'}`}
                    >
                      {risk.score}
                    </span>
                    <span className="text-lg text-ink-2"> / 100</span>
                  </div>
                  <div className="min-w-0 border-l border-line pl-4">
                    <Chip tone={LEVEL_TONE[risk.level]}>{risk.level[0].toUpperCase() + risk.level.slice(1)} risk</Chip>
                    <div className="mt-1.5 text-xs text-muted">{risk.model_note}</div>
                  </div>
                </div>
                <div className="mt-5 mb-2 text-sm font-semibold text-ink">Top contributing factors</div>
                <ShapBars factors={risk.factors} />
              </>
            ) : (
              <EmptyState icon={Gauge} title="No risk score yet">
                The model has no operating condition for this asset.
              </EmptyState>
            )}
          </Card>

          {d.readings.length > 0 && (
            <Card title="Current readings" subtitle="Operating condition used by the risk model">
              <div className="grid grid-cols-2 gap-3">
                {d.readings.map((r) => {
                  const Icon = READING_ICON[r.key]
                  return (
                    <div key={r.key} className="flex items-center gap-3 rounded-xl border border-line bg-surface-2/50 px-3 py-2.5">
                      <Icon className="size-6 shrink-0 text-accent-ink" aria-hidden />
                      <div className="min-w-0">
                        <div className="text-xs text-ink-2">{r.label}</div>
                        <div className="text-lg font-semibold text-ink">
                          {formatNumber(r.value)} <span className="text-sm font-normal text-ink-2">{r.unit}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          )}

          <Card title="Latest inspection">
            {d.latest_inspection ? (
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => setScanOpen(true)}
                  className="h-36 w-32 shrink-0 overflow-hidden rounded-md border border-line transition hover:shadow-md"
                  aria-label="Open scan"
                >
                  <div className="pointer-events-none w-[220%] origin-top-left scale-[0.455]">
                    <InspectionPaper inspection={d.latest_inspection} compact />
                  </div>
                </button>
                <div className="min-w-0 space-y-2 border-l border-line pl-4 text-sm">
                  <div className="flex items-center gap-2 text-ink">
                    <CalendarDays className="size-4 text-ink-2" aria-hidden />
                    {formatDate(d.latest_inspection.date)}
                  </div>
                  {d.latest_inspection.findings
                    .filter((f) => f.flagged)
                    .slice(0, 1)
                    .map((f) => (
                      <div key={f.item} className="flex items-start gap-2 text-ink">
                        <Crosshair className="mt-0.5 size-4 shrink-0 text-ink-2" aria-hidden />
                        <span>
                          {f.item}: <span className="font-semibold">{f.result.replace('Misalignment observed: ', 'misaligned ')}</span>
                        </span>
                      </div>
                    ))}
                  <Button size="sm" variant="soft" onClick={() => setScanOpen(true)}>
                    View scan
                  </Button>
                </div>
              </div>
            ) : (
              <EmptyState icon={CalendarDays} title="No inspection on file">
                Upload a scanned report for {asset.tag} to see findings here.
              </EmptyState>
            )}
          </Card>
        </div>
      </div>

      {d.latest_inspection && (
        <Modal open={scanOpen} onClose={() => setScanOpen(false)} title={`${d.latest_inspection.report_no} · ${asset.tag}`}>
          <InspectionPaper inspection={d.latest_inspection} />
        </Modal>
      )}
    </>
  )
}
