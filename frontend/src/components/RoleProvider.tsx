import { useState, type ReactNode } from 'react'
import { setSessionRole } from '../api/client'
import { RoleContext } from '../lib/role'
import { can, DEFAULT_ROLE, ROLE_BY_ID, type Permission, type RoleId } from '../lib/roles'

const KEY = 'ps-role'

/** The demo "sign-in": remembers the chosen role in this browser so a refresh keeps it. */
function initialRole(): RoleId {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved && saved in ROLE_BY_ID) return saved as RoleId
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_ROLE
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<RoleId>(() => {
    const r = initialRole()
    setSessionRole(r)
    return r
  })
  const def = ROLE_BY_ID[role]

  const setRole = (r: RoleId) => {
    setSessionRole(r)
    setRoleState(r)
    try {
      localStorage.setItem(KEY, r)
    } catch {
      /* storage unavailable: role still applies for this session */
    }
  }

  return (
    <RoleContext.Provider
      value={{
        role,
        def,
        user: def.user,
        setRole,
        can: (p: Permission) => can(role, p),
        deny: (p: Permission) => (can(role, p) ? null : `Not allowed for ${def.label}`),
      }}
    >
      {children}
    </RoleContext.Provider>
  )
}
