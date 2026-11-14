import { useEffect, useState } from 'react'
import { api, USE_MOCK } from '../api/client'
import { useTopicVersion } from '../api/events'
import type { BlockedAttempt, PrivacyStatus } from '../api/types'

const POLL_MS = 3000

/** Live network status, polled every few seconds. */
export function usePrivacyStatus(): PrivacyStatus | null {
  const [status, setStatus] = useState<PrivacyStatus | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => api.getPrivacyStatus().then((s) => alive && setStatus(s)).catch(() => {})
    load()
    const t = window.setInterval(load, POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])
  return status
}

/** Blocked exfiltration attempts; refreshes on demo events, polls the real backend. */
export function useBlockedAttempts(): BlockedAttempt[] {
  const version = useTopicVersion('blocked')
  const [list, setList] = useState<BlockedAttempt[]>([])
  useEffect(() => {
    let alive = true
    const load = () => api.getBlockedAttempts().then((l) => alive && setList(l)).catch(() => {})
    load()
    const t = USE_MOCK ? undefined : window.setInterval(load, POLL_MS)
    return () => {
      alive = false
      if (t) clearInterval(t)
    }
  }, [version])
  return list
}
