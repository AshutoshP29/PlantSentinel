// The caller supplies the deps list (same contract as useEffect), so the
// static deps check can't see it.
/* oxlint-disable react-hooks/exhaustive-deps */
import { useEffect, useState } from 'react'

export interface ApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

/** Runs an API call on mount (and when deps change) and tracks its state. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null })

  // Callers pass their own deps list, like useEffect itself.
  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((data) => !cancelled && setState({ data, loading: false, error: null }))
      .catch((e: unknown) =>
        !cancelled &&
        setState({ data: null, loading: false, error: e instanceof Error ? e.message : String(e) }),
      )
    return () => {
      cancelled = true
    }
  }, deps)

  return state
}
