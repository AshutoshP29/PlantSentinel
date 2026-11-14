import { createContext, useContext } from 'react'
import type { AuthSession } from '../api/types'

export interface AuthCtx {
  session: AuthSession | null
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  /** Demo role switcher: become a seeded demo account (no password). */
  switchUser: (username: string) => Promise<void>
}

export const AuthContext = createContext<AuthCtx | null>(null)

export function useAuth(): AuthCtx {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
