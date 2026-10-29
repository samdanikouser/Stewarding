import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CourseSummary } from '@/lib/training'
import { ToastProvider } from '@/lib/toast'
import { TrainingPage } from '@/pages/training/TrainingPage'

const mocks = vi.hoisted(() => ({ items: [] as unknown[], canManage: false }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ me: { permissions: mocks.canManage ? ['settings.manage'] : [] } }) }))
vi.mock('@/lib/useApi', () => ({ useApi: () => ({ data: { items: mocks.items }, loading: false, reload: vi.fn() }) }))

const course = (over: Partial<CourseSummary>): CourseSummary => ({
  assignment_id: 1, course_id: 1, title: 'Food Safety Basics', description: 'Start here', category: 'Food safety', lessons: 6, done: 0, percent: 0,
  status: 'not_started', overdue: false, due_on: null, assigned_at: '2026-03-01T08:00:00', started_at: null, completed_at: null, score: null, certificate: false, ...over,
})

describe('TrainingPage', () => {
  beforeEach(() => {
    mocks.canManage = false
    mocks.items = []
  })

  it('says so when nothing has been assigned', () => {
    render(<ToastProvider><MemoryRouter><TrainingPage /></MemoryRouter></ToastProvider>)
    expect(screen.getByText('No training has been assigned to you yet')).toBeTruthy()
  })

  it('lists what is left to do with a way in, and what is finished with its certificate', () => {
    mocks.items = [
      course({ assignment_id: 5, status: 'in_progress', done: 2, percent: 33, due_on: '2026-03-20' }),
      course({ assignment_id: 6, course_id: 2, title: 'Fire Safety', status: 'completed', done: 3, lessons: 3, percent: 100, completed_at: '2026-02-10T09:00:00', score: 90, certificate: true }),
    ]
    render(<ToastProvider><MemoryRouter><TrainingPage /></MemoryRouter></ToastProvider>)
    expect(screen.getByRole('link', { name: /Continue/ }).getAttribute('href')).toBe('/training/5')
    expect(screen.getByRole('link', { name: /Review/ }).getAttribute('href')).toBe('/training/6')
    expect(screen.getByRole('button', { name: /Certificate/ })).toBeTruthy()
    expect(screen.getByText('2 of 6 lessons')).toBeTruthy()
    expect(screen.getAllByRole('progressbar')).toHaveLength(2)
  })

  it('marks a course past its due date as overdue', () => {
    mocks.items = [course({ status: 'not_started', overdue: true, due_on: '2026-02-01' })]
    render(<ToastProvider><MemoryRouter><TrainingPage /></MemoryRouter></ToastProvider>)
    expect(screen.getByText('Overdue')).toBeTruthy()
    expect(screen.getByText(/Was due/)).toBeTruthy()
  })

  it('links managers to the training settings and shows nobody else the link', () => {
    mocks.canManage = true
    const { unmount } = render(<ToastProvider><MemoryRouter><TrainingPage /></MemoryRouter></ToastProvider>)
    expect(screen.getByRole('link', { name: /Manage training/ }).getAttribute('href')).toBe('/settings/training-courses')
    unmount()
    mocks.canManage = false
    render(<ToastProvider><MemoryRouter><TrainingPage /></MemoryRouter></ToastProvider>)
    expect(screen.queryByRole('link', { name: /Manage training/ })).toBeNull()
  })
})
