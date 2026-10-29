import { useState } from 'react'

export type ViewMode = 'cards' | 'grid' | 'list'

export const VIEW_MODES: ViewMode[] = ['cards', 'grid', 'list']

/** The view chosen for a list, remembered in this browser; storage that is blocked just means the default each time. */
export function useViewMode(key: string, fallback: ViewMode = 'cards'): [ViewMode, (mode: ViewMode) => void] {
  const [mode, setMode] = useState<ViewMode>(() => {
    try {
      const saved = localStorage.getItem(`plato.view.${key}`)
      return VIEW_MODES.includes(saved as ViewMode) ? (saved as ViewMode) : fallback
    } catch {
      return fallback
    }
  })
  const choose = (next: ViewMode) => {
    setMode(next)
    try {
      localStorage.setItem(`plato.view.${key}`, next)
    } catch {
      // the choice still applies until the page is closed
    }
  }
  return [mode, choose]
}
