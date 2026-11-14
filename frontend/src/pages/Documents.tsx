import { CheckCircle2, Download, FileSpreadsheet, FileText, Pencil, Plus, Save, Search, X } from 'lucide-react'
import { useMemo, useState, type MouseEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useTopicVersion } from '../api/events'
import type { DocKind, DocumentItem, WorkOrderDraft } from '../api/types'
import { Button, Card, Chip, EmptyState, ErrorNote, Modal, PageHeader, Restricted, Select, Skeleton } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { formatDate, formatInr, formatWhen } from '../lib/format'
import { useRole } from '../lib/role'
import { criticalityTone, TD, TH } from '../lib/status'
import { useToast } from '../lib/toast'

type TypeFilter = 'all' | DocKind

export default function Documents() {
  const version = useTopicVersion('documents')
  const docs = useApi(() => api.getDocuments(), [version])
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [type, setType] = useState<TypeFilter>('all')
  const [newOpen, setNewOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const { deny } = useRole()
  const toast = useToast()

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (docs.data ?? [])
      .filter((d) => type === 'all' || d.kind === type)
      .filter((d) => !q || `${d.file_name} ${d.tag ?? ''} ${d.created_by}`.toLowerCase().includes(q))
  }, [docs.data, query, type])

  const selectedId = params.get('doc') ?? list[0]?.id
  const selected = docs.data?.find((d) => d.id === selectedId) ?? null
  const select = (id: string) => setParams({ doc: id }, { replace: true })

  const exportReport = async () => {
    setBusy(true)
    try {
      const doc = await api.exportBadActorReport()
      select(doc.id)
      toast({ title: 'Bad-actor report created', body: doc.file_name, tone: 'good' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Documents"
        description="Review and download maintenance outputs."
        actions={
          <>
            <Button variant="primary" icon={Plus} onClick={() => setNewOpen(true)} disabledReason={deny('draft_work_order')}>
              New work order
            </Button>
            <Button icon={Download} onClick={exportReport} disabled={busy} disabledReason={deny('export_reports')}>
              Export bad-actor report
            </Button>
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* List */}
        <Card bodyClassName="p-4">
          <div className="mb-3 flex flex-wrap gap-2">
            <label className="relative flex min-w-48 flex-1 items-center">
              <span className="sr-only">Search documents</span>
              <Search className="pointer-events-none absolute left-3 size-4 text-ink-2" aria-hidden />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search documents…"
                className="h-10 w-full rounded-xl border border-line bg-surface pr-3 pl-9 text-sm text-ink outline-none placeholder:text-muted focus:border-accent"
              />
            </label>
            <Select<TypeFilter>
              label="Document type"
              value={type}
              onChange={setType}
              options={[
                { value: 'all', label: 'All types' },
                { value: 'work_order', label: 'Work orders' },
                { value: 'bad_actor_report', label: 'Reports' },
              ]}
              className="w-40"
            />
          </div>

          {docs.error ? (
            <ErrorNote message={docs.error} />
          ) : !docs.data ? (
            <Skeleton className="h-64" />
          ) : list.length === 0 ? (
            <EmptyState icon={FileText} title="No documents yet">
              Ask the agent to draft a work order, or export the bad-actor report.
            </EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[440px] text-sm">
                <thead>
                  <tr className="bg-surface-2">
                    <th className={`${TH} rounded-l-lg`}>Document</th>
                    <th className={TH}>Asset</th>
                    <th className={TH}>Created</th>
                    <th className={`${TH} rounded-r-lg text-right`}>
                      <span className="sr-only">Download</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((d) => (
                    <tr
                      key={d.id}
                      onClick={() => select(d.id)}
                      className={`cursor-pointer border-b border-line last:border-0 ${
                        d.id === selectedId ? 'bg-accent-soft/60' : 'hover:bg-surface-2/60'
                      }`}
                    >
                      <td className={TD}>
                        <div className="flex items-center gap-3">
                          <FileIcon kind={d.kind} />
                          <div className="min-w-0">
                            <div className="truncate font-semibold text-ink">{d.file_name}</div>
                            <div className="text-xs text-muted">Created by {d.created_by}</div>
                          </div>
                        </div>
                      </td>
                      <td className={`${TD} whitespace-nowrap text-ink`}>{d.tag ?? 'All assets'}</td>
                      <td className={`${TD} whitespace-nowrap text-ink-2`}>{formatWhen(d.created_at)}</td>
                      <td className={`${TD} text-right`}>
                        <DownloadButton doc={d} iconOnly />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Preview */}
        {selected ? (
          selected.work_order ? (
            <WorkOrderPreview key={selected.id} doc={selected} />
          ) : (
            <ReportPreview doc={selected} />
          )
        ) : (
          <Card>
            <EmptyState icon={FileText} title="Select a document to preview it" />
          </Card>
        )}
      </div>

      <NewWorkOrderModal
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(doc) => {
          setNewOpen(false)
          select(doc.id)
          toast({ title: `${doc.file_name} drafted`, tone: 'good' })
        }}
      />
    </>
  )
}

function FileIcon({ kind }: { kind: DocKind }) {
  const word = kind === 'work_order'
  return (
    <span
      className={`flex size-9 shrink-0 items-center justify-center rounded-lg text-white ${word ? 'bg-[#2b6cb0]' : 'bg-[#1e7a45]'}`}
      aria-label={word ? 'Word document' : 'Excel workbook'}
    >
      {word ? <FileText className="size-5" /> : <FileSpreadsheet className="size-5" />}
    </span>
  )
}

function DownloadButton({ doc, iconOnly = false }: { doc: DocumentItem; iconOnly?: boolean }) {
  const toast = useToast()
  const url = api.downloadUrl(doc)
  const ext = doc.file_name.split('.').pop()
  const onClick = (e: MouseEvent) => {
    e.stopPropagation()
    if (url) {
      const a = document.createElement('a')
      a.href = url
      a.download = doc.file_name
      a.click()
    } else {
      toast({ title: 'Demo mode', body: `The backend writes the real .${ext} file. Connect it to download ${doc.file_name}.` })
    }
  }
  return iconOnly ? (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg p-2 text-accent-ink hover:bg-accent-soft"
      aria-label={`Download ${doc.file_name}`}
    >
      <Download className="size-5" />
    </button>
  ) : (
    <Button icon={Download} onClick={onClick}>
      Download .{ext}
    </Button>
  )
}

const FIELDS: { key: keyof WorkOrderDraft; label: string }[] = [
  { key: 'problem', label: 'Problem' },
  { key: 'suspected_cause', label: 'Suspected cause' },
  { key: 'recommended_steps', label: 'Recommended steps' },
  { key: 'parts', label: 'Parts' },
  { key: 'safety', label: 'Safety' },
  { key: 'references', label: 'References' },
]

function WorkOrderPreview({ doc }: { doc: DocumentItem }) {
  const wo = doc.work_order!
  const { deny } = useRole()
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<WorkOrderDraft>(wo)
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState(false)

  const approve = async () => {
    setApproving(true)
    try {
      await api.approveWorkOrder(doc.id)
      toast({ title: `${wo.wo_number} approved`, body: 'Released for planning and scheduling.', tone: 'good' })
    } finally {
      setApproving(false)
    }
  }

  const save = async () => {
    setSaving(true)
    try {
      await api.saveWorkOrder(doc.id, draft)
      setEditing(false)
      toast({ title: 'Draft saved', tone: 'good' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="Work order preview"
      actions={
        wo.status === 'draft' ? (
          <Chip tone="warning">Draft · Pending approval</Chip>
        ) : (
          <Chip tone="good" icon={CheckCircle2}>
            Approved{wo.approved_by ? ` by ${wo.approved_by}` : ''}
          </Chip>
        )
      }
    >
      <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-2xl font-bold tracking-tight text-ink md:text-3xl">{wo.wo_number}</div>
            <div className="text-lg text-ink-2">
              {wo.tag} · {wo.asset_name}
            </div>
          </div>
          <Chip size="md" tone={criticalityTone(wo.priority)}>
            Priority: {wo.priority}
          </Chip>
        </div>

        <dl className="mt-4 grid gap-x-6 gap-y-3 border-t border-line pt-4 text-sm sm:grid-cols-[9rem_1fr]">
          {FIELDS.map((f) => (
            <div key={f.key} className="contents">
              <dt className="font-semibold text-ink">{f.label}:</dt>
              <dd className="text-ink">
                {editing ? (
                  <textarea
                    value={String(draft[f.key])}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                    rows={f.key === 'recommended_steps' ? 3 : 2}
                    className="w-full rounded-lg border border-line bg-surface-2/50 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
                  />
                ) : (
                  <span className="whitespace-pre-line">{String(wo[f.key] ?? '') || <span className="text-muted">—</span>}</span>
                )}
              </dd>
            </div>
          ))}
        </dl>

        <div className="mt-4 flex flex-wrap justify-between gap-2 border-t border-line pt-3 text-sm text-ink-2">
          <span>
            <span className="font-semibold text-ink">Requested by:</span> {wo.requested_by}
          </span>
          <span>
            <span className="font-semibold text-ink">Date:</span> {formatDate(wo.date)}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {editing ? (
            <>
              <Button variant="primary" icon={Save} onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save draft'}
              </Button>
              <Button icon={X} onClick={() => (setDraft(wo), setEditing(false))}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              {wo.status === 'draft' && (
                <>
                  <Button variant="primary" icon={Pencil} onClick={() => setEditing(true)} disabledReason={deny('edit_work_order') ?? (api.documentsEditable() ? null : 'Editing is not supported by the backend yet')}>
                    Edit draft
                  </Button>
                  <Button
                    variant="soft"
                    icon={CheckCircle2}
                    onClick={approve}
                    disabled={approving}
                    disabledReason={deny('approve_work_order') ?? (api.documentsEditable() ? null : 'Approving is not supported by the backend yet')}
                  >
                    {approving ? 'Approving…' : 'Approve'}
                  </Button>
                </>
              )}
              <DownloadButton doc={doc} />
            </>
          )}
        </div>
      </div>
    </Card>
  )
}

function ReportPreview({ doc }: { doc: DocumentItem }) {
  const rows = useApi(() => api.getBadActors({ window_days: 180 }, 6), [doc.id])
  const showCost = useRole().can('view_costs')
  return (
    <Card title="Report preview" subtitle={`${doc.file_name} · sheet "Bad actors"`} actions={<Chip tone="good">Generated</Chip>}>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[460px] text-sm">
          <thead>
            <tr className="bg-[#1e7a45] text-left text-xs text-white">
              {['Rank', 'Asset', 'Failure mode', 'Events', 'MTBF', 'Cost', 'Score'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(rows.data ?? []).map((r) => (
              <tr key={r.tag} className="border-b border-line last:border-0 odd:bg-surface-2/40">
                <td className="tabular px-3 py-1.5 text-ink-2">{r.rank}</td>
                <td className="px-3 py-1.5 font-medium text-ink">{r.tag}</td>
                <td className="px-3 py-1.5 text-ink-2">{r.failure_mode}</td>
                <td className="tabular px-3 py-1.5 text-ink">{r.events}</td>
                <td className="tabular px-3 py-1.5 text-ink">{r.mtbf_days} d</td>
                <td className="tabular px-3 py-1.5 text-ink">{showCost ? formatInr(r.cost_inr) : <Restricted />}</td>
                <td className="tabular px-3 py-1.5 font-semibold text-ink">{r.score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">Showing the first 6 rows. The workbook also has a "Failure modes" sheet.</p>
      <div className="mt-4">
        <DownloadButton doc={doc} />
      </div>
    </Card>
  )
}

function NewWorkOrderModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (doc: DocumentItem) => void
}) {
  const assets = useApi(() => api.getAssets(), [])
  const [tag, setTag] = useState('P-101')
  const [busy, setBusy] = useState(false)

  const create = async () => {
    setBusy(true)
    try {
      onCreated(await api.createWorkOrder(tag))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New work order">
      <p className="mb-3 text-sm text-ink-2">The draft is pre-filled from the asset's history, latest inspection and manuals. Writing it takes the local model a little while.</p>
      <Select
        label="Asset"
        value={tag}
        onChange={setTag}
        options={(assets.data ?? []).map((a) => ({ value: a.tag, label: `${a.tag} · ${a.name}` }))}
      />
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={Plus} onClick={create} disabled={busy}>
          {busy ? 'Drafting…' : 'Create draft'}
        </Button>
      </div>
    </Modal>
  )
}
