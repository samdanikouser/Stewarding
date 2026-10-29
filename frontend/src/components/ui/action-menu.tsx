import { MoreHorizontal, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface MenuAction {
  label: string
  onClick: () => void
  icon?: LucideIcon
  tone?: 'danger'
  hidden?: boolean
}

interface ActionMenuProps {
  label: string
  text?: string
  actions: MenuAction[]
}

/** A "more actions" button that opens a short list; the list floats above the page so a table cannot clip it. */
export function ActionMenu({ label, actions, text }: ActionMenuProps) {
  const [spot, setSpot] = useState<{ top: number; right: number } | null>(null)
  const button = useRef<HTMLSpanElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const shown = actions.filter((a) => !a.hidden)

  useEffect(() => {
    if (!spot) return
    const close = () => setSpot(null)
    const outside = (event: MouseEvent) => {
      const target = event.target as Node
      if (!menu.current?.contains(target) && !button.current?.contains(target)) close()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close()
        button.current?.querySelector('button')?.focus()
      }
    }
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', key)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', key)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [spot])

  function toggle() {
    if (spot) return setSpot(null)
    const box = button.current?.getBoundingClientRect()
    if (box) setSpot({ top: box.bottom + 6, right: window.innerWidth - box.right })
  }

  function move(event: React.KeyboardEvent) {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const items = [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
    const at = items.indexOf(document.activeElement as HTMLElement)
    items[(at + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus()
  }

  return (
    <>
      <span ref={button} className="inline-flex">
        <Button type="button" size={text ? 'sm' : 'icon'} variant="outline" aria-label={label} aria-haspopup="menu" aria-expanded={spot !== null} onClick={toggle}>
          <MoreHorizontal className="h-4 w-4" aria-hidden />{text}
        </Button>
      </span>
      {spot && (
        <div
          ref={menu}
          role="menu"
          aria-label={label}
          onKeyDown={move}
          style={{ position: 'fixed', top: spot.top, right: spot.right }}
          className="z-50 min-w-48 rounded-xl border border-border bg-surface p-1.5 shadow-lg"
        >
          {shown.map(({ label: text, onClick, icon: Icon, tone }) => (
            <button
              key={text}
              type="button"
              role="menuitem"
              onClick={() => { setSpot(null); onClick() }}
              className={cn('flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-surface-muted focus-visible:bg-surface-muted focus-visible:outline-none',
                tone === 'danger' && 'text-danger hover:bg-danger-soft focus-visible:bg-danger-soft')}
            >
              {Icon && <Icon aria-hidden className="h-4 w-4 shrink-0" />} {text}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
