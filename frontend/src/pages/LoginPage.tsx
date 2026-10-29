import { AlertCircle, ArrowRight, CheckCircle2, Loader2, Lock, Mail, TriangleAlert, User } from 'lucide-react'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { BrandMark } from '@/components/BrandMark'
import { LoginHero } from '@/components/LoginHero'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PasswordInput } from '@/components/ui/password-input'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { APP_NAME } from '@/lib/brand'
import { useApi } from '@/lib/useApi'

export function LoginPage() {
  const { login } = useAuth()
  const org = useApi<{ name: string; has_logo: boolean }>('/organization/public')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [signingUp, setSigningUp] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [shaking, setShaking] = useState(false)
  const [capsLock, setCapsLock] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (signingUp) {
        await api('/auth/signup', { body: { full_name: fullName, email, password } })
        setNotice('Request sent. You can sign in once a manager approves it.')
        setSigningUp(false)
        setPassword('')
      } else {
        setNotice(null)
        await login(email, password)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : signingUp ? 'Sign up failed' : 'Sign in failed')
      setShaking(true)
    } finally {
      setBusy(false)
    }
  }

  const watchCapsLock = (event: KeyboardEvent<HTMLElement>) => setCapsLock(event.getModifierState('CapsLock'))
  const switchMode = () => { setSigningUp(!signingUp); setError(null); setNotice(null) }

  return (
    <div className="grid min-h-screen grid-rows-[auto_1fr] lg:grid-cols-[1.1fr_1fr] lg:grid-rows-1">
      <LoginHero variant="banner" />
      <LoginHero variant="panel" />

      <main className="relative flex flex-1 items-start justify-center px-5 pb-10 pt-8 sm:px-8 lg:items-center lg:py-10">
        <div className={`login-rise w-full max-w-sm ${shaking ? 'login-shake' : ''}`} onAnimationEnd={(e) => { if (e.animationName === 'login-shake') setShaking(false) }}>
          {/* on a phone the banner already names the product, so the plain product name is shown only on wide screens */}
          <div className={org.data?.name ? undefined : 'hidden lg:block'}>
            <BrandMark organization={org.data?.name ?? ''} hasLogo={org.data?.has_logo ?? false} />
          </div>

          <div key={signingUp ? 'up' : 'in'} className="login-rise mt-8">
            <h1 className="text-3xl font-semibold tracking-tight">{signingUp ? 'Request an account' : 'Welcome back'}</h1>
            <p className="mt-2 text-sm text-ink-muted">
              {signingUp ? `Tell us who you are. A manager approves your request before you can sign in to ${APP_NAME}.` : `Sign in to ${APP_NAME} to pick up where your shift left off.`}
            </p>

            <form onSubmit={submit} className="mt-7 space-y-5">
              {signingUp && (
                <label className="login-rise block space-y-1.5 text-sm font-medium">
                  Full name
                  <span className="relative block">
                    <User aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
                    <Input className="pl-10" autoComplete="name" autoFocus required minLength={2} value={fullName} onChange={(e) => setFullName(e.target.value)} />
                  </span>
                </label>
              )}
              <label className="block space-y-1.5 text-sm font-medium">
                Email
                <span className="relative block">
                  <Mail aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
                  <Input className="pl-10" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
                </span>
              </label>
              <div className="space-y-1.5">
                <label className="block space-y-1.5 text-sm font-medium">
                  Password
                  <span className="relative block">
                    <Lock aria-hidden className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-ink-muted" />
                    <PasswordInput
                      className="pl-10"
                      autoComplete={signingUp ? 'new-password' : 'current-password'}
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={watchCapsLock}
                      onKeyUp={watchCapsLock}
                      onBlur={() => setCapsLock(false)}
                    />
                  </span>
                </label>
                {capsLock && (
                  <p role="status" className="flex items-center gap-1.5 text-xs font-medium text-warn">
                    <TriangleAlert aria-hidden className="h-3.5 w-3.5" /> Caps Lock is on
                  </p>
                )}
              </div>

              {notice && (
                <p role="status" className="login-rise flex items-start gap-2 rounded-lg bg-ok-soft px-3 py-2.5 text-sm text-ok">
                  <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /> {notice}
                </p>
              )}
              {error && (
                <p role="alert" className="login-rise flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-sm text-danger">
                  <AlertCircle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /> {error}
                </p>
              )}

              <Button type="submit" className="group h-11 w-full text-base shadow-md" disabled={busy}>
                {busy ? (
                  <><Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Please wait...</>
                ) : (
                  <>{signingUp ? 'Request account' : 'Sign in'} <ArrowRight aria-hidden className="h-4 w-4 transition-transform group-hover:translate-x-1" /></>
                )}
              </Button>
            </form>

            <div className="mt-6 border-t border-border pt-5 text-center text-sm">
              <button type="button" onClick={switchMode} className="font-semibold text-brand-deep underline-offset-4 hover:underline">
                {signingUp ? 'Back to sign in' : 'New here? Request an account'}
              </button>
              {!signingUp && <p className="mt-3 text-xs text-ink-muted">Forgot your password? Ask your manager to reset it.</p>}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
