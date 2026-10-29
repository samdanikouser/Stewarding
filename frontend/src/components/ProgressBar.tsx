/** A thin bar showing how far along something is, with the figure available to screen readers. */
export function ProgressBar({ percent, label, tone = 'brand' }: { percent: number; label: string; tone?: 'brand' | 'ok' }) {
  const width = Math.min(100, Math.max(0, percent))
  return (
    <div role="progressbar" aria-valuenow={width} aria-valuemin={0} aria-valuemax={100} aria-label={label} className="h-2 w-full overflow-hidden rounded-full bg-surface-muted">
      <div className={`h-full rounded-full transition-[width] duration-500 ${tone === 'ok' ? 'bg-ok' : 'bg-brand'}`} style={{ width: `${width}%` }} />
    </div>
  )
}
