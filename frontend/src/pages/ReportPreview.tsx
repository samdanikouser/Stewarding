import { Check, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { EmptyState, Table, Td, Th } from '@/components/ui/table'

type Cell = string | number | null | { s: 'ok' | 'pending' | 'fail' | 'waived' | 'na'; by?: string; ver?: string }

export interface RecordGroup {
  title: string
  layout?: string
  legend?: string
  meta: [string, string][]
  columns: [string, string][]
  rows: Record<string, Cell>[]
  row_count?: number
  totals: [string, string | number][]
}

export interface RecordDoc {
  title: string
  period: { label: string }
  locations: string[]
  groups: RecordGroup[]
}

const PREVIEW_ROWS = 25

function Mark({ cell }: { cell: Cell }) {
  if (cell === null || typeof cell !== 'object') return <>{cell ?? '-'}</>
  const who = [cell.by, cell.ver].filter(Boolean).join('/')
  if (cell.s === 'ok' || cell.s === 'pending') {
    return (
      <span className="flex flex-col items-center" title={who}>
        <Check className={`h-4 w-4 ${cell.s === 'ok' ? 'text-ok' : 'text-warn'}`} aria-label={cell.s === 'ok' ? 'Done and approved' : 'Done, awaiting approval'} />
        <span className="text-[10px] text-ink-muted">{who}</span>
      </span>
    )
  }
  if (cell.s === 'fail') return <X className="mx-auto h-4 w-4 text-danger" aria-label="Not done or rejected" />
  return <span className="block text-center text-ink-muted">{cell.s === 'waived' ? 'W' : '-'}</span>
}

export function ReportPreview({ doc }: { doc: RecordDoc }) {
  if (doc.groups.length === 0) return <EmptyState title="Nothing recorded for these filters" />
  return (
    <div className="space-y-3">
      {doc.groups.map((group) => {
        const chart = group.layout === 'chart'
        return (
          <details key={group.title} open className="rounded-lg border border-border bg-surface">
            <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3 font-medium">
              {group.title}
              <span className="flex flex-wrap gap-1">{group.totals.map(([label, value]) => <Badge key={label}>{label}: {String(value)}</Badge>)}</span>
            </summary>
            <div className="space-y-2 px-4 pb-4">
              {chart && <p className="text-xs text-ink-muted">{group.legend}</p>}
              {group.meta.find(([label]) => label === 'Initials') && <p className="text-xs text-ink-muted">{group.meta.find(([label]) => label === 'Initials')?.[1]}</p>}
              <Table>
                <thead><tr>{group.columns.map(([key, label]) => <Th key={key} className={chart && key !== "task" ? "whitespace-pre-line px-1 text-center" : undefined}>{label}</Th>)}</tr></thead>
                <tbody>
                  {group.rows.slice(0, PREVIEW_ROWS).map((row, i) => (
                    <tr key={i}>{group.columns.map(([key]) => <Td key={key} className={chart && key !== 'task' ? 'px-1' : undefined}><Mark cell={row[key]} /></Td>)}</tr>
                  ))}
                </tbody>
              </Table>
              {(group.row_count ?? group.rows.length) > PREVIEW_ROWS && (
                <p className="text-xs text-ink-muted">Showing {PREVIEW_ROWS} of {group.row_count ?? group.rows.length} rows. The download has them all.</p>
              )}
            </div>
          </details>
        )
      })}
    </div>
  )
}
