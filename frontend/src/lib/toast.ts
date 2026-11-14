import { createContext, useContext } from 'react'

export interface ToastInput {
  title: string
  body?: string
  tone?: 'default' | 'critical' | 'good'
  action?: { label: string; to: string }
}

export const ToastContext = createContext<((t: ToastInput) => void) | null>(null)

export function useToast(): (t: ToastInput) => void {
  const push = useContext(ToastContext)
  if (!push) throw new Error('useToast must be used inside <ToastProvider>')
  return push
}
