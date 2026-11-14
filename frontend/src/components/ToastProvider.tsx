import { CheckCircle2, Info, ShieldAlert, X } from 'lucide-react'
import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ToastContext, type ToastInput } from '../lib/toast'

interface Toast extends ToastInput {
  id: number
}

let next = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const push = useCallback(
    (t: ToastInput) => {
      const id = next++
      setToasts((list) => [...list.slice(-2), { ...t, id }])
      window.setTimeout(() => dismiss(id), 5000)
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => {
          const Icon = t.tone === 'critical' ? ShieldAlert : t.tone === 'good' ? CheckCircle2 : Info
          const iconColor = t.tone === 'critical' ? 'text-critical' : t.tone === 'good' ? 'text-good' : 'text-accent-ink'
          return (
            <div
              key={t.id}
              className="pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-lg"
            >
              <Icon className={`mt-0.5 size-5 shrink-0 ${iconColor}`} aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-ink">{t.title}</div>
                {t.body && <div className="mt-0.5 text-xs text-ink-2">{t.body}</div>}
                {t.action && (
                  <Link
                    to={t.action.to}
                    onClick={() => dismiss(t.id)}
                    className="mt-1.5 inline-block text-xs font-medium text-accent-ink hover:underline"
                  >
                    {t.action.label}
                  </Link>
                )}
              </div>
              <button type="button" onClick={() => dismiss(t.id)} className="rounded p-0.5 text-muted hover:text-ink" aria-label="Dismiss">
                <X className="size-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
