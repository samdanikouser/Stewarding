import {
  ArrowLeftRight, Bell, CalendarDays, ChartColumn, ClipboardCheck, Clock, GraduationCap, LayoutDashboard, LogIn, Package,
  Menu, Moon, PanelLeftClose, PanelLeftOpen, QrCode, ScrollText, Settings, Sun, Thermometer, TriangleAlert, Users, Wrench, X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { BrandMark } from '@/components/BrandMark'
import { NotificationBell } from '@/components/NotificationBell'
import { Button } from '@/components/ui/button'
import { UserMenu } from '@/components/UserMenu'
import { useAuth } from '@/lib/auth'
import { APP_NAME } from '@/lib/brand'
import { setDisplayTimeZone } from '@/lib/format'
import { useTheme } from '@/lib/theme'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { setCurrency } from '@/lib/money'
import { ErrorBoundary } from '@/components/ErrorBoundary'

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboard,
  employees: Users,
  'check-in': LogIn,
  'my-schedule': CalendarDays,
  attendance: Clock,
  roster: CalendarDays,
  checklists: ClipboardCheck,
  monitoring: Thermometer,
  equipment: Wrench,
  inventory: Package,
  'stock-movements': ArrowLeftRight,
  breakage: TriangleAlert,
  traceability: QrCode,
  training: GraduationCap,
  tasks: Bell,
  reports: ChartColumn,
  settings: Settings,
  audit: ScrollText,
}

const GROUPS: { title: string; keys: string[] }[] = [
  { title: 'Overview', keys: ['dashboard', 'tasks'] },
  { title: 'People', keys: ['check-in', 'my-schedule', 'employees', 'attendance', 'roster', 'training'] },
  { title: 'Daily operations', keys: ['checklists'] },
  { title: 'Food safety', keys: ['monitoring', 'traceability'] },
  { title: 'Stock', keys: ['inventory', 'stock-movements', 'breakage'] },
  { title: 'Insights and admin', keys: ['reports', 'settings', 'audit'] },
]

// monitoring setup is edited under Settings
const IN_SETTINGS = ['equipment']

export function AppLayout() {
  const { me } = useAuth()
  const [theme, toggleTheme] = useTheme()
  const { pathname } = useLocation()
  const org = useApi<{ name: string; logo: string | null; timezone: string; currency: string }>('/organization')
  const reloadOrg = org.reload
  setDisplayTimeZone(org.data?.timezone)
  const currency = org.data?.currency
  useEffect(() => setCurrency(currency), [currency])
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  useEffect(() => {
    window.addEventListener('organization-changed', reloadOrg)
    return () => window.removeEventListener('organization-changed', reloadOrg)
  }, [reloadOrg])
  const [open, setOpen] = useState(false)
  // on wide screens the menu can be hidden to give the page the whole width; the choice is remembered on this device
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem('menu-hidden') === '1' } catch { return false } })
  const toggleMenu = () => setHidden((h) => { try { localStorage.setItem('menu-hidden', h ? '0' : '1') } catch { /* private mode */ } return !h })
  if (!me) return null

  const known = new Set([...GROUPS.flatMap((g) => g.keys), ...IN_SETTINGS])
  const groups = [...GROUPS, { title: 'More', keys: me.modules.map((m) => m.key).filter((k) => !known.has(k)) }]
    .map(({ title, keys }) => ({ title, modules: keys.flatMap((k) => me.modules.filter((m) => m.key === k)) }))
    .filter((g) => g.modules.length > 0)
  const current = me.modules.find(({ key }) => (key === 'dashboard' ? pathname === '/' : pathname === `/${key}` || pathname.startsWith(`/${key}/`)))

  return (
    <div className={cn('min-h-screen lg:grid lg:gap-2 lg:p-3', hidden ? 'lg:grid-cols-[1fr]' : 'lg:grid-cols-[17.5rem_1fr]')}>
      <aside
        className={cn(
          hidden && 'lg:hidden',
          'fixed inset-y-0 left-0 z-30 flex w-72 flex-col bg-side text-white transition-transform lg:sticky lg:top-3 lg:h-[calc(100vh-1.5rem)] lg:w-auto lg:translate-x-0 lg:rounded-2xl',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center justify-between px-5">
          <BrandMark organization={org.data?.name ?? ''} hasLogo={!!org.data?.logo} inverse />
          <Button variant="ghost" size="icon" className="text-white hover:bg-white/10 lg:hidden" aria-label="Close menu" onClick={() => setOpen(false)}>
            <X className="h-5 w-5" />
          </Button>
        </div>
        <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pb-4">
          {groups.map(({ title, modules }) => (
            <div key={title} role="group" aria-label={title} className="space-y-0.5">
              <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-white/40">{title}</p>
              {modules.map(({ key, label }) => {
            const Icon = ICONS[key] ?? LayoutDashboard
            return (
              <NavLink
                key={key}
                to={key === 'dashboard' ? '/' : `/${key}`}
                end={key === 'dashboard'}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-xl px-3 py-1.5 text-sm transition-colors',
                    isActive ? 'bg-white/12 font-medium text-white' : 'text-white/65 hover:bg-white/8 hover:text-white',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={cn('flex h-7 w-7 items-center justify-center rounded-lg', isActive ? 'bg-brand text-brand-ink' : 'bg-white/8')}>
                      <Icon className="h-4 w-4 shrink-0" aria-hidden />
                    </span>
                    {label}
                  </>
                )}
              </NavLink>
            )
              })}
            </div>
          ))}
        </nav>
        <UserMenu onNavigate={() => setOpen(false)} />
      </aside>
      {open && <div className="scrim fixed inset-0 z-20 lg:hidden" onClick={() => setOpen(false)} aria-hidden />}

      <div className="flex min-w-0 flex-col">
        <header className="glass sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b border-border/60 px-4 lg:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
          <Button variant="ghost" size="icon" className="hidden lg:inline-flex" aria-label={hidden ? 'Show the menu' : 'Hide the menu'} onClick={toggleMenu}>
            {hidden ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
          </Button>
          <nav aria-label="Breadcrumb" className="hidden text-sm text-ink-muted sm:block">
            {APP_NAME} <span aria-hidden>/</span> <span className="font-medium text-ink">{pathname.startsWith('/account') ? 'My profile' : current?.label ?? 'Home'}</span>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="icon" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={toggleTheme}>
              {theme === 'dark' ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
            </Button>
            <NotificationBell />
          </div>
        </header>
        <main className={cn('mx-auto w-full flex-1 px-4 pb-8 lg:px-6', hidden ? 'max-w-none lg:px-10' : 'max-w-[1400px]')}>
          <ErrorBoundary key={pathname}><Outlet /></ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
