import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { MtbfPoint } from '../../api/types'
import { formatMonth } from '../../lib/format'
import { ChartTooltip } from './ChartTooltip'
import { axisTick } from './chartStyle'

/** One series of monthly MTBF (days): 2px line, 12% wash, value labelled at the end. */
export function TrendChart({ data, height = 260, name = 'MTBF' }: { data: MtbfPoint[]; height?: number; name?: string }) {
  const last = data.length - 1
  const ticks = cleanTicks(Math.max(0, ...data.map((p) => p.mtbf_days)))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 44, bottom: 0, left: -6 }}>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis
          dataKey="month"
          tickFormatter={formatMonth}
          tick={axisTick}
          tickLine={false}
          axisLine={{ stroke: 'var(--axis)' }}
          interval="preserveStartEnd"
          minTickGap={28}
        />
        <YAxis
          tick={axisTick}
          tickLine={false}
          axisLine={false}
          domain={[0, ticks[ticks.length - 1]]}
          ticks={ticks}
          unit=" d"
          width={52}
        />
        <Tooltip
          cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
          content={(p) => <ChartTooltip {...p} formatLabel={formatMonth} formatValue={(v) => `${v} days`} />}
        />
        <Area
          type="monotone"
          dataKey="mtbf_days"
          name={name}
          stroke="var(--series-1)"
          strokeWidth={2}
          fill="var(--series-1-wash)"
          fillOpacity={1}
          isAnimationActive={false}
          activeDot={{ r: 5, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
          dot={(p: { cx?: number; cy?: number; index?: number }) =>
            p.index === last ? (
              <circle key="end" cx={p.cx} cy={p.cy} r={4} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
            ) : (
              <g key={p.index} />
            )
          }
          label={(p: { x?: number | string; y?: number | string; index?: number; value?: unknown }) =>
            p.index === last ? (
              <text key="end-label" x={Number(p.x) + 9} y={Number(p.y)} dy={4} fontSize={12} fontWeight={600} fill="var(--ink)">
                {`${p.value} d`}
              </text>
            ) : (
              <g key={`l${p.index}`} />
            )
          }
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** 0-based ticks on a clean step (10, 20, 25, 50, 100 …) with 4–6 intervals. */
function cleanTicks(max: number): number[] {
  if (max <= 0) return [0, 1]
  const raw = max / 5
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow
  const top = Math.ceil(max / step) * step
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
}
