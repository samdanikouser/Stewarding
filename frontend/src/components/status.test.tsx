import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KpiCard } from '@/components/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/ui/status-badge'

const icons = (element: HTMLElement) => element.querySelectorAll('svg[aria-hidden="true"]').length

describe('status never rests on colour alone', () => {
  it.each(['ok', 'warn', 'critical'] as const)('a %s badge carries an icon beside its words', (tone) => {
    render(<Badge tone={tone}>Some state</Badge>)
    const badge = screen.getByText('Some state')
    expect(icons(badge)).toBe(1)
  })

  it('leaves a neutral badge plain', () => {
    render(<Badge>Label</Badge>)
    expect(icons(screen.getByText('Label'))).toBe(0)
  })

  it('gives the status badge the icon of its tone and none for an unknown status', () => {
    render(<><StatusBadge status="failed" /><StatusBadge status="something_else" /></>)
    expect(icons(screen.getByText('Failed'))).toBe(1)
    expect(icons(screen.getByText('Something else'))).toBe(0)
  })

  it('names the tone of a figure for screen readers and marks it with an icon', () => {
    const { container } = render(<><KpiCard label="Overdue" value={4} tone="critical" /><KpiCard label="Held" value={2} tone="warn" /><KpiCard label="Done" value={9} tone="ok" /><KpiCard label="Plain" value={1} /></>)
    expect(container.querySelectorAll('.sr-only')).toHaveLength(3)
    expect(screen.getByText('Critical:')).toBeTruthy()
    expect(screen.getByText('Needs attention:')).toBeTruthy()
    expect(screen.getByText('On track:')).toBeTruthy()
    const plain = screen.getByText('Plain').parentElement?.parentElement as HTMLElement
    expect(plain.querySelector('.sr-only')).toBeNull()
  })
})

describe('touch sizing and control borders', () => {
  it('grows buttons to a 44 px target on a touch screen only', () => {
    render(<><Button>Save</Button><Button size="sm">Small</Button><Button size="icon" aria-label="Icon" /></>)
    expect(screen.getByText('Save').className).toContain('h-10')
    expect(screen.getByText('Save').className).toContain('pointer-coarse:h-11')
    expect(screen.getByText('Small').className).toContain('pointer-coarse:h-10')
    expect(screen.getByLabelText('Icon').className).toContain('pointer-coarse:w-11')
  })

  it('draws a form control with the strong border', () => {
    render(<Input aria-label="Name" />)
    expect(screen.getByLabelText('Name').className).toContain('border-border-strong')
    expect(screen.getByLabelText('Name').className).toContain('pointer-coarse:h-11')
  })
})
