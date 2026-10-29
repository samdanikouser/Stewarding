import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'plato-theme'
const listeners = new Set<() => void>()

const asTheme = (value: string | null): Theme | null => (value === 'light' || value === 'dark' ? value : null)

function remembered(): Theme | null {
  try {
    return asTheme(localStorage.getItem(KEY))
  } catch {
    return null
  }
}

let chosen: Theme | null = null
const systemDark = () => window.matchMedia('(prefers-color-scheme: dark)')

/** The theme in use: the one a person chose, otherwise the one their device asks for. */
export const currentTheme = (): Theme => chosen ?? (systemDark().matches ? 'dark' : 'light')

function apply() {
  document.documentElement.dataset.theme = currentTheme()
  listeners.forEach((listener) => listener())
}

export function setTheme(theme: Theme) {
  chosen = theme
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // storage is blocked, so the choice lasts until the page is closed
  }
  apply()
}

/** Applies the saved or device theme before the first screen is drawn, and follows the device until a choice is made. */
export function initTheme() {
  chosen = remembered()
  apply()
  systemDark().addEventListener('change', () => {
    if (!chosen) apply()
  })
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore((listener) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }, currentTheme)
  return [theme, () => setTheme(theme === 'dark' ? 'light' : 'dark')]
}
