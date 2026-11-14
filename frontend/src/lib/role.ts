import type { UserAccount } from '../api/types'
import { useAuth } from './auth'
import { can, ROLE_BY_ID, type Permission, type RoleDef, type RoleId } from './roles'

export interface RoleCtx {
  role: RoleId
  def: RoleDef
  account: UserAccount
  /** display name of the signed-in person */
  user: string
  can: (p: Permission) => boolean
  /** null when allowed, otherwise a short reason for a disabled button's tooltip */
  deny: (p: Permission) => string | null
  signOut: () => Promise<void>
}

/** The signed-in person's role and permissions. Only used inside signed-in screens. */
export function useRole(): RoleCtx {
  const { session, signOut } = useAuth()
  if (!session) throw new Error('useRole needs a signed-in user')
  const role = (session.user.role in ROLE_BY_ID ? session.user.role : 'operator') as RoleId
  const def = ROLE_BY_ID[role]
  return {
    role,
    def,
    account: session.user,
    user: session.user.name,
    can: (p) => can(role, p),
    deny: (p) => (can(role, p) ? null : `Not allowed for ${def.label}`),
    signOut,
  }
}
