import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

export interface TabItem {
  key: string
  label: string
}

export interface TabGroup {
  title: string
  items: TabItem[]
}

interface SectionTabsProps {
  label: string
  groups: TabGroup[]
  active: string
  hrefFor?: (key: string) => string
  onSelect?: (key: string) => void
  trailing?: ReactNode
}

function Entry({ href, onClick, current, className, children }: { href?: string; onClick: () => void; current: boolean; className: string; children: ReactNode }) {
  return href ? (
    <Link to={href} aria-current={current ? 'page' : undefined} className={className}>{children}</Link>
  ) : (
    <button type="button" onClick={onClick} aria-current={current ? 'page' : undefined} className={className}>{children}</button>
  )
}

/** Topic tabs with the sections of the open topic as pills beneath, for pages that hold many screens. */
export function SectionTabs({ label, groups, active, hrefFor, onSelect, trailing }: SectionTabsProps) {
  const current = groups.find((group) => group.items.some((item) => item.key === active)) ?? groups[0]
  const choose = (key: string) => onSelect?.(key)

  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-4 border-b border-border">
        <nav aria-label={`${label} topics`} className="-mb-px flex min-w-0 gap-1 overflow-x-auto">
          {groups.map((group) => {
            const open = group === current
            const first = group.items[0].key
            return (
              <Entry
                key={group.title}
                href={hrefFor?.(first)}
                onClick={() => choose(first)}
                current={open}
                className={cn(
                  'shrink-0 border-b-2 px-4 py-3 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brand',
                  open ? 'border-brand font-semibold text-ink' : 'border-transparent font-medium text-ink-muted hover:border-border-strong hover:text-ink',
                )}
              >
                {group.title}
              </Entry>
            )
          })}
        </nav>
        {trailing && <div className="shrink-0 pb-2">{trailing}</div>}
      </div>

      {current.items.length > 1 && (
        <nav aria-label={`${label} sections`} className="flex flex-wrap gap-2">
          {current.items.map((item) => (
            <Entry
              key={item.key}
              href={hrefFor?.(item.key)}
              onClick={() => choose(item.key)}
              current={item.key === active}
              className={cn(
                'rounded-full px-4 py-1.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
                item.key === active ? 'bg-brand-soft font-semibold text-brand-deep ring-1 ring-brand/40' : 'border border-border bg-surface text-ink hover:bg-surface-muted',
              )}
            >
              {item.label}
            </Entry>
          ))}
        </nav>
      )}
    </div>
  )
}
