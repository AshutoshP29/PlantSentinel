import { Loader2, Trash2, UserPlus } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { useTopicVersion } from '../api/events'
import type { UserAccount } from '../api/types'
import { Button, Card, Chip, ErrorNote, PageHeader, Skeleton } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { formatWhen } from '../lib/format'
import { useRole } from '../lib/role'
import { canManageRole, manageableRoles, ROLE_BY_ID, ROLES, type RoleId } from '../lib/roles'
import { TD, TH } from '../lib/status'
import { useToast } from '../lib/toast'

export default function Users() {
  const { role, def } = useRole()
  const version = useTopicVersion('users')
  const users = useApi(() => api.listUsers(), [version])
  const allowed = manageableRoles(role)
  const allowedLabels = allowed.map((r) => ROLE_BY_ID[r].label)

  return (
    <>
      <PageHeader
        title="Users"
        description="Add accounts for the people who report to you. Each person signs in with their own username and password."
      />

      <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
        <Card
          title="Add a person"
          subtitle={
            <>
              As {def.label}, you can add: <span className="text-ink-2">{allowedLabels.join(', ')}</span>
            </>
          }
        >
          <AddUserForm allowed={allowed} />
        </Card>

        <Card title="People" subtitle="Everyone with access to PlantSentinel at this site" bodyClassName="p-2 pt-3">
          {users.error ? (
            <div className="p-3">
              <ErrorNote message={users.error} />
            </div>
          ) : !users.data ? (
            <div className="p-3">
              <Skeleton className="h-64" />
            </div>
          ) : (
            <PeopleTable users={users.data} />
          )}
        </Card>
      </div>
    </>
  )
}

function AddUserForm({ allowed }: { allowed: RoleId[] }) {
  const toast = useToast()
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<RoleId>(allowed[allowed.length - 1] ?? allowed[0])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Offer roles in hierarchy order
  const options = ROLES.filter((r) => allowed.includes(r.id))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!name.trim() || !username.trim() || !password) {
      setError('Fill in name, username and password.')
      return
    }
    setBusy(true)
    try {
      const u = await api.createUser({ name, username, password, role })
      toast({ title: `${u.name} added`, body: `Signs in as ${u.username} · ${ROLE_BY_ID[u.role as RoleId].label}`, tone: 'good' })
      setName('')
      setUsername('')
      setPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const field = 'h-10 w-full rounded-xl border border-line bg-surface px-3 text-sm text-ink outline-none placeholder:text-muted focus:border-accent'

  return (
    <form onSubmit={submit} className="space-y-3.5" noValidate>
      <div>
        <label htmlFor="nu-name" className="mb-1 block text-sm font-medium text-ink">
          Full name
        </label>
        <input id="nu-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. R. Patel" className={field} />
      </div>
      <div>
        <label htmlFor="nu-username" className="mb-1 block text-sm font-medium text-ink">
          Username
        </label>
        <input
          id="nu-username"
          value={username}
          onChange={(e) => setUsername(e.target.value.toLowerCase())}
          placeholder="e.g. r.patel"
          autoCapitalize="none"
          spellCheck={false}
          autoComplete="off"
          className={`${field} font-mono`}
        />
      </div>
      <div>
        <label htmlFor="nu-password" className="mb-1 block text-sm font-medium text-ink">
          Temporary password
        </label>
        <input
          id="nu-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          className={field}
        />
        <p className="mt-1 text-xs text-muted">At least 8 characters. Share it with the person directly.</p>
      </div>
      <div>
        <label htmlFor="nu-role" className="mb-1 block text-sm font-medium text-ink">
          Role
        </label>
        <select id="nu-role" value={role} onChange={(e) => setRole(e.target.value as RoleId)} className={`${field} cursor-pointer`}>
          {options.map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-muted">{ROLE_BY_ID[role]?.description}</p>
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-critical-soft px-3 py-2 text-sm text-critical-ink">
          {error}
        </p>
      )}

      <Button type="submit" variant="primary" icon={busy ? Loader2 : UserPlus} disabled={busy} className="w-full">
        {busy ? 'Adding…' : 'Add person'}
      </Button>
    </form>
  )
}

function PeopleTable({ users }: { users: UserAccount[] }) {
  const { role, account } = useRole()
  const toast = useToast()
  const [removing, setRemoving] = useState<string | null>(null)

  // Hierarchy order, then name
  const rows = useMemo(() => {
    const order = new Map(ROLES.map((r, i) => [r.id, i]))
    return [...users].sort(
      (a, b) => (order.get(a.role as RoleId) ?? 99) - (order.get(b.role as RoleId) ?? 99) || a.name.localeCompare(b.name),
    )
  }, [users])

  const remove = async (u: UserAccount) => {
    if (!window.confirm(`Remove ${u.name} (${u.username})? They will no longer be able to sign in.`)) return
    setRemoving(u.username)
    try {
      await api.removeUser(u.username)
      toast({ title: `${u.name} removed`, tone: 'good' })
    } catch (err) {
      toast({ title: 'Could not remove', body: err instanceof Error ? err.message : String(err), tone: 'critical' })
    } finally {
      setRemoving(null)
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="bg-surface-2">
            <th className={`${TH} rounded-l-lg`}>Name</th>
            <th className={TH}>Username</th>
            <th className={TH}>Role</th>
            <th className={TH}>Added by</th>
            <th className={TH}>Added</th>
            <th className={`${TH} rounded-r-lg`}>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => {
            const isMe = u.username === account.username
            const seeded = u.added_by === null
            const manageable = canManageRole(role, u.role as RoleId)
            const reason = isMe
              ? 'You can’t remove yourself'
              : !manageable
                ? 'Only people below you in the hierarchy'
                : seeded
                  ? 'Demo accounts can’t be removed'
                  : null
            return (
              <tr key={u.username} className={`border-b border-line last:border-0 ${isMe ? 'bg-accent-soft/40' : ''}`}>
                <td className={`${TD} font-medium text-ink`}>
                  {u.name} {isMe && <Chip tone="accent">You</Chip>}
                </td>
                <td className={`${TD} font-mono text-[13px] text-ink-2`}>{u.username}</td>
                <td className={`${TD} whitespace-nowrap text-ink`}>{ROLE_BY_ID[u.role as RoleId]?.label ?? u.role}</td>
                <td className={`${TD} font-mono text-[13px] text-muted`}>{u.added_by ?? 'demo setup'}</td>
                <td className={`${TD} whitespace-nowrap text-ink-2`}>{formatWhen(u.created_at)}</td>
                <td className={`${TD} text-right`}>
                  <Button
                    size="sm"
                    variant="danger"
                    icon={removing === u.username ? Loader2 : Trash2}
                    onClick={() => remove(u)}
                    disabled={removing === u.username}
                    disabledReason={reason}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
