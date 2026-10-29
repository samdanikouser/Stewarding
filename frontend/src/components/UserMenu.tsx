import { ChevronUp } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { useAuth } from '@/lib/auth'
import { initials } from '@/lib/format'

const ITEM = 'block w-full rounded-lg px-3 py-2.5 text-left text-sm hover:bg-surface-muted focus-visible:bg-surface-muted focus-visible:outline-none'

/** The signed-in person at the foot of the sidebar; opens a small menu with their details and account links. */
export function UserMenu({ onNavigate }: { onNavigate: () => void }) {
  const { me, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const outside = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        trigger.current?.focus()
      }
    }
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  if (!me) return null
  const name = me.employee?.name ?? me.email
  const go = () => {
    setOpen(false)
    onNavigate()
  }

  return (
    <div ref={root} className="relative m-3">
      {open && (
        <div role="menu" aria-label="Account" className="absolute inset-x-0 bottom-full z-30 mb-2 rounded-xl border border-border bg-surface p-2 text-ink shadow-lg">
          <div className="border-b border-border px-3 pb-3 pt-2">
            <p className="truncate text-sm font-semibold">{name}</p>
            <p className="truncate text-xs text-ink-muted">{me.email}</p>
            <Badge className="mt-2">{me.role_label}</Badge>
          </div>
          <div className="pt-1">
            <Link role="menuitem" to="/account" className={ITEM} onClick={go}>My profile</Link>
            <Link role="menuitem" to="/account#security" className={ITEM} onClick={go}>Change password</Link>
            <button type="button" role="menuitem" className={`${ITEM} text-danger`} onClick={logout}>Sign out</button>
          </div>
        </div>
      )}
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 rounded-xl bg-white/8 p-3 text-left hover:bg-white/12 focus-visible:outline-2 focus-visible:outline-white"
      >
        <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-sm font-semibold">{initials(name)}</span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-sm font-medium">{name}</span>
          <span className="block truncate text-xs text-white/60">{me.role_label}</span>
        </span>
        <ChevronUp aria-hidden className={`h-4 w-4 shrink-0 text-white/60 transition-transform ${open ? '' : 'rotate-180'}`} />
      </button>
    </div>
  )
}
