import { useState, type FormEvent } from 'react'
import { BrandMark } from '@/components/BrandMark'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { PasswordInput } from '@/components/ui/password-input'
import { useAuth } from '@/lib/auth'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

export function PasswordForm({ forced = false }: { forced?: boolean }) {
  const { changePassword, logout } = useAuth()
  const run = useRun()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = again !== '' && again !== next

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (mismatch) return
    if (await run(() => changePassword(current, next), 'Password changed')) {
      setCurrent('')
      setNext('')
      setAgain('')
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={forced ? 'Temporary password' : 'Current password'}>
        <PasswordInput required autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </Field>
      <Field label="New password">
        <PasswordInput required minLength={10} maxLength={128} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </Field>
      <Field label="Repeat the new password">
        <PasswordInput required autoComplete="new-password" aria-invalid={mismatch} value={again} onChange={(e) => setAgain(e.target.value)} />
      </Field>
      {mismatch && <p role="alert" className="text-sm text-danger">The two passwords do not match.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={mismatch || !current || next.length < 10}>Save new password</Button>
        {forced && <Button type="button" variant="outline" onClick={logout}>Sign out</Button>}
      </div>
    </form>
  )
}

/** The screen shown after a sign-in with a temporary password, before anything else. */
export function ChangePasswordPage() {
  const org = useApi<{ name: string; has_logo: boolean }>('/organization/public')
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <BrandMark organization={org.data?.name ?? ''} hasLogo={org.data?.has_logo ?? false} />
          <CardTitle className="pt-1 text-xl">Choose your own password</CardTitle>
        </CardHeader>
        <CardContent>
          <PasswordForm forced />
        </CardContent>
      </Card>
    </div>
  )
}
