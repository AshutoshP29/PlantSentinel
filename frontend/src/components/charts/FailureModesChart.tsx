import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { FailureModeCount } from '../../api/types'
import { ChartTooltip } from './ChartTooltip'
import { axisTick } from './chartStyle'

const ROW_HEIGHT = 30

/** Horizontal bars, one series: events per failure-mode cluster. */
export function FailureModesChart({ data, windowDays }: { data: FailureModeCount[]; windowDays: number }) {
  // Real clusters sorted by size; past 8 they fold into "Other"; the noise bucket always sits last.
  const real = data.filter((m) => !m.is_noise).sort((a, b) => b.events - a.events)
  const noise = data.filter((m) => m.is_noise)
  const MAX = 8
  const rows: FailureModeCount[] =
    real.length > MAX + 1
      ? [
          ...real.slice(0, MAX),
          { id: -1, name: `Other (${real.length - MAX} modes)`, events: real.slice(MAX).reduce((s, m) => s + m.events, 0), is_noise: true },
          ...noise,
        ]
      : [...real, ...noise]

  return (
    <div>
      <ResponsiveContainer width="100%" height={rows.length * ROW_HEIGHT + 8}>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 36, bottom: 0, left: 0 }}>
          <CartesianGrid horizontal={false} stroke="var(--grid)" />
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="name"
            width={212}
            tick={{ ...axisTick, fill: 'var(--ink-2)' }}
            tickLine={false}
            axisLine={{ stroke: 'var(--axis)' }}
          />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            content={(p) => <ChartTooltip {...p} formatValue={(v) => `${v} events`} />}
          />
          <Bar dataKey="events" name="Events" barSize={16} radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.id} fill={r.is_noise ? 'var(--muted)' : 'var(--series-1)'} />
            ))}
            <LabelList dataKey="events" position="right" offset={8} style={{ fill: 'var(--ink)', fontSize: 12, fontWeight: 500 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-1 text-center text-xs text-muted">Failure events (last {windowDays} days)</div>
    </div>
  )
}
