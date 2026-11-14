export interface Gap {
  date: string // failure date
  days: number // days since the previous failure of the same mode
  recent: boolean // inside the last 180 days
}

const DAY = 86_400_000
const t = (d: string) => new Date(`${d.slice(0, 10)}T00:00:00Z`).getTime()

/** Days between consecutive work orders of `mode`, oldest first (display only; no scoring). */
export function gapsFor(workOrders: { date: string; failure_mode: string | null }[], mode: string, asOf: string): Gap[] {
  const dates = workOrders
    .filter((w) => w.failure_mode === mode)
    .map((w) => w.date)
    .sort()
  const cutoff = t(asOf) - 180 * DAY
  return dates.slice(1).map((d, i) => ({
    date: d,
    days: Math.round((t(d) - t(dates[i])) / DAY),
    recent: t(d) > cutoff,
  }))
}
