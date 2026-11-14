import { ChevronDown, Lock, X, type LucideIcon } from 'lucide-react'
import { useEffect, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Tone } from '../lib/status'

// ---------- buttons ----------

type Variant = 'primary' | 'secondary' | 'soft' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover shadow-sm',
  secondary: 'border border-line bg-surface text-ink hover:bg-surface-2',
  soft: 'border border-accent/25 bg-accent-soft text-accent-ink hover:brightness-[0.97]',
  ghost: 'text-ink-2 hover:bg-surface-2 hover:text-ink',
  danger: 'border border-critical/30 bg-surface text-critical-ink hover:bg-critical-soft',
}
const SIZE: Record<Size, string> = {
  sm: 'h-8 gap-1.5 rounded-lg px-3 text-xs',
  md: 'h-10 gap-2 rounded-xl px-4 text-sm',
}

function buttonClass(variant: Variant, size: Size, extra = '') {
  return `inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition disabled:cursor-not-allowed disabled:opacity-45 ${VARIANT[variant]} ${SIZE[size]} ${extra}`
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: LucideIcon
  /** When set, the button is disabled and this explains why (tooltip). */
  disabledReason?: string | null
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  disabledReason,
  className = '',
  children,
  disabled,
  title,
  ...rest
}: ButtonProps) {
  const blocked = Boolean(disabledReason)
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || blocked}
      title={blocked ? disabledReason! : title}
      className={buttonClass(variant, size, className)}
    >
      {Icon && <Icon className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden />}
      {children}
    </button>
  )
}

export function LinkButton({
  to,
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  children,
  className = '',
}: {
  to: string
  variant?: Variant
  size?: Size
  icon?: LucideIcon
  children: ReactNode
  className?: string
}) {
  return (
    <Link to={to} className={buttonClass(variant, size, className)}>
      {Icon && <Icon className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden />}
      {children}
    </Link>
  )
}

// ---------- chips ----------

const TONE: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-ink-2',
  accent: 'bg-accent-soft text-accent-ink',
  critical: 'bg-critical-soft text-critical-ink',
  warning: 'bg-warning-soft text-warning-ink',
  good: 'bg-good-soft text-good-ink',
}

export function Chip({
  tone = 'neutral',
  icon: Icon,
  children,
  size = 'sm',
  title,
}: {
  tone?: Tone
  icon?: LucideIcon
  children: ReactNode
  size?: 'sm' | 'md'
  title?: string
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap ${TONE[tone]} ${
        size === 'md' ? 'px-3 py-1.5 text-sm' : 'px-2.5 py-0.5 text-xs'
      }`}
    >
      {Icon && <Icon className={size === 'md' ? 'size-4' : 'size-3.5'} aria-hidden />}
      {children}
    </span>
  )
}

// ---------- form controls ----------

export function Select<T extends string>({
  value,
  onChange,
  options,
  label,
  icon: Icon,
  className = '',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  label: string
  icon?: LucideIcon
  className?: string
}) {
  return (
    <label className={`relative flex items-center ${className}`}>
      <span className="sr-only">{label}</span>
      {Icon && <Icon className="pointer-events-none absolute left-3 size-4 text-ink-2" aria-hidden />}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className={`h-10 w-full cursor-pointer appearance-none rounded-xl border border-line bg-surface pr-9 text-sm text-ink hover:bg-surface-2 ${
          Icon ? 'pl-9' : 'pl-3.5'
        }`}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 size-4 text-ink-2" aria-hidden />
    </label>
  )
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition ${
            value === o.value ? 'bg-accent text-white' : 'text-ink-2 hover:text-ink'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------- layout ----------

export function Card({
  title,
  subtitle,
  actions,
  icon: Icon,
  className = '',
  bodyClassName = 'px-5 pt-3 pb-5',
  children,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  icon?: LucideIcon
  className?: string
  bodyClassName?: string
  children: ReactNode
}) {
  return (
    <section className={`rounded-2xl border border-line bg-surface/90 shadow-[0_1px_2px_rgba(16,32,29,0.04)] backdrop-blur ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 px-5 pt-4">
          <div className="flex items-center gap-2">
            {Icon && <Icon className="size-4 text-ink-2" aria-hidden />}
            <div>
              {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
            </div>
          </div>
          {actions}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">{title}</h1>
        {description && <div className="mt-1 text-sm text-ink-2 md:text-base">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

/** Placeholder for a value the current role may not see (e.g. repair cost). */
export function Restricted({ label = 'Hidden' }: { label?: string }) {
  return (
    <span title="Hidden for your role" className="inline-flex items-center gap-1 text-xs text-muted">
      <Lock className="size-3" aria-hidden />
      {label}
    </span>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-2xl bg-surface-2 ${className}`} />
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
      Couldn't load this data. {message}
    </div>
  )
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <div className="rounded-full bg-surface-2 p-3">
        <Icon className="size-5 text-ink-2" aria-hidden />
      </div>
      <div className="text-sm font-medium text-ink">{title}</div>
      {children && <div className="max-w-sm text-xs leading-relaxed text-muted">{children}</div>}
    </div>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl border border-line bg-surface shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-2" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

/** Simple table, used for chart table-views. */
export function DataTable({
  columns,
  rows,
}: {
  columns: { key: string; label: string; numeric?: boolean }[]
  rows: Record<string, ReactNode>[]
}) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-surface-2">
          <tr className="text-xs text-ink-2">
            {columns.map((c) => (
              <th key={c.key} className={`px-3 py-2 font-medium ${c.numeric ? 'text-right' : 'text-left'}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              {columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 ${c.numeric ? 'tabular text-right text-ink' : 'text-ink-2'}`}>
                  {r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
