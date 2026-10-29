let displayZone: string | undefined

/** Zone used when a time has no location of its own; set from the organization settings. */
export function setDisplayTimeZone(zone: string | undefined) {
  displayZone = zone
}

export function fmtDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return '-'
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: timeZone ?? displayZone }).format(new Date(iso))
}

export function fmtTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return '-'
  return new Intl.DateTimeFormat('en-GB', { timeStyle: 'short', timeZone: timeZone ?? displayZone }).format(new Date(iso))
}

/** Formats a plain YYYY-MM-DD date without applying any timezone shift. */
export function fmtDate(day: string | null | undefined): string {
  if (!day) return '-'
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${day}T00:00:00Z`))
}

export function hoursMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '-'
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export function label(value: string): string {
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Up to two capital letters from a person's name, for an avatar. */
export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('')

export function todayIso(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

export function weekRange(day: string): { from: string; to: string } {
  const date = new Date(`${day}T00:00:00Z`)
  const offset = (date.getUTCDay() + 6) % 7
  const monday = new Date(date.getTime() - offset * 86400000)
  const sunday = new Date(monday.getTime() + 6 * 86400000)
  return { from: monday.toISOString().slice(0, 10), to: sunday.toISOString().slice(0, 10) }
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Weekdays (0 is Monday, sorted) as Every day, a run such as Mon-Fri, or the days listed. */
export function weekdaysText(days: number[]): string {
  if (days.length === 7) return 'Every day'
  const parts: string[] = []
  for (let i = 0; i < days.length; ) {
    let j = i
    while (j + 1 < days.length && days[j + 1] === days[j] + 1) j++
    parts.push(j - i >= 2 ? `${WEEKDAYS[days[i]]}-${WEEKDAYS[days[j]]}` : days.slice(i, j + 1).map((d) => WEEKDAYS[d]).join(', '))
    i = j + 1
  }
  return parts.join(', ')
}
