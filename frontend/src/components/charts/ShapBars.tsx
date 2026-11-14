import type { ShapFactor } from '../../api/types'

/**
 * Diverging bars around a zero line: red pushes risk up, teal pulls it down.
 * Values are printed beside each bar so colour never carries meaning alone.
 */
export function ShapBars({ factors, max = 3 }: { factors: ShapFactor[]; max?: number }) {
  const top = [...factors].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, max)
  const scale = Math.max(...top.map((f) => Math.abs(f.value)), 0.01)

  return (
    <div>
      <div className="flex flex-col gap-2.5">
        {top.map((f) => {
          const pct = (Math.abs(f.value) / scale) * 50
          const up = f.value >= 0
          return (
            <div key={f.feature} className="grid grid-cols-[7.5rem_1fr_3rem] items-center gap-3 text-sm">
              <span className="truncate text-ink-2" title={f.feature}>
                {f.feature}
              </span>
              <div className="relative h-2.5 rounded-full bg-surface-2" role="img" aria-label={`${f.feature}: ${up ? 'raises' : 'lowers'} risk by ${Math.abs(f.value).toFixed(2)}`}>
                <div className="absolute inset-y-[-4px] left-1/2 w-px bg-axis" />
                <div
                  className={`absolute inset-y-0 ${up ? 'left-1/2 rounded-r-full bg-risk-up' : 'right-1/2 rounded-l-full bg-risk-down'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="tabular text-right font-medium text-ink">
                {up ? '+' : '−'}
                {Math.abs(f.value).toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>
      <div className="mt-3 flex gap-4 text-xs text-ink-2">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-risk-up" /> Raises risk
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-risk-down" /> Lowers risk
        </span>
      </div>
    </div>
  )
}
