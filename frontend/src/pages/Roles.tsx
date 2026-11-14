import { Check, Minus, UserPlus, UserRound } from 'lucide-react'
import { Fragment } from 'react'
import { Card, Chip, PageHeader } from '../components/ui'
import { useRole } from '../lib/role'
import { can, manageableRoles, PERMISSIONS, ROLE_BY_ID, ROLES, type PermissionDef, type RoleDef } from '../lib/roles'

const LEVELS = [1, 2, 3, 4, 5]
const AREAS: PermissionDef['area'][] = ['Data & analysis', 'Work orders & reports', 'Security & admin']

export default function Roles() {
  const { role } = useRole()
  const support = ROLES.filter((r) => r.level === null)

  return (
    <>
      <PageHeader
        title="Roles & access"
        description="Who can do what in PlantSentinel, following the plant's reporting line."
        actions={<Chip tone="warning" size="md">Draft permissions · review with the team</Chip>}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="Plant hierarchy" subtitle="Reporting line of the maintenance organisation. Each role can add accounts for the roles below it.">
          <div className="flex flex-col items-center">
            {LEVELS.map((lvl, i) => {
              const row = ROLES.filter((r) => r.level === lvl)
              return (
                <Fragment key={lvl}>
                  {i > 0 && <div className="h-5 w-px bg-axis" aria-hidden />}
                  <div className="flex w-full flex-col items-center gap-2">
                    <span className="text-[11px] font-medium tracking-wide text-muted uppercase">Level {lvl}</span>
                    <div className="flex w-full flex-wrap justify-center gap-3">
                      {row.map((r) => (
                        <RoleCard key={r.id} r={r} current={r.id === role} />
                      ))}
                    </div>
                  </div>
                </Fragment>
              )
            })}
          </div>
        </Card>

        <Card title="Outside the reporting line" subtitle="Support roles with narrow, specific access">
          <div className="flex flex-col gap-3">
            {support.map((r) => (
              <RoleCard key={r.id} r={r} current={r.id === role} wide />
            ))}
          </div>
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Permission matrix"
        subtitle="Draft. The backend guard enforces the same table; it lives in frontend/src/lib/roles.ts."
        bodyClassName="p-2 pt-3"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-surface px-4 py-2 text-left text-xs font-medium text-ink-2">Permission</th>
                {ROLES.map((r) => (
                  <th
                    key={r.id}
                    title={r.label}
                    className={`px-2 py-2 text-center text-xs font-medium ${
                      r.id === role ? 'rounded-t-lg bg-accent-soft text-accent-ink' : 'text-ink-2'
                    }`}
                  >
                    {r.short}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {AREAS.map((area) => (
                <Fragment key={area}>
                  <tr>
                    <td colSpan={ROLES.length + 1} className="bg-surface-2 px-4 py-1.5 text-xs font-semibold text-ink">
                      {area}
                    </td>
                  </tr>
                  {PERMISSIONS.filter((p) => p.area === area).map((p) => (
                    <tr key={p.id} className="border-b border-line last:border-0">
                      <td className="sticky left-0 z-10 bg-surface px-4 py-2.5 whitespace-nowrap text-ink">{p.label}</td>
                      {ROLES.map((r) => {
                        const ok = can(r.id, p.id)
                        return (
                          <td key={r.id} className={`px-2 py-2.5 text-center ${r.id === role ? 'bg-accent-soft/50' : ''}`}>
                            {ok ? (
                              <Check className="mx-auto size-[18px] text-accent-ink" aria-label="Allowed" />
                            ) : (
                              <Minus className="mx-auto size-4 text-axis" aria-label="Not allowed" />
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

function RoleCard({ r, current, wide = false }: { r: RoleDef; current: boolean; wide?: boolean }) {
  const adds = manageableRoles(r.id)
  return (
    <div
      className={`rounded-xl border px-4 py-3 text-left ${wide ? 'w-full' : 'w-full sm:w-60'} ${
        current ? 'border-accent bg-accent-soft/70 shadow-sm' : 'border-line bg-surface'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-ink">{r.label}</span>
        {current && <Chip tone="accent">You</Chip>}
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-2">
        <UserRound className="size-3.5" aria-hidden /> Demo: <span className="font-mono">{demoUsername(r.user)}</span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">{r.description}</p>
      {adds.length > 0 && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-ink-2">
          <UserPlus className="mt-px size-3.5 shrink-0 text-accent-ink" aria-hidden />
          <span>
            Adds: {adds.length === ROLES.length ? 'anyone' : adds.map((id) => ROLE_BY_ID[id].short).join(', ')}
          </span>
        </p>
      )}
    </div>
  )
}

const demoUsername = (name: string) => name.toLowerCase().replace(/\s+/g, '').replace(/[^a-z.]/g, '')
