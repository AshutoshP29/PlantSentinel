import {
  ArrowRight,
  CheckCircle2,
  CloudUpload,
  Database,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  Info,
  Layers,
  Loader2,
  Sparkles,
  Trash2,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { keyFinding } from '../api/adapters'
import { api } from '../api/client'
import { p101Inspection } from '../api/mock'
import type { ClusterRun, IngestFile, IngestKind, IngestStatus, IngestSummary } from '../api/types'
import { InspectionPaper } from '../components/SourceDocs'
import { Button, Card, Chip, EmptyState, PageHeader } from '../components/ui'
import { formatDate, formatNumber } from '../lib/format'
import type { Tone } from '../lib/status'
import { TD, TH } from '../lib/status'
import { useRole } from '../lib/role'
import { useToast } from '../lib/toast'

const KIND: Record<IngestKind, { label: string; icon: LucideIcon }> = {
  work_orders: { label: 'Work orders', icon: FileSpreadsheet },
  manual: { label: 'Manual', icon: FileText },
  scan: { label: 'Scan', icon: ImageIcon },
}

const STATUS: Record<IngestStatus, { label: string; tone: Tone; icon: LucideIcon; spin?: boolean }> = {
  queued: { label: 'Queued', tone: 'neutral', icon: Loader2 },
  parsing: { label: 'Parsing', tone: 'accent', icon: Loader2, spin: true },
  ocr: { label: 'Reading scan', tone: 'accent', icon: Loader2, spin: true },
  indexed: { label: 'Indexed', tone: 'good', icon: CheckCircle2 },
  done: { label: 'Done', tone: 'good', icon: CheckCircle2 },
  failed: { label: 'Failed', tone: 'critical', icon: XCircle },
}

const ACCEPT = '.xlsx,.xls,.csv,.pdf,.jpg,.jpeg,.png'

export default function Upload() {
  const [files, setFiles] = useState<IngestFile[]>([])
  const [summary, setSummary] = useState<IngestSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [clusters, setClusters] = useState<ClusterRun | null>(null)
  const [clustering, setClustering] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const toast = useToast()
  const { deny } = useRole()

  const ingest = async (list: { name: string; file?: File }[]) => {
    if (!list.length || busy) return
    setBusy(true)
    setSummary(null)
    setClusters(null)
    try {
      const s = await api.ingest(list, setFiles)
      setSummary(s)
    } catch (e) {
      toast({ title: 'Upload failed', body: e instanceof Error ? e.message : String(e), tone: 'critical' })
    } finally {
      setBusy(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = Array.from(e.dataTransfer.files)
    void ingest(dropped.map((f) => ({ name: f.name, file: f })))
  }

  const runClustering = async () => {
    setClustering(true)
    try {
      setClusters(await api.runClustering())
    } finally {
      setClustering(false)
    }
  }

  const clear = async () => {
    await api.clearData()
    setFiles([])
    setSummary(null)
    setClusters(null)
  }

  const hasScan = files.some((f) => f.kind === 'scan' && f.status === 'done')

  return (
    <>
      <PageHeader
        title="Upload plant data"
        description="Turn maintenance records into searchable evidence."
        actions={
          <>
            <Button
              variant="soft"
              icon={Database}
              onClick={() => ingest(api.demoFileNames().map((name) => ({ name })))}
              disabled={busy}
            >
              Load demo dataset
            </Button>
            <Button icon={Trash2} onClick={clear} disabled={busy || !files.length} disabledReason={deny('clear_data')}>
              Clear data
            </Button>
          </>
        }
      />

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-8 text-center transition ${
          dragOver ? 'border-accent bg-accent-soft/60' : 'border-axis bg-surface/60'
        }`}
      >
        <CloudUpload className="size-9 text-accent-ink" aria-hidden />
        <div className="text-base text-ink">
          Drop files here or{' '}
          <button type="button" onClick={() => inputRef.current?.click()} className="font-semibold text-accent-ink underline underline-offset-2">
            browse
          </button>
        </div>
        <div className="text-sm text-muted">.xlsx · .csv · .pdf · .jpg · .png</div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            const picked = Array.from(e.target.files ?? [])
            e.target.value = ''
            void ingest(picked.map((f) => ({ name: f.name, file: f })))
          }}
        />
      </div>

      {/* File list */}
      {files.length > 0 && (
        <Card className="mt-4" bodyClassName="p-2">
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="bg-surface-2">
                  <th className={`${TH} rounded-l-lg`}>File</th>
                  <th className={TH}>Type</th>
                  <th className={TH}>Details</th>
                  <th className={`${TH} rounded-r-lg`}>Status</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f) => {
                  const k = KIND[f.kind]
                  const st = STATUS[f.status]
                  return (
                    <tr key={f.id} className="border-b border-line last:border-0">
                      <td className={`${TD} py-2.5`}>
                        <span className="flex items-center gap-2.5 text-ink">
                          <k.icon className="size-[18px] shrink-0 text-ink-2" aria-hidden />
                          <span className="truncate">{f.name}</span>
                        </span>
                      </td>
                      <td className={`${TD} py-2.5 text-ink-2`}>{k.label}</td>
                      <td className={`${TD} tabular py-2.5 text-muted`}>{f.detail ?? '—'}</td>
                      <td className={`${TD} py-2.5`}>
                        <Chip tone={st.tone}>
                          <st.icon className={`size-3.5 ${st.spin ? 'animate-spin' : ''}`} aria-hidden />
                          {st.label}
                        </Chip>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Summary */}
      {summary && (
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-accent/25 bg-accent-soft/60 px-5 py-3.5">
          <Layers className="size-5 text-accent-ink" aria-hidden />
          <span className="text-base font-semibold text-ink">
            {formatNumber(summary.records_parsed)} records parsed · {summary.scans_ocrd} scans OCR'd ·{' '}
            {summary.manuals_indexed} manuals indexed
          </span>
        </div>
      )}

      {/* Scan preview + clustering */}
      {summary && (
        <>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <Card title="Scan preview" subtitle="Text read from the scanned inspection report">
              {hasScan ? (
                <div className="grid gap-4 sm:grid-cols-[minmax(0,15rem)_1fr] sm:items-center">
                  <InspectionPaper inspection={p101Inspection} compact />
                  <div className="space-y-3">
                    <div className="text-lg font-semibold text-ink">Asset: {p101Inspection.tag}</div>
                    <div className="text-xs text-muted">
                      {p101Inspection.report_no} · {formatDate(p101Inspection.date)}
                    </div>
                    {(() => {
                      const key = keyFinding(p101Inspection)
                      const others = p101Inspection.findings.filter((f) => f.flagged && f !== key).slice(0, 2)
                      return (
                        <>
                          {key && <div className="rounded-lg bg-highlight px-3 py-2 font-semibold text-ink">Finding: {key.result}</div>}
                          {others.map((f) => (
                            <div key={f.item} className="px-3 text-sm text-ink">
                              {f.item}: {f.result}
                            </div>
                          ))}
                        </>
                      )
                    })()}
                  </div>
                </div>
              ) : (
                <EmptyState icon={ImageIcon} title="No scans in this upload">
                  Add a .jpg or .png inspection report to see its findings here.
                </EmptyState>
              )}
            </Card>

            <Card
              title="Failure clustering"
              subtitle="Messy work-order text grouped into clean failure modes"
              actions={
                <Button variant="primary" size="sm" icon={clustering ? Loader2 : Sparkles} onClick={runClustering} disabled={clustering}>
                  {clustering ? 'Clustering…' : clusters ? 'Run again' : 'Run clustering'}
                </Button>
              }
            >
              {clusters ? (
                <div className="divide-y divide-line">
                  {clusters.clusters.map((c) => (
                    <div key={c.name} className="grid items-center gap-3 py-3 first:pt-1 sm:grid-cols-[1fr_auto_1fr]">
                      <div className="flex flex-wrap gap-1.5">
                        {c.samples.map((t) => (
                          <span key={t} className="rounded-md bg-surface-2 px-2 py-1 font-mono text-xs text-ink-2">
                            {t}
                          </span>
                        ))}
                      </div>
                      <ArrowRight className="hidden size-5 text-muted sm:block" aria-hidden />
                      <div className="rounded-xl bg-accent-soft px-3 py-2 text-sm font-semibold text-accent-ink">
                        {c.name} · {c.events} events
                      </div>
                    </div>
                  ))}
                  <p className="pt-3 text-xs text-muted">
                    {[
                      clusters.metrics.n_work_orders != null && `${clusters.metrics.n_work_orders} work orders`,
                      clusters.metrics.n_clusters != null && `${clusters.metrics.n_clusters} clusters`,
                      clusters.metrics.n_failure_modes != null && `${clusters.metrics.n_failure_modes} failure modes`,
                      clusters.metrics.silhouette != null && `silhouette ${clusters.metrics.silhouette.toFixed(2)}`,
                      clusters.metrics.ari_vs_truth != null && `agreement with ground truth (ARI) ${clusters.metrics.ari_vs_truth.toFixed(2)}`,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
              ) : (
                <EmptyState icon={Sparkles} title={clustering ? 'Grouping work orders…' : 'Ready to cluster'}>
                  {clustering
                    ? 'Embedding descriptions and finding groups.'
                    : `Group ${formatNumber(summary.records_parsed)} work-order descriptions into failure modes.`}
                </EmptyState>
              )}
            </Card>
          </div>
          <p className="mt-3 flex items-center gap-2 text-sm text-muted">
            <Info className="size-4" aria-hidden /> Review extracted findings before continuing.
          </p>
        </>
      )}
    </>
  )
}
