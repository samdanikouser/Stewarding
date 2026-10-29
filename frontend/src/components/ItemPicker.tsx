import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Item } from '@/lib/useItems'
import { cn } from '@/lib/utils'

interface Props {
  items: Item[]
  value: string
  onChange: (id: string) => void
  label?: string
  placeholder?: string
  className?: string
  usual?: Set<number>  // items to list first, such as those bought from the supplier chosen on the form
}

const SHOWN = 100
const WIDE = 480  // px: wide enough to read a long item name without the list scrolling sideways

/** Type to find an item by code or name; arrow keys and Enter pick one. Replaces a drop-down that has to be scrolled. */
export function ItemPicker({ items, value, onChange, label = 'Item', placeholder = 'Type a code or name', className, usual }: Props) {
  const chosen = items.find((i) => String(i.id) === value)
  const text = chosen ? `${chosen.code} - ${chosen.name}` : ''
  const [typed, setTyped] = useState<string | null>(null)  // null: showing the chosen item, not a search
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const [place, setPlace] = useState<{ left: number; top: number; width: number; height: number } | null>(null)
  const listId = useId()

  const matches = useMemo(() => {
    const words = (typed ?? '').toLowerCase().split(/\s+/).filter(Boolean)
    const hits = words.length ? items.filter((i) => words.every((w) => `${i.code} ${i.name}`.toLowerCase().includes(w))) : items
    const found = usual?.size ? [...hits.filter((i) => usual.has(i.id)), ...hits.filter((i) => !usual.has(i.id))] : hits
    return { list: found.slice(0, SHOWN), more: Math.max(0, found.length - SHOWN) }
  }, [items, typed, usual])

  useEffect(() => {
    const away = (e: MouseEvent) => {
      const target = e.target as Node
      if (box.current && !box.current.contains(target) && !list.current?.contains(target)) {
        setOpen(false)
        setTyped(null)
      }
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  // the list is drawn on the page itself, not inside the form row, so a scrolling or narrow container cannot squeeze or clip it
  useLayoutEffect(() => {
    if (!open || !box.current) return
    const measure = () => {
      const r = box.current!.getBoundingClientRect()
      const width = Math.min(Math.max(r.width, WIDE), window.innerWidth - 16)
      const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8))
      const below = window.innerHeight - r.bottom - 12
      const above = r.top - 12
      const up = below < 220 && above > below
      const height = Math.max(160, Math.min(up ? above : below, 520))
      setPlace({ left, width, height, top: up ? r.top - height - 4 : r.bottom + 4 })
    }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open])

  useEffect(() => {
    list.current?.children[at]?.scrollIntoView?.({ block: 'nearest' })
  }, [at, open])

  const pick = (item: Item) => {
    onChange(String(item.id))
    setTyped(null)
    setOpen(false)
  }

  function keys(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setAt((n) => Math.min(n + 1, matches.list.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setAt((n) => Math.max(n - 1, 0))
    } else if (e.key === 'Enter' && open && matches.list[at]) {
      e.preventDefault()
      e.stopPropagation()  // choosing an item is not "commit this row"
      pick(matches.list[at])
    } else if (e.key === 'Escape') {
      setOpen(false)
      setTyped(null)
    }
  }

  return (
    <div ref={box} className={cn('relative', className)}>
      <input
        role="combobox" aria-label={label} aria-expanded={open} aria-controls={listId} aria-autocomplete="list" autoComplete="off"
        className="h-10 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm pointer-coarse:h-11 focus-visible:outline-2 focus-visible:outline-brand"
        placeholder={placeholder} value={typed ?? text}
        onFocus={(e) => { setOpen(true); e.currentTarget.select() }}
        onChange={(e) => { setTyped(e.target.value); setOpen(true); setAt(0); if (e.target.value === '') onChange('') }}
        onKeyDown={keys}
      />
      {open && place && createPortal(
        <ul id={listId} ref={list} role="listbox" style={{ position: 'fixed', left: place.left, top: place.top, width: place.width, maxHeight: place.height }}
          className="z-50 overflow-auto rounded-xl border border-border bg-surface py-1 shadow-xl">
          {matches.list.length === 0 && <li className="px-4 py-3 text-sm text-ink-muted">No item matches</li>}
          {matches.list.map((it, n) => (
            <li key={it.id} role="option" aria-selected={String(it.id) === value}
              className={cn('cursor-pointer px-4 py-2.5 text-sm', n === at && 'bg-brand-soft', String(it.id) === value && 'font-semibold')}
              onMouseEnter={() => setAt(n)} onMouseDown={(e) => { e.preventDefault(); pick(it) }}>
              <span className="mr-2 inline-block min-w-16 text-ink-muted tabular-nums">{it.code}</span>{it.name}
              <span className="ml-2 text-xs text-ink-muted">{it.unit}</span>{usual?.has(it.id) && <span className="ml-2 rounded bg-ok-soft px-1.5 py-0.5 text-[10px] font-medium text-ok">usual</span>}
            </li>
          ))}
          {matches.more > 0 && <li className="px-4 py-2 text-xs text-ink-muted">{matches.more} more. Keep typing to narrow the list.</li>}
        </ul>,
        document.body,
      )}
    </div>
  )
}
