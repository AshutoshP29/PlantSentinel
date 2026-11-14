import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDate } from '../../lib/format'
import type { Gap } from '../../lib/gaps'
import { ChartTooltip } from './ChartTooltip'
import { axisTick } from './chartStyle'

/**
 * Days between consecutive failures of one failure mode. One bar per failure, so a
 * collapse in MTBF (e.g. 150 → 50 days) is obvious at a glance.
 */
export function GapChart({ gaps, height = 240 }: { gaps: Gap[]; height?: number }) {
  return (
    <div>
      <div className="mb-2 flex gap-4 text-xs text-ink-2">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-series-1" /> Earlier
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-critical" /> Last 180 days
        </span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={gaps} margin={{ top: 18, right: 8, bottom: 0, left: -6 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="date"
            tickFormatter={(d: string) => formatDate(d).slice(3)}
            tick={axisTick}
            tickLine={false}
            axisLine={{ stroke: 'var(--axis)' }}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis tick={axisTick} tickLine={false} axisLine={false} unit=" d" width={52} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            content={(p) => (
              <ChartTooltip {...p} formatLabel={(d) => `Failure on ${formatDate(d)}`} formatValue={(v) => `${v} days since previous`} />
            )}
          />
          <Bar dataKey="days" name="Gap" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {gaps.map((g) => (
              <Cell key={g.date} fill={g.recent ? 'var(--critical)' : 'var(--series-1)'} />
            ))}
            <LabelList dataKey="days" position="top" offset={6} style={{ fill: 'var(--ink)', fontSize: 11, fontWeight: 500 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
