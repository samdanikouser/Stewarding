export type RulesSection = 'attendance' | 'monitoring-rules' | 'qr-codes' | 'approvals' | 'breakage' | 'receiving'

export interface SettingDef {
  key: string
  section: RulesSection
  kind: 'toggle' | 'number'
  label: string
  unit?: string
}

export const SECTION_TITLES: Record<RulesSection, string> = {
  attendance: 'Check-in and attendance rules',
  'monitoring-rules': 'Monitoring rules',
  'qr-codes': 'QR codes',
  approvals: 'Approvals and escalation',
  breakage: 'Breakage approval',
  receiving: 'Receiving',
}

export const SETTINGS: SettingDef[] = [
  { key: 'attendance.face_required', section: 'attendance', kind: 'toggle', label: 'Require face verification to check in and out' },
  { key: 'attendance.face_liveness', section: 'attendance', kind: 'toggle', label: 'Live head-turn check, with a snapshot kept' },
  { key: 'attendance.by_location', section: 'attendance', kind: 'toggle', label: 'Staff choose a location to check in, and attendance is shown by location' },
  { key: 'attendance.missed_checkout_after_shift_hours', section: 'attendance', kind: 'number', label: 'Not checked out: alert this long after the shift ends', unit: 'hours' },
  { key: 'attendance.missed_checkout_hours', section: 'attendance', kind: 'number', label: 'Missed check-out after (only when there is no shift)', unit: 'hours' },
  { key: 'attendance.max_accuracy_m', section: 'attendance', kind: 'number', label: 'Largest location error accepted', unit: 'metres' },
  { key: 'attendance.snapshot_days', section: 'attendance', kind: 'number', label: 'Keep face snapshots for (0 = keep them)', unit: 'days' },
  { key: 'attendance.face_match_max', section: 'attendance', kind: 'number', label: 'Face match limit (lower is stricter)', unit: '10 to 80' },

  { key: 'temp.due_grace_minutes', section: 'monitoring-rules', kind: 'number', label: 'Grace period for a due check', unit: 'minutes' },
  { key: 'temp.retest_minutes', section: 'monitoring-rules', kind: 'number', label: 'Retest due after corrective action', unit: 'minutes' },
  { key: 'temp.escalate_after_minutes', section: 'monitoring-rules', kind: 'number', label: 'Escalate an unresolved failed check after', unit: 'minutes' },
  { key: 'temp.pending_alert_hours', section: 'monitoring-rules', kind: 'number', label: 'Warn when a time out is missing after (0 = never)', unit: 'hours' },
  { key: 'temp.repeat_failure_count', section: 'monitoring-rules', kind: 'number', label: 'Repeat-failure alert at', unit: 'failures' },
  { key: 'temp.repeat_failure_days', section: 'monitoring-rules', kind: 'number', label: 'Repeat-failure window', unit: 'days' },

  { key: 'scan.monitoring_required', section: 'qr-codes', kind: 'toggle', label: 'Scan the QR code of a monitoring point to record its checks' },
  { key: 'scan.checklists_required', section: 'qr-codes', kind: 'toggle', label: 'Scan the QR code of the location to complete its checklist tasks' },
  { key: 'scan.valid_minutes', section: 'qr-codes', kind: 'number', label: 'A scan stays valid for', unit: 'minutes' },

  { key: 'approval.checklists', section: 'approvals', kind: 'toggle', label: 'Every completed checklist task needs approval' },
  { key: 'reminder.lead_minutes', section: 'approvals', kind: 'number', label: 'Reminder before a deadline', unit: 'minutes' },
  { key: 'escalation.supervisor_after_minutes', section: 'approvals', kind: 'number', label: 'Escalate to supervisor after', unit: 'minutes overdue' },
  { key: 'checklist.grace_minutes', section: 'approvals', kind: 'number', label: 'Grace period before a task counts as overdue', unit: 'minutes' },
  { key: 'checklist.alert_priority', section: 'approvals', kind: 'number', label: 'Overdue alerts: 0 every task, 1 high and critical only, 2 critical only', unit: '0 to 2' },
  { key: 'escalation.manager_after_minutes', section: 'approvals', kind: 'number', label: 'Escalate to manager after', unit: 'minutes overdue' },

  { key: 'breakage.approval_qty', section: 'breakage', kind: 'number', label: 'Approval needed from this quantity', unit: 'units' },
  { key: 'breakage.approval_cost', section: 'breakage', kind: 'number', label: 'Approval needed from this estimated cost' },

  { key: 'stock.lock_through', section: 'receiving', kind: 'number', label: 'Lock stock figures up to this month (0 = no lock)', unit: 'YYYYMM, such as 202609' },
  { key: 'stock.round_tolerance_units', section: 'receiving', kind: 'number', label: 'Count rounds: normal counting error, at least', unit: 'units' },
  { key: 'stock.round_tolerance_percent', section: 'receiving', kind: 'number', label: 'Count rounds: or this share of the books if larger', unit: '%' },
  { key: 'receiving.allow_old_invoices', section: 'receiving', kind: 'toggle', label: 'Allow receiving against invoices older than two years' },
]
