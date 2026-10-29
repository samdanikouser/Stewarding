import { Boxes, CalendarClock, ClipboardCheck, ShieldCheck } from 'lucide-react'
import { APP_NAME } from '@/lib/brand'

const FEATURES = [
  { icon: ShieldCheck, title: 'Food-safety monitoring', text: 'Temperatures, checks and corrective actions, on record.' },
  { icon: ClipboardCheck, title: 'Checklists that get done', text: 'Daily and weekly tasks with sign-off and reminders.' },
  { icon: Boxes, title: 'Stock, receiving and transfers', text: 'Know what arrived, what it cost and where it went.' },
  { icon: CalendarClock, title: 'Attendance and rosters', text: 'Check-ins, shifts, leave and who is working where.' },
]

/** Paper-cut shapes in the logo's colours, drifting slowly behind the content. */
function Shapes({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="login-drift-a absolute -right-8 -top-12 h-32 w-32 rounded-[42%_58%_55%_45%/48%_44%_56%_52%] bg-[#f2b632] shadow-[0_14px_28px_rgba(0,0,0,0.28)]" />
        <div className="login-drift-b absolute right-14 -bottom-12 h-28 w-28 rounded-[55%_45%_40%_60%/50%_58%_42%_50%] bg-[#6dbfa6] shadow-[0_14px_28px_rgba(0,0,0,0.28)]" />
        <div className="login-drift-c absolute -bottom-6 -right-6 h-24 w-24 rounded-[48%_52%_60%_40%/44%_50%_50%_56%] bg-[#ee6a4a] shadow-[0_14px_28px_rgba(0,0,0,0.28)]" />
      </div>
    )
  }
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="login-drift-a absolute -left-24 -top-20 h-72 w-72 rounded-[42%_58%_55%_45%/48%_44%_56%_52%] bg-[#f2b632] opacity-95 shadow-[0_24px_50px_rgba(0,0,0,0.28)]" />
      <div className="login-drift-b absolute -right-20 top-1/4 h-80 w-80 rounded-[55%_45%_40%_60%/50%_58%_42%_50%] bg-[#6dbfa6] opacity-95 shadow-[0_24px_50px_rgba(0,0,0,0.28)]" />
      <div className="login-drift-c absolute -bottom-28 left-1/4 h-80 w-80 rounded-[48%_52%_60%_40%/44%_50%_50%_56%] bg-[#ee6a4a] opacity-95 shadow-[0_24px_50px_rgba(0,0,0,0.28)]" />
      <div className="login-drift-a absolute -bottom-10 -right-10 h-44 w-44 rounded-[50%_50%_45%_55%/55%_45%_55%_45%] bg-[#f2b632]/90 shadow-[0_18px_36px_rgba(0,0,0,0.25)]" />
    </div>
  )
}

/** The logo tile, floating, with a soft ring that keeps pulsing out from behind it. */
function LogoTile({ size }: { size: string }) {
  return (
    <div className={`relative ${size}`}>
      <span aria-hidden className="login-ring absolute inset-0 rounded-3xl border-2 border-white/40" />
      <span aria-hidden className="login-ring absolute inset-0 rounded-3xl border-2 border-white/30 [animation-delay:1.8s]" />
      <img src="/icon-512.png" alt="" className="login-float relative h-full w-full rounded-3xl shadow-[0_18px_40px_rgba(0,0,0,0.4)] ring-1 ring-white/25" />
    </div>
  )
}

/** The brand side of the sign-in page: a full panel on wide screens, a compact banner on phones. */
export function LoginHero({ variant }: { variant: 'panel' | 'banner' }) {
  if (variant === 'banner') {
    return (
      <div className="relative flex h-40 items-center gap-4 overflow-hidden bg-[linear-gradient(135deg,#1d3c5d,#0d2a47)] px-6 lg:hidden">
        <Shapes compact />
        <LogoTile size="h-16 w-16 shrink-0" />
        <div className="login-rise relative max-w-[10.5rem] text-white sm:max-w-xs">
          <p className="text-2xl font-semibold tracking-tight">{APP_NAME}</p>
          <p className="text-sm text-white/75">Run every outlet with confidence.</p>
        </div>
      </div>
    )
  }
  return (
    <div className="relative hidden overflow-hidden bg-[linear-gradient(145deg,#1d3c5d,#0d2a47)] text-white lg:flex lg:flex-col lg:justify-center lg:px-14 xl:px-20">
      <Shapes />
      <div className="relative z-10 max-w-lg">
        <LogoTile size="h-24 w-24" />
        <div className="login-rise mt-8 rounded-3xl bg-[#0d2a47]/85 p-6 ring-1 ring-white/10 backdrop-blur-sm [animation-delay:150ms]">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight xl:text-5xl">Run every outlet with confidence.</h2>
          <p className="mt-4 max-w-md text-base text-white/85">Food safety, stock and people in one place, so nothing slips between shifts.</p>
        </div>
        <ul className="mt-10 space-y-4">
          {FEATURES.map(({ icon: Icon, title, text }, i) => (
            <li key={title} className="login-rise flex items-start gap-4 rounded-2xl bg-[#0d2a47]/85 p-3 ring-1 ring-white/10 backdrop-blur-sm" style={{ animationDelay: `${380 + i * 120}ms` }}>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/12 ring-1 ring-white/15">
                <Icon aria-hidden className="h-5 w-5" />
              </span>
              <span>
                <span className="block text-sm font-semibold">{title}</span>
                <span className="block text-sm text-white/75">{text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
