import { useState, useEffect } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import { LogIn, Eye, EyeOff, AlertCircle, KeyRound } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { ThemePill } from '@/components/ThemeToggle'
import { BookAnimation } from '@/components/BookAnimation'
import { cn } from '@/lib/utils'

const API_BASE = '/api'

// Human-readable messages for the ?sso_error= codes the OIDC callback bounces back.
const SSO_ERRORS: Record<string, string> = {
  misconfigured: 'SSO is misconfigured on the server (redirect URL). Contact your admin.',
  disabled: 'SSO is not enabled.',
  exchange: 'SSO sign-in could not be completed. Please try again.',
  claims: 'SSO sign-in failed: no identity information was returned.',
  not_allowed: 'Your account is not permitted to sign in to Tome.',
  no_account: 'No Tome account is linked to this identity, and self-signup is disabled.',
  inactive: 'Your Tome account is disabled.',
  oidc_error: 'SSO sign-in failed. Please try again.',
  callback: 'SSO sign-in did not complete. Please try again.',
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw Object.assign(new Error(text || res.statusText), { status: res.status })
  }
  return res.json() as Promise<T>
}

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // SSO (OIDC) state
  const [sso, setSso] = useState<{ enabled: boolean; button_label: string }>({ enabled: false, button_label: 'Sign in with SSO' })

  useEffect(() => {
    apiFetch<{ enabled: boolean; button_label: string }>('/auth/oidc/config')
      .then(setSso)
      .catch(() => {})
    // Surface an error bounced back from the OIDC callback (?sso_error=…)
    const reason = new URLSearchParams(window.location.search).get('sso_error')
    if (reason) {
      setError(SSO_ERRORS[reason] ?? 'SSO sign-in failed. Please try again.')
      // Clean the query string so a refresh doesn't re-show it
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  // Redirect AFTER all hooks have run — an early return before later hooks
  // (e.g. when a stale session resolves user null→set while mounted) trips
  // React's "rendered fewer hooks than expected".
  if (user) return <Navigate to="/" replace />

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4 safe-top">
      <style>{`
        @keyframes fade-in-up {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fade-in-up { animation: fade-in-up 0.4s ease-out both; }
      `}</style>

      <ThemePill className="fixed top-4 right-4" />

      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3 mb-8 cursor-default">
          <BookAnimation variant="levitate" className="block w-24 h-24 text-primary" strokeWidth={4} />
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Tome</h1>
        </div>

        {/* Card — fade in on mount */}
        <div className="bg-card border border-border rounded-2xl p-6 shadow-lg shadow-accent-soft animate-fade-in-up">

          <>
            <h2 className="text-lg font-medium text-foreground mb-1">Welcome back</h2>
            <p className="text-sm text-muted-foreground mb-6">Sign in to your library</p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Username or email
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoComplete="username"
                  className={cn(
                    'w-full px-3 py-2.5 rounded-lg text-sm bg-background border',
                    'text-foreground placeholder:text-muted-foreground/50',
                    'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent focus:scale-[1.01]',
                    'transition-all duration-200',
                    error ? 'border-destructive' : 'border-input'
                  )}
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    autoComplete="current-password"
                    className={cn(
                      'w-full px-3 py-2.5 pr-10 rounded-lg text-sm bg-background border',
                      'text-foreground placeholder:text-muted-foreground/50',
                      'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent focus:scale-[1.01]',
                      'transition-all duration-200',
                      error ? 'border-destructive' : 'border-input'
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(s => !s)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="flex items-center gap-2 text-destructive text-sm p-3 rounded-lg bg-destructive/10 border border-destructive/20">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className={cn(
                  'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg',
                  'bg-primary text-primary-foreground text-sm font-medium',
                  'hover:opacity-90 hover:-translate-y-0.5 hover:shadow-md hover:shadow-primary/20',
                  'active:translate-y-0 active:shadow-none',
                  'transition-all duration-200',
                  'disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none disabled:shadow-none'
                )}
              >
                {loading ? (
                  <div className="w-4 h-4 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
                ) : (
                  <>
                    <LogIn className="w-4 h-4" />
                    Sign in
                  </>
                )}
              </button>
            </form>

            {/* SSO button */}
            {sso.enabled && (
              <div className="mt-4 pt-4 border-t border-border">
                <button
                  onClick={() => { window.location.href = `${API_BASE}/auth/oidc/login` }}
                  className={cn(
                    'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg',
                    'border border-border text-sm font-medium text-foreground',
                    'hover:bg-muted hover:-translate-y-0.5 hover:shadow-sm',
                    'transition-all duration-200'
                  )}
                >
                  <KeyRound className="w-4 h-4" />
                  {sso.button_label}
                </button>
              </div>
            )}
          </>
        </div>

        <p className="text-center text-xs text-muted-foreground mt-6">
          Tome · Your personal library
        </p>
      </div>
    </div>
  )
}
