import { useEffect } from 'react'
import { Select } from '@/components/ui/select'
import { useAuth } from '@/lib/auth'

interface LocationSelectProps {
  value: number | null
  onChange: (id: number | null) => void
  allowAll?: boolean
  preferred?: number[]
  className?: string
}

export function LocationSelect({ value, onChange, allowAll = false, preferred = [], className = 'w-auto min-w-44' }: LocationSelectProps) {
  const { me } = useAuth()
  const locations = [...(me?.locations ?? [])].sort((a, b) => Number(preferred.includes(b.id)) - Number(preferred.includes(a.id)))

  const firstId = locations[0]?.id
  useEffect(() => {
    if (value === null && !allowAll && firstId !== undefined) onChange(firstId)
  }, [value, allowAll, firstId, onChange])

  return (
    <Select
      aria-label="Location"
      className={className}
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
    >
      {allowAll && <option value="">All locations</option>}
      {locations.map((location) => (
        <option key={location.id} value={location.id}>
          {location.name}{preferred.includes(location.id) ? ' (rostered today)' : ''}
        </option>
      ))}
    </Select>
  )
}
