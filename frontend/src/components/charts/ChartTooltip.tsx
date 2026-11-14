import type { ReactNode } from 'react'

interface TooltipRow {
  name?: unknown
  value?: unknown
  color?: string
  dataKey?: unknown
}

interface ChartTooltipProps {
  active?: boolean
  payload?: readonly TooltipRow[]
  label?: unknown
  formatLabel?: (label: string) => ReactNode
  formatValue?: (value: number, row: TooltipRow) => ReactNode
}

/** Tooltip in the app's own tokens; values in ink, identity from a swatch. */
export function ChartTooltip({
  active,
  payload,
  label,
  formatLabel = (l) => l,
  formatValue = (v) => v,
}: ChartTooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="min-w-36 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      {label != null && <div className="mb-1.5 font-medium text-ink">{formatLabel(String(label))}</div>}
      <div className="flex flex-col gap-1">
        {payload.map((row, i) => (
          <div key={i} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-ink-2">
              {payload.length > 1 && (
                <span className="h-0.5 w-3 rounded-full" style={{ background: row.color }} />
              )}
              {String(row.name ?? '')}
            </span>
            <span className="tabular font-medium text-ink">
              {formatValue(Number(row.value), row)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
