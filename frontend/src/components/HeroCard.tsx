import type { ReactNode } from 'react'

interface HeroCardProps {
  title: string
  eyebrow?: string
  chips?: { label: string; urgent?: boolean }[]
  children?: ReactNode
}

/** The gradient greeting card at the top of a dashboard, with short facts as pills. */
export function HeroCard({ title, eyebrow, chips = [], children }: HeroCardProps) {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-hero-a to-hero-b p-6 text-white shadow-lg shadow-hero-b/30">
      <div className="relative space-y-1">
        {eyebrow && <p className="text-xs font-medium uppercase tracking-wide text-white/70">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold">{title}</h1>
      </div>
      {chips.length > 0 && (
        <ul className="relative mt-4 flex flex-wrap gap-2">
          {chips.map((c) => (
            <li key={c.label} className={c.urgent ? 'rounded-full bg-white px-3 py-1 text-xs font-semibold text-hero-alert' : 'rounded-full bg-white/15 px-3 py-1 text-xs font-medium'}>{c.label}</li>
          ))}
        </ul>
      )}
      {children && <div className="relative mt-4">{children}</div>}
    </section>
  )
}

export function greeting(now = new Date()): string {
  const hour = now.getHours()
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
}
