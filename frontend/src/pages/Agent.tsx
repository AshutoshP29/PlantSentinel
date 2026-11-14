import {
  Bot,
  CheckCircle2,
  Copy,
  ExternalLink,
  FilePlus2,
  FileText,
  Layers,
  Loader2,
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
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { p101Inspection } from '../api/mock'
import type { AgentEvent, AgentStep, Citation } from '../api/types'
import { CitationSource, InspectionPaper } from '../components/SourceDocs'
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
  streaming?: boolean
  citations?: Citation[]
  canDraft?: boolean
  tag?: string | null
  error?: string
}

const SUGGESTIONS = [
  { label: 'Why does P-101 keep failing?', q: 'Why does P-101 keep failing and what should we do?', icon: Wrench },
  { label: 'Assets at risk next', q: 'Which assets are at risk next?', icon: TrendingUp },
  { label: 'Summarise C-203', q: 'Summarise C-203', icon: Layers },
]

const TAG_RE = /\b([PCEM])-?(\d{3})\b/i

let msgId = 1

export default function Agent() {
  const [params, setParams] = useSearchParams()
  const assets = useApi(() => api.getAssets(), [])
  const [messages, setMessages] = useState<Message[]>([])
  const [steps, setSteps] = useState<AgentStep[]>([])
  const [running, setRunning] = useState(false)
  const [input, setInput] = useState('')
  const [contextTag, setContextTag] = useState<string | null>(params.get('tag'))
  const [source, setSource] = useState<Citation | null>(null)
  const [sourceOpen, setSourceOpen] = useState(false)
  const cancelRef = useRef<(() => void) | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const ask = (question: string) => {
    const q = question.trim()
    if (!q || running) return
    const m = q.match(TAG_RE)
    const tag = m ? `${m[1].toUpperCase()}-${m[2]}` : contextTag
    if (tag) setContextTag(tag)

    const now = new Date().toISOString()
    // Ids are taken here, not inside the updater (StrictMode runs updaters twice).
    const userId = msgId++
    const answerId = msgId++
    setMessages((list) => [
      ...list,
      { id: userId, role: 'user', text: q, at: now },
      { id: answerId, role: 'assistant', text: '', at: now, streaming: true, tag },
    ])
    setSteps([])
    setSource(null)
    setInput('')
    setRunning(true)

    const patch = (fn: (m: Message) => Message) =>
      setMessages((list) => list.map((x) => (x.id === answerId ? fn(x) : x)))

    cancelRef.current = api.askAgent(q, tag, (e: AgentEvent) => {
      switch (e.type) {
        case 'step':
          setSteps((list) => {
            const i = list.findIndex((s) => s.id === e.step.id)
            return i === -1 ? [...list, e.step] : list.map((s, j) => (j === i ? e.step : s))
          })
          break
        case 'token':
          patch((x) => ({ ...x, text: x.text + e.text }))
          break
        case 'done':
          patch((x) => ({ ...x, streaming: false, citations: e.citations, canDraft: e.can_draft_work_order, at: new Date().toISOString() }))
          setSource(e.citations[0] ?? null)
          setRunning(false)
          break
        case 'error':
          patch((x) => ({ ...x, streaming: false, error: e.message }))
          setRunning(false)
          break
        case 'blocked':
          break
      }
    })
  }

  const stop = () => {
    cancelRef.current?.()
    setMessages((list) => list.map((x) => (x.streaming ? { ...x, streaming: false, text: x.text + ' …(stopped)' } : x)))
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
      <PageHeader title="Ask the agent" description="Root-cause answers with citations from your own history, manuals and inspections." />

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
              <Button size="sm" variant="ghost" onClick={() => (setMessages([]), setSteps([]), setSource(null))}>
                New chat
              </Button>
            )}
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
            {messages.length === 0 && (
              <EmptyState icon={Sparkles} title="Ask about an asset or a failure">
                The agent reads your work orders, inspections and manuals, and cites every source.
              </EmptyState>
            )}
            {messages.map((m) =>
              m.role === 'user' ? (
                <UserBubble key={m.id} m={m} />
              ) : (
                <AnswerCard key={m.id} m={m} onCite={(c) => setSource(c)} activeCite={source?.id ?? null} />
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
            title={source ? source.title : 'Source preview'}
            subtitle={source ? undefined : 'Click a citation to see where an answer came from'}
          >
            {source ? (
              <div className="space-y-3">
                <CitationSource citation={source} inspection={p101Inspection} />
                <blockquote className="rounded-lg bg-highlight px-3 py-2 text-sm text-ink italic">“{source.quote}”</blockquote>
                <Button size="sm" variant="soft" icon={ExternalLink} onClick={() => setSourceOpen(true)}>
                  Open source
                </Button>
              </div>
            ) : (
              <p className="py-4 text-sm text-muted">No source selected.</p>
            )}
          </Card>
        </div>
      </div>

      {source && (
        <Modal open={sourceOpen} onClose={() => setSourceOpen(false)} title={source.title}>
          {source.kind === 'inspection' ? <InspectionPaper inspection={p101Inspection} /> : <CitationSource citation={source} />}
        </Modal>
      )}
    </>
  )
}

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

function AnswerCard({ m, onCite, activeCite }: { m: Message; onCite: (c: Citation) => void; activeCite: number | null }) {
  const { deny } = useRole()
  const toast = useToast()
  const navigate = useNavigate()
  const [drafting, setDrafting] = useState(false)
  const cites = m.citations ?? []
  const findCite = (n: number) => cites.find((c) => c.id === n)

  const draft = async () => {
    if (!m.tag) return
    setDrafting(true)
    try {
      const doc = await api.createWorkOrder(m.tag)
      toast({ title: `${doc.file_name} drafted`, body: 'Saved to Documents for review.', tone: 'good' })
      navigate(`/documents?doc=${doc.id}`)
    } finally {
      setDrafting(false)
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.text.replace(/^## /gm, ''))
      toast({ title: 'Answer copied' })
    } catch {
      toast({ title: 'Copy not available in this browser', tone: 'critical' })
    }
  }

  return (
    <div className="flex items-start gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-ink">
        <Bot className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-line bg-surface px-5 py-4 shadow-sm">
        {m.text === '' && m.streaming ? (
          <div className="flex items-center gap-2 text-sm text-ink-2">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Working through the tools…
          </div>
        ) : (
          <RichText text={m.text} streaming={m.streaming} renderCite={(n) => {
            const c = findCite(n)
            return (
              <button
                type="button"
                disabled={!c}
                onClick={() => c && onCite(c)}
                className={`mx-0.5 rounded px-1 text-xs font-semibold align-[1px] ${
                  c && activeCite === n ? 'bg-accent text-white' : 'bg-accent-soft text-accent-ink'
                }`}
              >
                [{n}]
              </button>
            )
          }} />
        )}
        {m.error && <p className="mt-2 text-sm text-critical-ink">{m.error}</p>}

        {!m.streaming && cites.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {cites.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onCite(c)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${
                  activeCite === c.id ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line bg-surface text-ink-2 hover:bg-surface-2'
                }`}
              >
                <FileText className="size-3.5" aria-hidden />[{c.id}] {c.label}
              </button>
            ))}
          </div>
        )}

        {!m.streaming && m.text && (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {m.canDraft && (
              <Button
                variant="primary"
                icon={FilePlus2}
                onClick={draft}
                disabled={drafting}
                disabledReason={deny('draft_work_order')}
              >
                {drafting ? 'Drafting…' : 'Draft work order'}
              </Button>
            )}
            <Button icon={Copy} onClick={copy}>
              Copy
            </Button>
            <span className="ml-auto text-xs text-muted">{formatTime(m.at)}</span>
          </div>
        )}
      </div>
    </div>
  )
}

/** Markdown-lite: "## " headings, "1. " list items, [n] citation refs. */
function RichText({ text, streaming, renderCite }: { text: string; streaming?: boolean; renderCite: (n: number) => ReactNode }) {
  const lines = text.split('\n').filter((l, i, arr) => l.trim() !== '' || i === arr.length - 1)
  const inline = (s: string) =>
    s.split(/(\[\d+\])/).map((part, i) => {
      const m = part.match(/^\[(\d+)\]$/)
      return m ? <Fragment key={i}>{renderCite(Number(m[1]))}</Fragment> : <Fragment key={i}>{part}</Fragment>
    })

  return (
    <div className={`space-y-2 text-[15px] leading-relaxed text-ink ${streaming ? 'stream-caret' : ''}`}>
      {lines.map((l, i) =>
        l.startsWith('## ') ? (
          <h3 key={i} className={`text-lg font-bold text-ink ${i > 0 ? 'pt-2' : ''}`}>
            {l.slice(3)}
          </h3>
        ) : /^\d+\.\s/.test(l) ? (
          <p key={i} className="pl-4 -indent-4">
            {inline(l)}
          </p>
        ) : (
          <p key={i}>{inline(l)}</p>
        ),
      )}
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
      <XCircle className="size-5 text-muted" aria-label="Stopped" />
    )

  return (
    <li
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
