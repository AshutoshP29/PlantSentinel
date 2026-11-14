import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { FailureModeCount } from '../../api/types'
import { ChartTooltip } from './ChartTooltip'
import { axisTick } from './chartStyle'

const ROW_HEIGHT = 30

/** Horizontal bars, one series: events per failure-mode cluster. */
export function FailureModesChart({ data, windowDays }: { data: FailureModeCount[]; windowDays: number }) {
  // Real clusters sorted by size; the noise bucket always sits last.
  const rows = [...data].sort((a, b) =>
    a.is_noise === b.is_noise ? b.events - a.events : a.is_noise ? 1 : -1,
  )

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
