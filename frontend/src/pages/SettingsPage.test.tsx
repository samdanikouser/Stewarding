import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SettingsPage } from '@/pages/SettingsPage'

vi.mock('@/pages/settings/SettingsRules', () => ({ SettingsRules: ({ section }: { section: string }) => <p>Rules {section} page</p> }))
vi.mock('@/pages/settings/SettingsInventoryLists', () => ({ SettingsInventoryLists: () => <p>Units page</p> }))
vi.mock('@/pages/settings/SettingsItems', () => ({ SettingsItems: () => <p>Items page</p> }))
vi.mock('@/pages/settings/SettingsLocations', () => ({ SettingsLocations: () => <p>Locations page</p> }))
vi.mock('@/pages/settings/SettingsLookups', () => ({ SettingsLookups: () => <p>Lists page</p> }))
vi.mock('@/pages/settings/SettingsMonitoring', () => ({ SettingsMonitoring: () => <p>Monitoring page</p> }))
vi.mock('@/pages/settings/SettingsOrganization', () => ({ SettingsOrganization: () => <p>Organization page</p> }))
vi.mock('@/pages/settings/SettingsRoles', () => ({ SettingsRoles: () => <p>Roles page</p> }))
vi.mock('@/pages/settings/SettingsShifts', () => ({ SettingsShifts: () => <p>Shifts page</p> }))
vi.mock('@/pages/settings/SettingsSuppliers', () => ({ SettingsSuppliers: () => <p>Suppliers page</p> }))

function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

function visit(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/:section" element={<SettingsPage />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  )
}

const where = () => screen.getByTestId('where').textContent

describe('SettingsPage', () => {
  it('opens the first section and shows the topics as tabs along the top', () => {
    visit('/settings')
    expect(where()).toBe('/settings/organization')
    expect(screen.getByText('Organization page')).toBeTruthy()
    const topics = screen.getByRole('navigation', { name: 'Settings topics' })
    expect(Array.from(topics.querySelectorAll('a')).map((a) => a.textContent)).toEqual(['Company', 'People', 'Food safety', 'Stock', 'Training', 'Lists'])
    expect(screen.getByRole('link', { name: 'Company' }).getAttribute('aria-current')).toBe('page')
  })

  it('shows the sections of the open topic as pills and marks the open one', () => {
    visit('/settings/roles')
    const pills = screen.getByRole('navigation', { name: 'Settings sections' })
    expect(Array.from(pills.querySelectorAll('a')).map((a) => a.textContent)).toEqual(['Check-in and attendance rules', 'Roles', 'Approvals and escalation'])
    expect(screen.getByRole('link', { name: 'Roles' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'People' }).getAttribute('aria-current')).toBe('page')
    expect(screen.queryByRole('link', { name: 'Monitoring setup' })).toBeNull()
    expect(screen.getByText('Roles page')).toBeTruthy()
  })

  it('takes a topic tab to the first section of that topic', () => {
    visit('/settings/roles')
    expect(screen.getByRole('link', { name: 'Food safety' }).getAttribute('href')).toBe('/settings/monitoring')
    expect(screen.getByRole('link', { name: 'Stock' }).getAttribute('href')).toBe('/settings/items')
  })

  it('sends an old ?tab= link to the clean address of that section', () => {
    visit('/settings?tab=monitoring')
    expect(where()).toBe('/settings/monitoring')
    expect(screen.getByText('Monitoring page')).toBeTruthy()
  })

  it('opens a rules topic as its own section', () => {
    visit('/settings/monitoring-rules')
    expect(screen.getByText('Rules monitoring-rules page')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Monitoring rules' }).getAttribute('aria-current')).toBe('page')
  })

  it('sends the old Rules & alerts address, as a path or a ?tab=, to the check-in and attendance rules', () => {
    visit('/settings/general')
    expect(where()).toBe('/settings/attendance')
    expect(screen.getByText('Rules attendance page')).toBeTruthy()
  })

  it('sends the old ?tab=general link to the check-in and attendance rules', () => {
    visit('/settings?tab=general')
    expect(where()).toBe('/settings/attendance')
  })

  it.each(['/settings/nope', '/settings?tab=nope', '/settings/constructor'])('opens the first section for %s', (path) => {
    visit(path)
    expect(where()).toBe('/settings/organization')
  })

  it('finds a rule by its words and opens the page it lives on', async () => {
    const user = userEvent.setup()
    visit('/settings/organization')
    const box = screen.getByRole('searchbox', { name: 'Search settings' })
    await user.type(box, 'grace')
    const hit = screen.getByRole('link', { name: /Grace period for a due check/ })
    expect(hit.textContent).toContain('Monitoring rules')
    await user.click(hit)
    expect(where()).toBe('/settings/monitoring-rules')
    expect((screen.getByRole('searchbox', { name: 'Search settings' }) as HTMLInputElement).value).toBe('')
    expect(screen.queryByRole('link', { name: /Grace period for a due check/ })).toBeNull()
  })

  it('finds the check-in rules however check in is written', async () => {
    const user = userEvent.setup()
    visit('/settings/organization')
    const box = screen.getByRole('searchbox', { name: 'Search settings' })
    for (const typed of ['check in', 'check-in', 'checkin', 'check out']) {
      await user.clear(box)
      await user.type(box, typed)
      expect(screen.getAllByRole('link').some((a) => a.getAttribute('href') === '/settings/attendance' && /check-?in|check-?out/i.test(a.textContent ?? '')), typed).toBe(true)
    }
  })

  it('finds a section by its name and says so when nothing matches', async () => {
    const user = userEvent.setup()
    visit('/settings/organization')
    const box = screen.getByRole('searchbox', { name: 'Search settings' })
    await user.type(box, 'suppl')
    const hits = screen.getAllByRole('link', { name: /Suppliers/ })
    expect(hits.some((a) => a.getAttribute('href') === '/settings/suppliers')).toBe(true)
    await user.clear(box)
    await user.type(box, 'zzzz')
    expect(screen.getByText('Nothing matches')).toBeTruthy()
  })
})
