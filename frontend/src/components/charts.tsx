import { cn } from '@/lib/utils'

export function BarList({ items, unit = '%' }: { items: { label: string; value: number | null; sub?: string }[]; unit?: string }) {
  if (items.length === 0) return <p className="py-6 text-center text-sm text-ink-muted">No data for this selection.</p>
  return (
    <ul className="space-y-3">
      {items.map((item) => {
        const value = item.value ?? 0
        const tone = item.value === null ? 'bg-border' : item.value >= 90 ? 'bg-ok' : item.value >= 70 ? 'bg-warn' : 'bg-danger'
        return (
          <li key={item.label}>
            <div className="flex justify-between gap-2 text-sm">
              <span className="truncate font-medium">{item.label}</span>
              <span className="tabular-nums text-ink-muted">{item.value === null ? 'n/a' : `${item.value}${unit}`}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded bg-surface-muted" role="img" aria-label={`${item.label} ${item.value ?? 'no data'}${unit}`}>
              <div className={cn('h-full rounded', tone)} style={{ width: `${Math.min(value, 100)}%` }} />
            </div>
            {item.sub && <p className="mt-0.5 text-xs text-ink-muted">{item.sub}</p>}
          </li>
        )
      })}
    </ul>
  )
}

interface Series {
  key: string
  label: string
  className: string
}

interface ColumnChartProps {
  data: Record<string, string | number>[]
  labelKey: string
  series: Series[]
  height?: number
}

export function ColumnChart({ data, labelKey, series, height = 140 }: ColumnChartProps) {
  const max = Math.max(1, ...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0)))
  return (
    <div>
      <div className="flex items-end gap-1 overflow-x-auto" style={{ height }} role="img"
        aria-label={`${series.map((s) => s.label).join(' and ')} by ${labelKey}`}>
        {data.map((d) => (
          <div key={String(d[labelKey])} className="flex h-full min-w-0 flex-1 items-end justify-center gap-0.5"
            title={`${d[labelKey]}: ${series.map((s) => `${s.label} ${d[s.key]}`).join(', ')}`}>
            {series.map((s) => (
              <div key={s.key} className={cn('w-full max-w-4 rounded-t', s.className)}
                style={{ height: `${((Number(d[s.key]) || 0) / max) * 100}%`, minHeight: Number(d[s.key]) ? 2 : 0 }} />
            ))}
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1 text-[10px] text-ink-muted">
        {data.map((d, i) => (
          <span key={String(d[labelKey])} className="min-w-0 flex-1 truncate text-center">
            {data.length > 10 && i % 2 === 1 ? '' : String(d[labelKey]).slice(-5)}
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink-muted">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1"><span className={cn('inline-block h-2 w-2 rounded-sm', s.className)} />{s.label}</span>
        ))}
      </div>
    </div>
  )
}

export function TrendLine({ points }: { points: { label: string; value: number | null }[] }) {
  const width = 300
  const height = 100
  const step = points.length > 1 ? width / (points.length - 1) : 0
  const known = points.map((p, i) => (p.value === null ? null : { x: i * step, y: height - (p.value / 100) * height, p }))
  const path = known.filter((k) => k !== null).map((k) => `${k.x},${k.y}`).join(' ')
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-28 w-full" role="img"
        aria-label={`Completion trend, ${points.filter((p) => p.value !== null).length} days with data`}>
        {[0, 50, 100].map((g) => <line key={g} x1={0} x2={width} y1={height - g} y2={height - g} className="stroke-border" strokeWidth={0.5} />)}
        {path && <polyline points={path} fill="none" className="stroke-brand" strokeWidth={2} strokeLinejoin="round" />}
        {known.map((k) => k && <circle key={k.p.label} cx={k.x} cy={k.y} r={2.5} className="fill-brand"><title>{`${k.p.label}: ${k.p.value}%`}</title></circle>)}
      </svg>
      <div className="flex justify-between text-[10px] text-ink-muted">
        <span>{points[0]?.label.slice(-5)}</span>
        <span>{points[points.length - 1]?.label.slice(-5)}</span>
      </div>
    </div>
  )
}

/** Horizontal bars sized against the largest value, for counts of units rather than percentages. */
export function QuantityBars({ items, unit = '' }: { items: { label: string; value: number; sub?: string }[]; unit?: string }) {
  if (items.length === 0) return <p className="py-6 text-center text-sm text-ink-muted">Nothing recorded for this selection.</p>
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.label}>
          <div className="flex justify-between gap-2 text-sm">
            <span className="truncate font-medium">{item.label}</span>
            <span className="tabular-nums text-ink-muted">{item.value}{unit}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded bg-surface-muted" role="img" aria-label={`${item.label} ${item.value}${unit}`}>
            <div className="h-full rounded bg-brand" style={{ width: `${(item.value / max) * 100}%` }} />
          </div>
          {item.sub && <p className="mt-0.5 text-xs text-ink-muted">{item.sub}</p>}
        </li>
      ))}
    </ul>
  )
}

/** A line of prices over time, scaled between the lowest and highest price so small moves are visible; hover a point for its details. */
export function PriceLine({ points, format }: { points: { label: string; value: number; sub?: string }[]; format: (n: number) => string }) {
  if (points.length === 0) return <p className="py-6 text-center text-sm text-ink-muted">No priced invoices for this item yet.</p>
  const width = 320
  const height = 120
  const pad = 8
  const low = Math.min(...points.map((p) => p.value))
  const high = Math.max(...points.map((p) => p.value))
  const span = high - low || 1
  const step = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0
  const at = (p: { value: number }, i: number) => ({ x: points.length > 1 ? pad + i * step : width / 2, y: pad + (1 - (p.value - low) / span) * (height - pad * 2) })
  const line = points.map((p, i) => { const { x, y } = at(p, i); return `${x},${y}` }).join(' ')
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-36 w-full" role="img" aria-label={`Price from ${format(points[0].value)} to ${format(points[points.length - 1].value)} over ${points.length} invoices`}>
        {[0, 0.5, 1].map((g) => <line key={g} x1={0} x2={width} y1={pad + g * (height - pad * 2)} y2={pad + g * (height - pad * 2)} className="stroke-border" strokeWidth={0.5} />)}
        {points.length > 1 && <polyline points={line} fill="none" className="stroke-brand" strokeWidth={2} strokeLinejoin="round" />}
        {points.map((p, i) => { const { x, y } = at(p, i); return <circle key={`${p.label}-${i}`} cx={x} cy={y} r={3.5} className="fill-brand"><title>{`${p.label}: ${format(p.value)}${p.sub ? ` (${p.sub})` : ''}`}</title></circle> })}
      </svg>
      <div className="flex justify-between text-[11px] text-ink-muted">
        <span>{points[0].label}</span><span>High {format(high)} - Low {format(low)}</span><span>{points[points.length - 1].label}</span>
      </div>
    </div>
  )
}
