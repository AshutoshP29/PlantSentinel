import type { TimelineEvent, TimelineKind } from '../../api/types'
import { formatDate } from '../../lib/format'

const STYLE: Record<TimelineKind, { dot: string; chip: string }> = {
  failure: { dot: 'bg-critical', chip: 'bg-critical-soft text-critical-ink' },
  inspection: { dot: 'bg-accent', chip: 'bg-accent-soft text-accent-ink' },
  maintenance: { dot: 'bg-muted', chip: 'bg-surface-2 text-ink-2' },
}

/** Evenly spaced event timeline: date above, labelled chip below, dot colour by kind. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="overflow-x-auto pb-1">
      <ol className="relative flex min-w-max gap-0 md:min-w-0">
        <div className="absolute top-[34px] right-10 left-10 h-px bg-axis" aria-hidden />
        {events.map((e, i) => {
          const s = STYLE[e.kind]
          return (
            <li key={i} className="relative flex min-w-24 flex-1 flex-col items-center gap-2 px-1 text-center">
              <span className="tabular text-xs text-ink-2">{formatDate(e.date)}</span>
              <span className={`relative z-10 size-3.5 rounded-full ring-4 ring-surface ${s.dot}`} aria-hidden />
              <span className={`rounded-lg px-2 py-1 text-xs leading-tight font-medium ${s.chip}`}>{e.label}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
