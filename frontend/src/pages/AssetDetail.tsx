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
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AssetDetail as Detail, Reading } from '../api/types'
import { ShapBars } from '../components/charts/ShapBars'
import { Timeline } from '../components/charts/Timeline'
import { TrendChart } from '../components/charts/TrendChart'
import { InspectionPaper } from '../components/SourceDocs'
import { Button, Card, Chip, EmptyState, ErrorNote, LinkButton, Modal, PageHeader, Restricted, Skeleton } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { formatDate, formatInr, formatNumber } from '../lib/format'
import { useRole } from '../lib/role'
import { criticalityTone, STATUS_INFO, TD, TH } from '../lib/status'
import { useToast } from '../lib/toast'

const READING_ICON: Record<Reading['key'], LucideIcon> = {
  temperature: Thermometer,
  speed: Gauge,
  torque: Settings2,
  tool_wear: Layers,
}

export default function AssetDetail() {
  const { tag = 'P-101' } = useParams()
  const navigate = useNavigate()
  const assets = useApi(() => api.getAssets(), [])
  const detail = useApi(() => api.getAssetDetail(tag), [tag])

  return (
    <>
      {detail.error ? (
        <ErrorNote message={detail.error} />
      ) : !detail.data ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-24 lg:col-span-3" />
          <Skeleton className="h-96 lg:col-span-2" />
          <Skeleton className="h-96" />
        </div>
      ) : (
        <DetailView
          d={detail.data}
          assetOptions={assets.data?.map((a) => ({ tag: a.tag, name: a.name })) ?? []}
          onSwitch={(t) => navigate(`/assets/${t}`)}
        />
      )}
    </>
  )
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
  const { asset } = d
  const { deny, can } = useRole()
  const showCost = can('view_costs')
  const toast = useToast()
  const navigate = useNavigate()
  const [scanOpen, setScanOpen] = useState(false)
  const [drafting, setDrafting] = useState(false)
  const st = STATUS_INFO[d.status]

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

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {asset.tag} · {asset.name}
            <label className="relative inline-flex size-9 items-center justify-center rounded-lg border border-line bg-surface text-ink-2 hover:bg-surface-2" title="Switch asset">
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
              <Chip size="md" tone={d.score >= 80 ? 'critical' : d.score >= 60 ? 'warning' : 'neutral'} title="Bad-actor score: frequency × criticality × cost trend">
                Bad-actor score <span className="rounded-md bg-critical px-1.5 text-white">{d.score}</span>
              </Chip>
              {d.status !== 'watch' && (
                <Chip size="md" tone={st.tone === 'critical' ? 'warning' : st.tone} icon={RefreshCw} title={st.title}>
                  {d.status === 'recurring' ? 'Recurring failures' : 'MTBF dropping'}
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
            <Button
              icon={FilePlus2}
              onClick={draft}
              disabled={drafting}
              disabledReason={deny('draft_work_order')}
            >
              {drafting ? 'Drafting…' : 'Draft work order'}
            </Button>
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Left column */}
        <div className="flex min-w-0 flex-col gap-4 xl:col-span-2">
          <Card title="Failure timeline" subtitle="Recent work orders and inspections">
            <Timeline events={d.timeline} />
          </Card>

          <Card title="Work orders" subtitle="Original free text as written by the technician" bodyClassName="p-2 pt-3">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-sm">
                <thead>
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

          <Card title="MTBF trend · days" subtitle={`Mean time between failures for ${asset.tag}, by month`}>
            <TrendChart data={d.mtbf_trend} height={240} name={`${asset.tag} MTBF`} />
          </Card>
        </div>

        {/* Right column */}
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Risk score" subtitle="Failure risk from current operating conditions">
            <div className="flex items-center gap-4">
              <div className="rounded-2xl bg-critical-soft px-4 py-2">
                <span className="text-5xl font-bold text-critical-ink">{d.risk.score}</span>
                <span className="text-lg text-ink-2"> / 100</span>
              </div>
              <div className="border-l border-line pl-4">
                <div className="text-xs text-ink-2">Predicted type</div>
                <div className="font-semibold text-ink">{d.risk.predicted_type}</div>
                <div className="mt-0.5 text-xs text-muted">{d.risk.model_note}</div>
              </div>
            </div>
            <div className="mt-5 mb-2 text-sm font-semibold text-ink">Top contributing factors</div>
            <ShapBars factors={d.risk.factors} />
          </Card>

          <Card title="Current readings">
            <div className="grid grid-cols-2 gap-3">
              {d.readings.map((r) => {
                const Icon = READING_ICON[r.key]
                return (
                  <div key={r.key} className="flex items-center gap-3 rounded-xl border border-line bg-surface-2/50 px-3 py-2.5">
                    <Icon className="size-6 shrink-0 text-accent-ink" aria-hidden />
                    <div>
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
