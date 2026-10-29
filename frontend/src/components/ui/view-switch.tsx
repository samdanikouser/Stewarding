import { LayoutGrid, List, Rows3, type LucideIcon } from 'lucide-react'
import type { ViewMode } from '@/lib/viewMode'
import { cn } from '@/lib/utils'

const VIEWS: { mode: ViewMode; label: string; icon: LucideIcon }[] = [
  { mode: 'cards', label: 'Cards', icon: Rows3 },
  { mode: 'grid', label: 'Grid', icon: LayoutGrid },
  { mode: 'list', label: 'List', icon: List },
]

/** Buttons that switch a list between cards, a grid of tiles and a plain list. */
export function ViewSwitch({ value, onChange }: { value: ViewMode; onChange: (mode: ViewMode) => void }) {
  return (
    <div role="group" aria-label="View as" className="inline-flex rounded-lg border border-border bg-surface p-0.5">
      {VIEWS.map(({ mode, label, icon: Icon }) => (
        <button
          key={mode}
          type="button"
          aria-pressed={value === mode}
          onClick={() => onChange(mode)}
          className={cn('inline-flex min-h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium', value === mode ? 'bg-brand text-brand-ink' : 'text-ink-muted hover:text-ink')}
        >
          <Icon aria-hidden className="h-4 w-4" /> <span className="sr-only sm:not-sr-only">{label}</span>
        </button>
      ))}
    </div>
  )
}
