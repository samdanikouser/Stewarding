import { useEffect, useState } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Field } from '@/components/ui/field'
import { Skeleton } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

interface Props {
  value: number | null
  onChange: (id: number | null) => void
  label?: string
  fill?: boolean
}

/** The location picker for people who work shifts: fixed to the one location they are rostered at today, with a link to pick another. */
export function WorkLocationSelect({ value, onChange, label, fill = false }: Props) {
  const { me } = useAuth()
  const status = useApi<{ rostered_today: { location_id: number; location_name: string; week_off: boolean }[] }>(
    me?.permissions.includes('attendance.self') ? '/attendance/me/status' : null)
  const [elsewhere, setElsewhere] = useState(false)
  const working = (status.data?.rostered_today ?? []).filter((r) => !r.week_off)
  const only = new Set(working.map((r) => r.location_id)).size === 1 ? working[0] : null
  const locked = only !== null && !elsewhere && (value === null || value === only.location_id)

  useEffect(() => {
    if (locked && value === null) onChange(only.location_id)
  }, [locked, value, only, onChange])

  const select = <LocationSelect className={fill ? 'w-full' : undefined} value={value} onChange={onChange} />
  if (status.loading) return <Skeleton className={cn('h-10', fill ? 'w-full' : 'w-44')} />
  if (!locked) return label ? <Field label={label}>{select}</Field> : select
  return (
    <div className="space-y-1.5">
      {label && <p className="text-sm font-medium">{label}</p>}
      <div className="flex flex-wrap items-center gap-x-3">
        <span className={cn('flex h-10 items-center rounded-lg border border-border bg-surface-muted px-3 text-sm font-medium', fill && 'flex-1')}>{only.location_name} (rostered today)</span>
        <button type="button" className="min-h-11 text-sm font-medium text-brand-deep hover:underline" onClick={() => setElsewhere(true)}>Viewing another location?</button>
      </div>
    </div>
  )
}
