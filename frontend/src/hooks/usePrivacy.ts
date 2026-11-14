import { useEffect, useState } from 'react'
import { api, isLive } from '../api/client'
import { useTopicVersion } from '../api/events'
import type { BlockedAttempt, PrivacyStatus } from '../api/types'

const POLL_MS = 2000

/** Live network status, polled every 2 seconds. */
export function usePrivacyStatus(): PrivacyStatus | null {
  return usePrivacyFeed().status
}

/** Status plus whether the last poll failed (endpoint missing or backend down). */
export function usePrivacyFeed(): { status: PrivacyStatus | null; failed: boolean } {
  const [status, setStatus] = useState<PrivacyStatus | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .getPrivacyStatus()
        .then((s) => alive && (setStatus(s), setFailed(false)))
        .catch(() => alive && setFailed(true))
    load()
    const t = window.setInterval(load, POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])
  return { status, failed }
}

/**
 * Blocked exfiltration attempts: blocked tool calls seen in this browser's agent streams,
 * plus the backend's list when the privacy endpoints are live (polled every 2 seconds).
 */
export function useBlockedAttempts(): BlockedAttempt[] {
  const version = useTopicVersion('blocked')
  const [list, setList] = useState<BlockedAttempt[]>([])
  useEffect(() => {
    let alive = true
    const load = () => api.getBlockedAttempts().then((l) => alive && setList(l)).catch(() => {})
    load()
    const t = isLive('privacy') ? window.setInterval(load, POLL_MS) : undefined
    return () => {
      alive = false
      if (t) clearInterval(t)
    }
  }, [version])
  return list
}
