import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { api, setSessionUser } from '../api/client'
import type { AuthSession } from '../api/types'
import { AuthContext, useAuth } from '../lib/auth'

const KEY = 'ps-session'

function readSaved(): AuthSession | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as AuthSession) : null
  } catch {
    return null
  }
}

function save(s: AuthSession | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s))
    else localStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: the session lasts until the tab closes */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  // Nothing saved → ready at once; otherwise wait for the saved session to be re-checked
  const [ready, setReady] = useState(() => readSaved() === null)

  const apply = (s: AuthSession | null) => {
    setSessionUser(s) // before any screen fetches with the new identity
    save(s)
    setSession(s)
  }

  // Restore a saved session once, re-checking it with the API
  useEffect(() => {
    const saved = readSaved()
    if (!saved) return
    let alive = true
    void api.resume(saved).then((s) => {
      if (!alive) return
      apply(s)
      setReady(true)
    })
    return () => {
      alive = false
    }
  }, [])

  const signIn = async (username: string, password: string) => {
    apply(await api.login(username, password))
  }

  const signOut = async () => {
    await api.logout()
    apply(null)
  }

  if (!ready) return null
  return <AuthContext.Provider value={{ session, signIn, signOut }}>{children}</AuthContext.Provider>
}

/** Sends signed-out visitors to /login, remembering where they were going. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const location = useLocation()
  if (!session) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <>{children}</>
}
