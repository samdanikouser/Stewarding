import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationBell } from '@/components/NotificationBell'
import { notificationsChanged } from '@/lib/notificationEvents'

const mocks = vi.hoisted(() => ({ unread: 3, reload: vi.fn() }))
vi.mock('@/lib/useApi', () => ({
  useApi: () => ({ data: { unread: mocks.unread, action_needed: 0 }, reload: () => { mocks.unread = 2; mocks.reload() } }),
}))

describe('NotificationBell', () => {
  beforeEach(() => { mocks.unread = 3; mocks.reload.mockClear() })

  it('refreshes its count the moment notifications change, and when the window is looked at again', () => {
    render(<MemoryRouter><NotificationBell /></MemoryRouter>)
    expect(screen.getByLabelText(/3 unread/)).toBeTruthy()
    act(() => notificationsChanged())
    expect(mocks.reload).toHaveBeenCalledTimes(1)
    act(() => { window.dispatchEvent(new Event('focus')) })
    expect(mocks.reload).toHaveBeenCalledTimes(2)
  })
})
