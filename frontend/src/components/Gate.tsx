import { Lock } from 'lucide-react'
import type { ReactNode } from 'react'
import { useRole } from '../lib/role'
import { PERMISSIONS, type Permission } from '../lib/roles'
import { Card, LinkButton } from './ui'

/** Renders children only when the current role has `perm`; otherwise an access notice. */
export function Gate({ perm, children }: { perm: Permission; children: ReactNode }) {
  const { can, def } = useRole()
  if (can(perm)) return <>{children}</>
  const label = PERMISSIONS.find((p) => p.id === perm)?.label.toLowerCase() ?? perm
  return (
    <Card className="mx-auto mt-10 max-w-lg text-center" bodyClassName="px-6 py-10">
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-surface-2">
        <Lock className="size-5 text-ink-2" aria-hidden />
      </div>
      <h1 className="mt-4 text-lg font-semibold text-ink">No access for {def.label}</h1>
      <p className="mt-1 text-sm text-ink-2">
        This screen needs permission to {label}. Ask your Maintenance Manager or System Admin if you need it.
      </p>
      <div className="mt-5 flex justify-center">
        <LinkButton to="/roles" variant="soft">
          See roles &amp; access
        </LinkButton>
      </div>
    </Card>
  )
}
