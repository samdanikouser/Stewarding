export type ExtraFilter = 'employee' | 'frequency' | 'monitoringPoint' | 'supplier' | 'movement' | 'item' | 'status' | 'foodGroup' | 'monitoringType' | 'checklist'

export interface ReportDef {
  key: string
  title: string
  section: string
  filters: ExtraFilter[]
  statuses?: [string, string][]
  summary?: boolean
}

export const REPORTS: ReportDef[] = [
  { key: 'attendance', title: 'Attendance', section: 'People', filters: ['employee', 'status'],
    statuses: [['present', 'Present'], ['late', 'Late'], ['absent', 'Absent'], ['leave', 'On leave'], ['week_off', 'Week off']] },
  { key: 'attendance_sheet', title: 'Employee attendance sheet', section: 'People', filters: ['employee'] },
  { key: 'checklist_chart', title: 'Checklist completion chart', section: 'Checklists', filters: ['checklist', 'frequency'] },
  { key: 'checklists', title: 'Checklist record', section: 'Checklists', filters: ['checklist', 'frequency', 'employee', 'status'],
    statuses: [['pending', 'Not done'], ['completed', 'Done'], ['pending_verification', 'Awaiting approval'], ['verified', 'Approved'], ['failed', 'Rejected'], ['waived', 'Waived']] },
  { key: 'monitoring', title: 'Monitoring record', section: 'Food safety', filters: ['monitoringType', 'monitoringPoint', 'status'],
    statuses: [['failed', 'Failed'], ['passed', 'Passed'], ['awaiting', 'Awaiting approval']] },
  { key: 'lots', title: 'Lot register', section: 'Food safety', filters: ['supplier', 'foodGroup', 'status'],
    statuses: [['active', 'Active'], ['on_hold', 'On hold'], ['used_up', 'Used up'], ['discarded', 'Discarded']] },
  { key: 'receipts', title: 'Receipts and invoices', section: 'Stock', filters: ['supplier'] },
  { key: 'movements', title: 'Stock issues and movements', section: 'Stock', filters: ['movement', 'item'] },
  { key: 'stock_cost', title: 'Stock cost report', section: 'Stock', filters: [] },
  { key: 'stock_cost_category', title: 'Stock cost by category', section: 'Stock', filters: [] },
  { key: 'inventory_detail', title: 'Detailed inventory report (by location and item)', section: 'Stock', filters: [] },
  { key: 'summary', title: 'Operations summary', section: 'Overview', filters: [], summary: true },
]

export const FOOD_GROUPS = [
  ['poultry', 'Poultry'], ['red_meat', 'Red meat'], ['seafood', 'Seafood'], ['dairy', 'Dairy'], ['eggs', 'Eggs'], ['other', 'Other'],
]

export const SECTIONS = ['People', 'Checklists', 'Food safety', 'Stock', 'Overview']

export const MOVEMENTS = [
  ['receipts', 'Receipts'], ['issues', 'Issues'], ['returns', 'Returns'], ['transfers', 'Transfers'],
  ['breakage', 'Breakage and damage'], ['adjustments', 'Adjustments'], ['opening', 'Opening stock'],
]
