import { Bell } from 'lucide-react'
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { NOTIFICATIONS_CHANGED } from '@/lib/notificationEvents'
import { useApi } from '@/lib/useApi'

const POLL_MS = 30_000

export function NotificationBell() {
  const { data, reload } = useApi<{ unread: number; action_needed: number }>('/notifications/unread-count')

  useEffect(() => {
    const timer = setInterval(reload, POLL_MS)
    const refresh = () => document.visibilityState !== 'hidden' && reload()  // a tab that was in the background catches up as soon as it is looked at
    window.addEventListener(NOTIFICATIONS_CHANGED, reload)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      clearInterval(timer)
      window.removeEventListener(NOTIFICATIONS_CHANGED, reload)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [reload])

  const unread = data?.unread ?? 0
  const urgent = (data?.action_needed ?? 0) > 0
  return (
    <Link to="/tasks" aria-label={`Notifications, ${unread} unread${urgent ? ', action needed' : ''}`}
      className="relative inline-flex h-10 w-10 items-center justify-center rounded-md border border-border-strong hover:bg-surface-muted">
      <Bell className="h-4 w-4" aria-hidden />
      {unread > 0 && (
        <span className={`absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-xs font-semibold ${urgent ? 'bg-danger text-danger-ink' : 'bg-brand text-brand-ink'}`}>
          {unread > 99 ? '99+' : unread}
        </span>
      )}
    </Link>
  )
}
