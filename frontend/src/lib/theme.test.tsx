import { act, fireEvent, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Modal } from '@/components/ui/modal'
import { initTheme, setTheme, useTheme } from '@/lib/theme'

const css = readFileSync(join(__dirname, '../index.css'), 'utf8')

function tokens(block: RegExp): Record<string, string> {
  const body = css.match(block)?.[1] ?? ''
  return Object.fromEntries([...body.matchAll(/--color-([a-z-]+):\s*(#[0-9a-f]{6});/gi)].map((m) => [m[1], m[2]]))
}

const light = tokens(/@theme\s*\{([^}]*)\}/)
const dark = { ...light, ...tokens(/:root\[data-theme='dark'\]\s*\{([^}]*)\}/) }

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

const ratio = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const TEXT_PAIRS = [
  ['ink', 'page'], ['ink', 'surface'], ['ink', 'surface-muted'], ['ink-muted', 'page'], ['ink-muted', 'surface'], ['ink-muted', 'surface-muted'],
  ['brand', 'surface'], ['brand', 'page'], ['brand', 'brand-soft'], ['brand-ink', 'brand'], ['brand-ink', 'brand-deep'],
  ['danger', 'danger-soft'], ['danger', 'surface'], ['danger-ink', 'danger'], ['warn', 'warn-soft'], ['warn', 'surface'], ['ok', 'ok-soft'], ['ok', 'surface'],
] as const

describe.each([['light', light], ['dark', dark]] as const)('%s theme contrast', (_name, palette) => {
  it.each(TEXT_PAIRS)('%s on %s reads at 4.5:1 or better', (front, back) => {
    expect(ratio(palette[front], palette[back])).toBeGreaterThanOrEqual(4.5)
  })

  it.each([['border-strong', 'surface'], ['border-strong', 'page']])('%s separates a control from %s at 3:1', (front, back) => {
    expect(ratio(palette[front], palette[back])).toBeGreaterThanOrEqual(3)
  })

  it('keeps the greeting banner readable with white text', () => {
    expect(ratio('#ffffff', palette['hero-a'])).toBeGreaterThanOrEqual(4.5)
    expect(ratio('#ffffff', palette['hero-b'])).toBeGreaterThanOrEqual(4.5)
    expect(ratio(palette['hero-alert'], '#ffffff')).toBeGreaterThanOrEqual(4.5)
  })
})

function deviceAsks(isDark: boolean) {
  vi.stubGlobal('matchMedia', () => ({ matches: isDark, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
}

function Switch() {
  const [theme, toggle] = useTheme()
  return <button onClick={toggle}>{theme}</button>
}

describe('theme switch', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('follows the device until someone chooses', () => {
    deviceAsks(true)
    initTheme()
    expect(document.documentElement.dataset.theme).toBe('dark')
    deviceAsks(false)
    initTheme()
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('remembers a choice over the device setting', () => {
    deviceAsks(true)
    localStorage.setItem('plato-theme', 'light')
    initTheme()
    expect(document.documentElement.dataset.theme).toBe('light')
    localStorage.setItem('plato-theme', 'nonsense')
    initTheme()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('switches from the button, saves the choice and keeps it when storage is blocked', () => {
    deviceAsks(false)
    initTheme()
    render(<Switch />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('button').textContent).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('plato-theme')).toBe('dark')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'QuotaExceededError')
    })
    act(() => setTheme('light'))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(screen.getByRole('button').textContent).toBe('light')
  })
})

const mixHex = (front: string, back: string, share: number) =>
  '#' + [1, 3, 5].map((i) => Math.round(parseInt(front.slice(i, i + 2), 16) * share + parseInt(back.slice(i, i + 2), 16) * (1 - share)).toString(16).padStart(2, '0')).join('')

describe('frosted surfaces', () => {
  const supported = css.slice(css.indexOf('@supports (backdrop-filter'), css.indexOf('@media (prefers-reduced-transparency'))
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-transparency'), css.indexOf('@keyframes toast-in'))

  it('starts from a solid colour and only blurs where the browser can', () => {
    expect(css).toMatch(/\.glass\s*\{\s*background:\s*var\(--color-page\);/)
    expect(css.indexOf('.glass {')).toBeLessThan(css.indexOf('@supports (backdrop-filter'))
    expect(supported).toContain('backdrop-filter: blur(14px)')
    expect(supported).toContain('backdrop-filter: blur(5px)')
  })

  it('turns the blur off and goes solid when transparency is reduced', () => {
    expect(reduced.match(/backdrop-filter:\s*none/g)).toHaveLength(2)
    expect(reduced).toContain('background: var(--color-page)')
  })

  it.each([['light', light, '#000000'], ['dark', dark, '#ffffff']] as const)('keeps secondary header text at 4.5:1 over the harshest %s backdrop', (_name, palette, harshest) => {
    const share = Number(supported.match(/var\(--color-page\) (\d+)%/)?.[1]) / 100
    expect(ratio(palette['ink-muted'], mixHex(palette.page, harshest, share))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(palette.ink, mixHex(palette.page, harshest, share))).toBeGreaterThanOrEqual(4.5)
  })

  it('puts the blurred scrim behind every dialog and keeps the dialog itself solid', () => {
    render(<Modal open title="Check" onClose={() => {}}>Body</Modal>)
    const dialog = screen.getByRole('dialog')
    expect(dialog.parentElement?.className).toContain('scrim')
    expect(dialog.className).toContain('bg-surface')
    expect(dialog.className).not.toContain('backdrop')
  })
})
