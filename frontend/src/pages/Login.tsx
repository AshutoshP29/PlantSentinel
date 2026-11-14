import { Eye, EyeOff, Loader2, LogIn, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { AUTH_SERVER, DEMO_PASSWORD, SITE } from '../api/client'
import { useAuth } from '../lib/auth'
import { ROLES } from '../lib/roles'

/** Demo accounts follow the seeded users: initial.surname, one per role. */
const DEMO_ACCOUNTS = ROLES.map((r) => ({
  username: r.user.toLowerCase().replace(/\s+/g, '').replace(/[^a-z.]/g, ''),
  role: r.label,
}))

export default function Login() {
  const { session, signIn } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || '/'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (session) return <Navigate to={next} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Enter your username and password.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await signIn(username.trim(), password)
      navigate(next.startsWith('/') ? next : '/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="grid w-full max-w-4xl gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        {/* Sign-in card */}
        <section className="rounded-2xl border border-line bg-surface/95 p-7 shadow-sm backdrop-blur sm:p-9">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-10" />
            <div>
              <div className="text-xl font-bold tracking-tight text-ink">PlantSentinel</div>
              <div className="text-xs text-muted">{SITE}</div>
            </div>
          </div>

          <h1 className="mt-8 text-2xl font-bold tracking-tight text-ink">Sign in</h1>
          <p className="mt-1 text-sm text-ink-2">Your access depends on your role in the plant.</p>

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <div>
              <label htmlFor="username" className="mb-1.5 block text-sm font-medium text-ink">
                Username
              </label>
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                placeholder="e.g. a.rao"
                className="h-11 w-full rounded-xl border border-line bg-surface px-3.5 text-[15px] text-ink outline-none placeholder:text-muted focus:border-accent"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-ink">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={show ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  className="h-11 w-full rounded-xl border border-line bg-surface pr-11 pl-3.5 text-[15px] text-ink outline-none focus:border-accent"
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-ink-2 hover:text-ink"
                  aria-label={show ? 'Hide password' : 'Show password'}
                >
                  {show ? <EyeOff className="size-[18px]" /> : <Eye className="size-[18px]" />}
                </button>
              </div>
            </div>

            {error && (
              <p role="alert" className="rounded-lg bg-critical-soft px-3 py-2 text-sm text-critical-ink">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-accent text-[15px] font-medium text-white shadow-sm hover:bg-accent-hover disabled:opacity-60"
            >
              {busy ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <p className="mt-6 flex items-start gap-2 text-xs text-muted">
            <ShieldCheck className="mt-px size-4 shrink-0 text-good" aria-hidden />
            Runs fully offline. Accounts are created by your manager or the system admin.
          </p>
        </section>

        {/* Demo accounts */}
        {!AUTH_SERVER && (
          <section className="rounded-2xl border border-line bg-surface/80 p-6 backdrop-blur">
            <h2 className="text-base font-semibold text-ink">Demo accounts</h2>
            <p className="mt-1 text-xs text-ink-2">
              Every demo account uses the password <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-ink">{DEMO_PASSWORD}</code>.
              Click one to fill it in.
            </p>
            <ul className="mt-4 divide-y divide-line">
              {DEMO_ACCOUNTS.map((a) => (
                <li key={a.username}>
                  <button
                    type="button"
                    onClick={() => {
                      setUsername(a.username)
                      setPassword(DEMO_PASSWORD)
                      setError(null)
                    }}
                    className={`flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2 text-left text-sm hover:bg-surface-2 ${
                      username === a.username ? 'bg-accent-soft/60' : ''
                    }`}
                  >
                    <span className="font-mono text-ink">{a.username}</span>
                    <span className="text-xs text-ink-2">{a.role}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </main>
  )
}
