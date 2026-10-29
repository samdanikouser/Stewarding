import { Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Input } from '@/components/ui/input'
import { SECTION_TITLES, SETTINGS } from '@/pages/settings/settingsRegistry'
import { SECTION_GROUPS } from '@/pages/settings/sections'

const plain = (text: string) => text.toLowerCase().replace(/[-\s]+/g, '')

/** Section names and the rules on the rules pages that contain the words typed, ignoring spaces and hyphens so check in finds check-in. */
function findSettings(query: string) {
  const needle = plain(query)
  if (!needle) return null
  const sections = SECTION_GROUPS.flatMap((group) =>
    group.items.filter(([, text]) => plain(text).includes(needle)).map(([key, text]) => ({ key, title: text, where: group.title })))
  const rules = SETTINGS.filter((s) => plain(s.label).includes(needle)).map((s) => ({ key: s.section, title: s.label, where: SECTION_TITLES[s.section] }))
  return [...sections, ...rules]
}

/** A small search box in the settings header; the matches open as a list under it. */
export function SettingsSearch() {
  const [query, setQuery] = useState('')
  const results = findSettings(query)

  return (
    <div className="relative w-44 sm:w-64">
      <Search aria-hidden className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-muted" />
      <Input type="search" aria-label="Search settings" placeholder="Search settings" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
      {results && (
        <ul className="absolute right-0 top-full z-20 mt-2 max-h-80 w-72 overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-lg sm:w-80">
          {results.length === 0 && <li className="px-3 py-3 text-sm text-ink-muted">Nothing matches</li>}
          {results.map((r) => (
            <li key={`${r.where}|${r.title}`}>
              <Link to={`/settings/${r.key}`} onClick={() => setQuery('')} className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-muted focus-visible:bg-surface-muted focus-visible:outline-none">
                {r.title}
                <span className="block text-xs text-ink-muted">{r.where}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
