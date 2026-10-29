import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RequireModule } from '@/components/RequireModule'

const auth = vi.hoisted(() => ({ me: null as { modules: { key: string }[] } | null }))
vi.mock('@/lib/auth', () => ({ useAuth: () => auth }))

function visit(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route index element={<p>Dashboard</p>} />
        <Route path="settings" element={<RequireModule module="settings"><p>Settings page</p></RequireModule>} />
        <Route path="checklists" element={<RequireModule module="checklists"><p>Checklists page</p></RequireModule>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireModule', () => {
  beforeEach(() => {
    auth.me = { modules: [{ key: 'dashboard' }, { key: 'checklists' }] }
  })

  it('shows a page to a role that has the module', () => {
    visit('/checklists')
    expect(screen.getByText('Checklists page')).toBeTruthy()
  })

  it('sends a role without the module to the dashboard instead of showing the page', () => {
    visit('/settings')
    expect(screen.queryByText('Settings page')).toBeNull()
    expect(screen.getByText('Dashboard')).toBeTruthy()
  })

  it('sends someone who is not signed in to the dashboard route as well', () => {
    auth.me = null
    visit('/checklists')
    expect(screen.queryByText('Checklists page')).toBeNull()
    expect(screen.getByText('Dashboard')).toBeTruthy()
  })
})
