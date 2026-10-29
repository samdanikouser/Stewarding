import { Badge } from '@/components/ui/badge'
import { label } from '@/lib/format'

const OK = new Set(['completed', 'verified', 'passed', 'active', 'operational', 'approved', 'resolved', 'on_duty', 'received'])
const WARN = new Set(['in_progress', 'pending_verification', 'requested', 'pending', 'reported', 'reviewed', 'open', 'waived', 'high', 'retest_due'])
const CRITICAL = new Set(['overdue', 'failed', 'inactive', 'rejected', 'critical', 'out_of_service', 'escalated', 'missing'])

export function StatusBadge({ status }: { status: string }) {
  const tone = OK.has(status) ? 'ok' : WARN.has(status) ? 'warn' : CRITICAL.has(status) ? 'critical' : 'neutral'
  return (
    <Badge tone={tone}>{label(status)}</Badge>
  )
}
