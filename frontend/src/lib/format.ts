const nf = new Intl.NumberFormat('en-IN')

export function formatNumber(n: number): string {
  return nf.format(n)
}

/** ₹ amounts in Indian units: ₹12K, ₹6.8 L, ₹1.2 Cr */
export function formatInr(n: number): string {
  if (n >= 1e7) return `₹${trim(n / 1e7)} Cr`
  if (n >= 1e5) return `₹${trim(n / 1e5)} L`
  if (n >= 1e3) return `₹${trim(n / 1e3)}K`
  return `₹${n}`
}

/** Signed percentage with a real minus sign: +7%, −60% */
export function formatPct(n: number): string {
  if (n === 0) return '0%'
  return `${n > 0 ? '+' : '−'}${Math.abs(n)}%`
}

/** '2026-05' → 'May 26' */
export function formatMonth(ym: string): string {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1, 1))
  return `${d.toLocaleString('en-IN', { month: 'short', timeZone: 'UTC' })} ${String(y).slice(2)}`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** '2026-11-12' → '12 Nov 2026' */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d} ${MONTHS[Number(m) - 1]} ${y}`
}

/** ISO datetime → 'Today 14:32' / 'Yesterday' / '07 Nov' */
export function formatWhen(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000)
  if (days === 0) return `Today ${time}`
  if (days === 1) return 'Yesterday'
  return `${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]}`
}

/** ISO datetime → '14:36' */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function trim(n: number): string {
  return n.toFixed(1).replace(/\.0$/, '')
}
