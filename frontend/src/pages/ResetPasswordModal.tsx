import { Check, Copy } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import type { EmployeeRow } from '@/pages/EmployeeForm'

export function ResetPasswordModal({ employee, onClose, onDone }: { employee: EmployeeRow; onClose: () => void; onDone: () => void }) {
  const run = useRun()
  const [custom, setCustom] = useState('')
  const [issued, setIssued] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function reset(event: FormEvent) {
    event.preventDefault()
    let password: string | null = null
    const ok = await run(async () => {
      const result = await api<{ temporary_password: string }>(`/employees/${employee.id}/reset-password`, { body: { new_password: custom || null } })
      password = result.temporary_password
    }, 'Password reset')
    if (ok && password) {
      setIssued(password)
      onDone()
    }
  }

  async function copy() {
    if (!issued) return
    try {
      await navigator.clipboard.writeText(issued)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Modal
      open
      size="md"
      title={issued ? 'Temporary password' : 'Reset password'}
      description={employee.full_name}
      onClose={onClose}
      footer={issued ? <Button onClick={onClose}>Done</Button> : <>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="reset-password-form">Reset password</Button>
      </>}
    >
      {issued ? (
        <div className="space-y-4">
          <p className="text-sm">Give this temporary password to {employee.full_name} in person. It is shown only now.</p>
          <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-muted px-4 py-3">
            <code className="flex-1 select-all text-lg tracking-wider">{issued}</code>
            <Button type="button" variant="outline" size="sm" onClick={copy}>{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copied ? 'Copied' : 'Copy'}</Button>
          </div>
          <p className="text-sm text-ink-muted">They will be asked to choose their own password at the next sign-in, and any open sessions have ended.</p>
        </div>
      ) : (
        <form id="reset-password-form" onSubmit={reset} className="space-y-5">
          <p className="text-sm text-ink-muted">A temporary password is generated for you to pass on. The employee must replace it when they sign in, and their open sessions end now.</p>
          <Field label="Or set one yourself (optional)">
            <Input type="text" autoComplete="off" value={custom} minLength={custom ? 10 : undefined} onChange={(e) => setCustom(e.target.value)} />
          </Field>
        </form>
      )}
    </Modal>
  )
}
