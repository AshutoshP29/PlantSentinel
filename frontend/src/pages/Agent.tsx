import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  FilePlus2,
  FileText,
  Layers,
  Loader2,
  RefreshCw,
  SendHorizontal,
  ShieldAlert,
  Sparkles,
  Square,
  TrendingUp,
  UserRound,
  Wrench,
  XCircle,
} from 'lucide-react'
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AgentEvent, AgentStatus, AgentStep, ChatTurn, Citation, DocumentItem } from '../api/types'
import { CitationPaper } from '../components/SourceDocs'
import { Button, Card, Chip, EmptyState, Modal, PageHeader } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { formatTime } from '../lib/format'
import { useRole } from '../lib/role'
import { useToast } from '../lib/toast'

interface Message {
  id: number
  role: 'user' | 'assistant'
  text: string
  at: string
  pending?: boolean
  citations?: Citation[]
  canDraft?: boolean
  error?: string
  elapsed?: number
  tag?: string | null
  doc?: DocumentItem
}

const SUGGESTIONS = [
  { label: 'Why does P-101 keep failing?', q: 'Why does P-101 keep failing and what should we do?', icon: Wrench },
  { label: 'Assets at risk next', q: 'Which assets are at risk next?', icon: TrendingUp },
  { label: 'Summarise C-203', q: 'Summarise C-203', icon: Layers },
]

const TAG_RE = /\b([PCEM])-?(\d{3})\b/i
const KIND_LABEL: Record<Citation['kind'], string> = { manual: 'Manual', inspection: 'Inspection', work_orders: 'Work order' }

let msgId = 1

export default function Agent() {
  const [params, setParams] = useSearchParams()
  const assets = useApi(() => api.getAssets(), [])
  const [statusKey, setStatusKey] = useState(0)
  const status = useApi(() => api.getAgentStatus(), [statusKey])
  const [messages, setMessages] = useState<Message[]>([])
  const [steps, setSteps] = useState<AgentStep[]>([])
  const [running, setRunning] = useState(false)
  const [input, setInput] = useState('')
  const [contextTag, setContextTag] = useState<string | null>(params.get('tag'))
  const [selected, setSelected] = useState<{ c: Citation; tag: string | null } | null>(null)
  const [sourceOpen, setSourceOpen] = useState(false)
  const cancelRef = useRef<(() => void) | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const patchMsg = (id: number, fn: (m: Message) => Message) => setMessages((list) => list.map((x) => (x.id === id ? fn(x) : x)))

  const ask = (question: string) => {
    const q = question.trim()
    if (!q || running) return
    const m = q.match(TAG_RE)
    const tag = m ? `${m[1].toUpperCase()}-${m[2]}` : contextTag
    if (tag) setContextTag(tag)

    // Earlier finished turns go along as history (the backend keeps the last 20)
    const history: ChatTurn[] = messages.filter((x) => !x.pending && x.text).map((x) => ({ role: x.role, content: x.text }))

    const now = new Date().toISOString()
    // Ids are taken here, not inside the updater (StrictMode runs updaters twice).
    const userId = msgId++
    const answerId = msgId++
    setMessages((list) => [
      ...list,
      { id: userId, role: 'user', text: q, at: now },
      { id: answerId, role: 'assistant', text: '', at: now, pending: true, tag },
    ])
    setSteps([])
    setSelected(null)
    setInput('')
    setRunning(true)

    const t0 = performance.now()
    let generated = false // the agent ran generate_work_order itself

    cancelRef.current = api.askAgent(q, tag, history, (e: AgentEvent) => {
      switch (e.type) {
        case 'step':
          if (e.step.tool === 'generate_work_order' && e.step.status === 'done') generated = true
          setSteps((list) => {
            const i = list.findIndex((s) => s.id === e.step.id)
            return i === -1 ? [...list, e.step] : list.map((s, j) => (j === i ? { ...s, ...e.step } : s))
          })
          break
        case 'token':
          patchMsg(answerId, (x) => ({ ...x, text: x.text + e.text }))
          break
        case 'blocked':
          break // the client raises the red alert
        case 'error':
          patchMsg(answerId, (x) => ({ ...x, error: e.message }))
          break
        case 'done': {
          const elapsed = (performance.now() - t0) / 1000
          patchMsg(answerId, (x) => ({ ...x, pending: false, citations: e.citations, canDraft: e.can_draft_work_order, elapsed, at: new Date().toISOString() }))
          if (e.citations[0]) setSelected({ c: e.citations[0], tag })
          setRunning(false)
          // If the agent drafted a work order, show its download (it's saved in Documents)
          if (generated && tag) {
            void api
              .getDocuments()
              .then((docs) => docs.find((d) => d.kind === 'work_order' && d.tag === tag))
              .then((doc) => doc && patchMsg(answerId, (x) => ({ ...x, doc })))
              .catch(() => {})
          }
          break
        }
      }
    })
  }

  const stop = () => {
    cancelRef.current?.()
    setMessages((list) => list.map((x) => (x.pending ? { ...x, pending: false, error: x.text ? undefined : 'Stopped.' } : x)))
    setSteps((list) => list.map((s) => (s.status === 'running' ? { ...s, status: 'error', summary: 'Stopped' } : s)))
    setRunning(false)
  }

  // Auto-ask when arriving from "Ask why it keeps failing" (deferred so StrictMode runs it once)
  useEffect(() => {
    const q = params.get('q')
    if (!q) return
    const t = window.setTimeout(() => {
      ask(q)
      setParams({}, { replace: true })
    }, 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => cancelRef.current?.(), [])
  // Braces matter: newer browsers return a Promise from scrollIntoView, and React
  // would treat a returned value as the effect's cleanup function.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [messages])

  const contextAsset = assets.data?.find((a) => a.tag === contextTag)

  return (
    <>
      <PageHeader
        title="Ask the agent"
        description="Root-cause answers with citations from your own history, inspections and manuals."
        actions={<ReadyChip status={status.data} loading={status.loading} onRefresh={() => setStatusKey((k) => k + 1)} />}
      />
      {status.data && !status.data.ready && <ReadinessBanner status={status.data} onRefresh={() => setStatusKey((k) => k + 1)} />}
      {status.error && (
        <div className="mb-4 rounded-2xl border border-warning/50 bg-warning-soft px-5 py-3 text-sm text-warning-ink">
          Couldn't reach the agent status endpoint: {status.error}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        {/* Conversation */}
        <Card bodyClassName="flex h-[min(72vh,760px)] min-h-[520px] flex-col p-0">
          <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
            {contextAsset ? (
              <Chip size="md" tone="accent" icon={Wrench}>
                {contextAsset.tag} · {contextAsset.name}
              </Chip>
            ) : (
              <span className="text-sm text-muted">No asset selected: mention a tag like P-101</span>
            )}
            {messages.length > 0 && !running && (
              <Button size="sm" variant="ghost" onClick={() => (setMessages([]), setSteps([]), setSelected(null))}>
                New chat
              </Button>
            )}
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
            {messages.length === 0 && (
              <EmptyState icon={Sparkles} title="Ask about an asset or a failure">
                The agent reads your work orders, inspection reports and manuals, and cites every source.
              </EmptyState>
            )}
            {messages.map((m) =>
              m.role === 'user' ? (
                <UserBubble key={m.id} m={m} />
              ) : (
                <AnswerCard
                  key={m.id}
                  m={m}
                  activeId={selected?.c.id ?? null}
                  onCite={(c) => setSelected({ c, tag: m.tag ?? null })}
                  onDoc={(doc) => patchMsg(m.id, (x) => ({ ...x, doc, canDraft: false }))}
                />
              ),
            )}
            <div ref={endRef} />
          </div>

          <div className="border-t border-line px-5 py-4">
            <div className="mb-3 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.label}
                  type="button"
                  onClick={() => ask(s.q)}
                  disabled={running}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-50"
                >
                  <s.icon className="size-4" aria-hidden />
                  {s.label}
                </button>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                ask(input)
              }}
              className="flex items-center gap-2 rounded-2xl border border-line bg-surface p-1.5 pl-4 focus-within:border-accent"
            >
              <label htmlFor="agent-q" className="sr-only">
                Question
              </label>
              <input
                id="agent-q"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about an asset or failure…"
                maxLength={2000}
                className="h-10 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-muted"
                autoComplete="off"
              />
              {running ? (
                <Button variant="secondary" icon={Square} onClick={stop} aria-label="Stop">
                  Stop
                </Button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="flex size-10 items-center justify-center rounded-xl bg-accent text-white hover:bg-accent-hover disabled:opacity-40"
                  aria-label="Send"
                >
                  <SendHorizontal className="size-5" />
                </button>
              )}
            </form>
          </div>
        </Card>

        {/* Right column */}
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Agent activity" subtitle="Each tool call, as it runs">
            {steps.length === 0 ? (
              <p className="py-4 text-sm text-muted">Steps appear here while the agent works.</p>
            ) : (
              <ol className="flex flex-col gap-2">
                {steps.map((s) => (
                  <StepRow key={s.id} step={s} />
                ))}
              </ol>
            )}
          </Card>

          <Card
            icon={FileText}
            title={selected ? `[${selected.c.id}] ${KIND_LABEL[selected.c.kind]}` : 'Source preview'}
            subtitle={selected ? selected.c.title : 'Click a citation to see where an answer came from'}
          >
            {selected ? (
              <div className="space-y-3">
                <CitationPaper citation={selected.c} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="soft" icon={ExternalLink} onClick={() => setSourceOpen(true)}>
                    Open source
                  </Button>
                  {selected.c.kind !== 'manual' && selected.tag && (
                    <Link to={`/assets/${selected.tag}`} className="inline-flex h-8 items-center rounded-lg px-3 text-xs font-medium text-accent-ink hover:bg-accent-soft">
                      Open {selected.tag}
                    </Link>
                  )}
                </div>
              </div>
            ) : (
              <p className="py-4 text-sm text-muted">No source selected.</p>
            )}
          </Card>
        </div>
      </div>

      {selected && (
        <Modal open={sourceOpen} onClose={() => setSourceOpen(false)} title={`[${selected.c.id}] ${selected.c.title}`}>
          <CitationPaper citation={selected.c} />
        </Modal>
      )}
    </>
  )
}

// ---------- readiness ----------

function problems(s: AgentStatus): string[] {
  const out: string[] = []
  if (!s.ollama.reachable) out.push(`Ollama isn't reachable at ${s.ollama.host}${s.ollama.error ? ` (${s.ollama.error})` : ''}.`)
  if (s.ollama.missing_models.length) out.push(`Missing models: ${s.ollama.missing_models.join(', ')}. Pull them before the demo.`)
  if (s.manual_chunks === 0) out.push('No manual passages are indexed, so answers will have no manual citations. Run the demo seeding.')
  if (s.manual_store_error) out.push(`Manual store: ${s.manual_store_error}`)
  return out.length ? out : ['The agent reports it is not ready.']
}

function ReadyChip({ status, loading, onRefresh }: { status: AgentStatus | null; loading: boolean; onRefresh: () => void }) {
  return (
    <div className="flex items-center gap-2">
      {status &&
        (status.ready ? (
          <Chip tone="good" icon={CheckCircle2} title={`Ollama at ${status.ollama.host}`}>
            Agent ready · {status.manual_chunks} manual passages
          </Chip>
        ) : (
          <Chip tone="warning" icon={AlertTriangle}>
            Agent not ready
          </Chip>
        ))}
      <Button size="sm" variant="ghost" icon={loading ? Loader2 : RefreshCw} onClick={onRefresh} disabled={loading} aria-label="Re-check agent status">
        Check
      </Button>
    </div>
  )
}

function ReadinessBanner({ status, onRefresh }: { status: AgentStatus; onRefresh: () => void }) {
  return (
    <div role="alert" className="mb-4 flex items-start gap-3 rounded-2xl border border-warning/50 bg-warning-soft px-5 py-4">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning-ink" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-warning-ink">The agent isn't ready for the demo</div>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-2">
          {problems(status).map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </div>
      <Button size="sm" icon={RefreshCw} onClick={onRefresh}>
        Re-check
      </Button>
    </div>
  )
}

// ---------- messages ----------

function UserBubble({ m }: { m: Message }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-start gap-2">
        <div className="max-w-[36rem] rounded-2xl rounded-tr-md bg-accent-soft px-4 py-2.5 text-[15px] text-ink">{m.text}</div>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-ink-2">
          <UserRound className="size-4" aria-hidden />
        </span>
      </div>
      <span className="mr-10 text-xs text-muted">{formatTime(m.at)}</span>
    </div>
  )
}

function AnswerCard({
  m,
  activeId,
  onCite,
  onDoc,
}: {
  m: Message
  activeId: number | null
  onCite: (c: Citation) => void
  onDoc: (doc: DocumentItem) => void
}) {
  const { deny } = useRole()
  const toast = useToast()
  const [drafting, setDrafting] = useState(false)
  const cites = m.citations ?? []
  const byId = new Map(cites.map((c) => [c.id, c]))

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.text.replace(/^#{2,3} /gm, ''))
      toast({ title: 'Answer copied' })
    } catch {
      toast({ title: 'Copy not available in this browser', tone: 'critical' })
    }
  }

  const draft = async () => {
    if (!m.tag) return
    setDrafting(true)
    try {
      const doc = await api.createWorkOrder(m.tag)
      onDoc(doc)
      toast({ title: `${doc.work_order?.wo_number ?? doc.file_name} drafted`, body: 'Saved in Documents.', tone: 'good' })
    } catch (err) {
      toast({ title: 'Could not draft the work order', body: err instanceof Error ? err.message : String(err), tone: 'critical' })
    } finally {
      setDrafting(false)
    }
  }

  const renderRef = (n: number) => {
    const c = byId.get(n)
    return (
      <button
        type="button"
        disabled={!c}
        title={c ? c.title : m.pending ? 'Sources load when the answer finishes' : 'Not in the cited sources'}
        onClick={() => c && onCite(c)}
        className={`mx-0.5 rounded px-1 align-[1px] text-xs font-semibold ${
          !c ? 'bg-surface-2 text-muted' : activeId === n ? 'bg-accent text-white' : 'bg-accent-soft text-accent-ink'
        }`}
      >
        [{n}]
      </button>
    )
  }

  return (
    <div className="flex items-start gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-ink">
        <Bot className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-line bg-surface px-5 py-4 shadow-sm">
        {m.text ? (
          <RichText text={m.text} streaming={m.pending} renderRef={renderRef} />
        ) : m.pending ? (
          <div className="flex items-center gap-2 text-sm text-ink-2">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Working through the tools…
          </div>
        ) : null}
        {m.error && <p className="mt-2 text-sm text-critical-ink">{m.error}</p>}

        {cites.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {cites.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onCite(c)}
                title={c.title}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-left text-xs font-medium ${
                  activeId === c.id ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line bg-surface text-ink-2 hover:bg-surface-2'
                }`}
              >
                <FileText className="size-3.5 shrink-0" aria-hidden />[{c.id}] {c.label}
              </button>
            ))}
          </div>
        )}

        {m.doc && <DocumentRow doc={m.doc} />}

        {!m.pending && m.text && (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {m.canDraft && m.tag && !m.doc && (
              <Button variant="primary" icon={drafting ? Loader2 : FilePlus2} onClick={draft} disabled={drafting} disabledReason={deny('draft_work_order')}>
                {drafting ? 'Drafting…' : 'Draft work order'}
              </Button>
            )}
            <Button icon={Copy} onClick={copy}>
              Copy
            </Button>
            <span className="ml-auto text-xs text-muted">
              {m.elapsed != null ? `Answered in ${m.elapsed.toFixed(1)} s · ` : ''}
              {formatTime(m.at)}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

function DocumentRow({ doc }: { doc: DocumentItem }) {
  const toast = useToast()
  const url = api.downloadUrl(doc)
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-accent/30 bg-accent-soft/50 px-3 py-2.5">
      <span className="flex size-9 items-center justify-center rounded-lg bg-[#2b6cb0] text-white" aria-hidden>
        <FileText className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ink">{doc.file_name}</div>
        <div className="text-xs text-ink-2">
          {doc.work_order?.wo_number ?? doc.id} · {doc.tag ?? 'All assets'}
          {doc.work_order?.priority ? ` · Priority ${doc.work_order.priority}` : ''}
        </div>
      </div>
      {url ? (
        <a href={url} download={doc.file_name} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-medium text-white hover:bg-accent-hover">
          <Download className="size-3.5" aria-hidden /> Download .docx
        </a>
      ) : (
        <Button size="sm" icon={Download} onClick={() => toast({ title: 'Demo mode', body: 'The backend writes the real .docx. Connect it to download.' })}>
          Download .docx
        </Button>
      )}
      <Link to={`/documents?doc=${encodeURIComponent(doc.id)}`} className="text-xs font-medium text-accent-ink hover:underline">
        Open in Documents
      </Link>
    </div>
  )
}

/** Markdown-lite: ## / ### headings, numbered and bulleted lists, **bold**, [n] citation refs. */
function RichText({ text, streaming, renderRef }: { text: string; streaming?: boolean; renderRef: (n: number) => ReactNode }) {
  const lines = text.split('\n').filter((l) => l.trim() !== '')
  const inline = (s: string) =>
    s.split(/(\[\d+\]|\*\*[^*]+\*\*)/).map((part, i) => {
      const ref = part.match(/^\[(\d+)\]$/)
      if (ref) return <Fragment key={i}>{renderRef(Number(ref[1]))}</Fragment>
      if (/^\*\*.+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>
      return <Fragment key={i}>{part}</Fragment>
    })

  return (
    <div className={`space-y-2 text-[15px] leading-relaxed text-ink ${streaming ? 'stream-caret' : ''}`}>
      {lines.map((l, i) => {
        const h = l.match(/^(#{2,3})\s+(.*)$/)
        if (h)
          return (
            <h3 key={i} className={`font-bold text-ink ${h[1].length === 2 ? 'text-lg' : 'text-base'} ${i > 0 ? 'pt-2' : ''}`}>
              {inline(h[2])}
            </h3>
          )
        if (/^\s*(\d+\.|[-*•])\s/.test(l)) return <p key={i} className="pl-5 -indent-4">{inline(l.trim())}</p>
        return <p key={i}>{inline(l)}</p>
      })}
    </div>
  )
}

function StepRow({ step }: { step: AgentStep }) {
  const icon =
    step.status === 'running' ? (
      <Loader2 className="size-5 animate-spin text-accent-ink" aria-label="Running" />
    ) : step.status === 'done' ? (
      <CheckCircle2 className="size-5 text-accent-ink" aria-label="Done" />
    ) : step.status === 'blocked' ? (
      <ShieldAlert className="size-5 text-critical" aria-label="Blocked" />
    ) : (
      <XCircle className="size-5 text-muted" aria-label="Failed" />
    )

  return (
    <li
      title={step.summary}
      className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 ${
        step.status === 'blocked' ? 'border-critical/40 bg-critical-soft' : 'border-line bg-surface-2/50'
      }`}
    >
      {icon}
      <div className="min-w-0 flex-1">
        <div className="font-mono text-sm font-semibold text-ink">{step.tool}</div>
        <div className={`truncate text-xs ${step.status === 'blocked' ? 'text-critical-ink' : 'text-ink-2'}`}>{step.summary}</div>
      </div>
      {step.duration_ms !== undefined && (
        <span className="tabular rounded-md bg-surface px-2 py-0.5 text-xs text-ink-2">{(step.duration_ms / 1000).toFixed(1)} s</span>
      )}
    </li>
  )
}
