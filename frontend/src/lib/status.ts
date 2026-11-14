import type { BadActorStatus, Criticality } from '../api/types'

export type Tone = 'neutral' | 'accent' | 'critical' | 'warning' | 'good'

export function criticalityTone(c: Criticality): Tone {
  return c === 'High' ? 'critical' : c === 'Medium' ? 'warning' : 'neutral'
}

export const STATUS_INFO: Record<BadActorStatus, { label: string; tone: Tone; title: string }> = {
  recurring: { label: 'Recurring', tone: 'critical', title: '3 or more events of the same failure mode in 180 days' },
  review: { label: 'Review', tone: 'warning', title: 'MTBF fell more than 40% vs the previous period' },
  watch: { label: 'Watch', tone: 'neutral', title: 'Not flagged; keep an eye on the trend' },
}

/** Header cell + body cell styles shared by the screens' main tables. */
export const TH = 'px-3 py-2.5 text-left text-xs font-medium text-ink-2 first:pl-4 last:pr-4'
export const TD = 'px-3 py-3 first:pl-4 last:pr-4'
