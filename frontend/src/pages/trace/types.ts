import type { Balance } from '@/lib/units'

export interface Lot {
  id: number
  code: string
  kind: 'received' | 'portion'
  item: string
  food_item_id: number
  food_group: string
  group_label: string
  condition: string
  condition_label: string
  supplier: string | null
  supplier_lot: string | null
  produced_on: string | null
  expiry_on: string | null
  use_by: string | null
  past_use_by: boolean
  temp_c: number | null
  qty: number | null
  waste_qty: number | null
  unit: string | null
  pack_count: number | null
  pack_description: string | null
  tag_number: string | null
  location_id: number
  location: string | null
  status: Status
  note: string | null
  created_by_name: string | null
  created_at: string
  thawed_at: string | null
  children?: Lot[]
  balance?: Balance | null
}

export type Status = 'active' | 'used_up' | 'discarded' | 'on_hold'

export interface Use {
  reading_id: number
  lot_id: number
  lot_code: string
  at: string
  equipment: string
  stage: string
  display: string
  passed: boolean
  by: string | null
  rejected: boolean
}

export interface TimelineItem {
  at: string
  kind: string
  title: string
  detail: string
  lot_code: string
  by: string | null
  tone: 'neutral' | 'ok' | 'critical'
}

export interface Trace {
  lot: Lot
  balance: Balance | null
  timeline: TimelineItem[]
  back: Lot[]
  forward: Lot[]
  uses_back: Use[]
  uses_forward: Use[]
  events: { kind: string; detail: string; by: string | null; at: string }[]
}

export interface Rules {
  groups: { key: string; label: string }[]
  conditions: { key: string; label: string }[]
  rules: { id: number; food_group: string; condition: string; hours: number; note: string | null }[]
  cold_chain: Record<string, number>
}

export const STATUS_LABEL: Record<Status, string> = { active: 'Active', used_up: 'Used up', discarded: 'Discarded', on_hold: 'On hold' }
export const STATUS_TONE: Record<Status, 'ok' | 'neutral' | 'critical' | 'warn'> = { active: 'ok', used_up: 'neutral', discarded: 'critical', on_hold: 'warn' }
export const RECEIVED_CONDITIONS = [['chilled_raw', 'Chilled, raw'], ['vacuum_chilled', 'Vacuum packed, chilled'], ['frozen', 'Frozen']] as const
