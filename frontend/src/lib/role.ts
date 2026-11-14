import { createContext, useContext } from 'react'
import type { Permission, RoleDef, RoleId } from './roles'

export interface RoleCtx {
  role: RoleId
  def: RoleDef
  user: string
  setRole: (r: RoleId) => void
  can: (p: Permission) => boolean
  /** null when allowed, otherwise a short reason for a disabled button's tooltip */
  deny: (p: Permission) => string | null
}

export const RoleContext = createContext<RoleCtx | null>(null)

export function useRole(): RoleCtx {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRole must be used inside <RoleProvider>')
  return ctx
}
