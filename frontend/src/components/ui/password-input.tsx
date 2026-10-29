import { Eye, EyeOff } from 'lucide-react'
import { useState, type InputHTMLAttributes } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/** A password field with a button that shows what was typed, so a typing mistake can be seen before it is submitted. */
export function PasswordInput({ className, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>) {
  const [shown, setShown] = useState(false)
  return (
    <span className="relative block">
      <Input {...props} type={shown ? 'text' : 'password'} className={cn('pr-11', className)} />
      <button
        type="button"
        aria-label={shown ? 'Hide password' : 'Show password'}
        aria-pressed={shown}
        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-brand"
        onClick={() => setShown((s) => !s)}
      >
        {shown ? <EyeOff aria-hidden className="h-4 w-4" /> : <Eye aria-hidden className="h-4 w-4" />}
      </button>
    </span>
  )
}
