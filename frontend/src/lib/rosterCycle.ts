const EPOCH = Date.UTC(2020, 0, 6)
const DAY = 86_400_000
const WEEK = 7 * DAY

const mondayOf = (iso: string) => {
  const day = new Date(`${iso}T00:00:00Z`)
  return day.getTime() - ((day.getUTCDay() + 6) % 7) * DAY
}

const mod = (a: number, n: number) => ((a % n) + n) % n

/** The week of a roster cycle, counted from the same Monday the server counts from. */
export const weekIndex = (iso: string) => Math.floor((mondayOf(iso) - EPOCH) / WEEK)

/** The cycle week stored for an assignment that starts `offset` weeks after the week of `iso`. */
export const cycleWeek = (iso: string, weeks: number, offset: number) => mod(weekIndex(iso) + offset, weeks)

/** How many weeks after the week of `iso` an assignment in `week` of the cycle first applies. */
export const cycleOffset = (iso: string, weeks: number, week: number) => mod(week - weekIndex(iso), weeks)

/** The Monday, as an ISO date, of the first week on or after the week of `iso` that falls in `week` of the cycle. */
export function cycleStart(iso: string, weeks: number, week: number): string {
  return new Date(mondayOf(iso) + cycleOffset(iso, weeks, week) * WEEK).toISOString().slice(0, 10)
}
