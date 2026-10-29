import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SectionTabs } from '@/components/SectionTabs'
import { useAuth } from '@/lib/auth'
import { FoodItemsTab } from '@/pages/trace/FoodItemsTab'
import { LotsTab } from '@/pages/trace/LotsTab'
import { PortionNamesTab } from '@/pages/trace/PortionNamesTab'
import { PrintersTab } from '@/pages/trace/PrintersTab'
import { ReceiveLotForm } from '@/pages/trace/ReceiveLotForm'
import { RulesTab } from '@/pages/trace/RulesTab'
import { SplitLotForm } from '@/pages/trace/SplitLotForm'

const TABS = [
  ['lots', 'Lots', 'lot.view'],
  ['receive', 'Receive food', 'lot.receive'],
  ['split', 'Split a lot', 'lot.split'],
  ['rules', 'Shelf life', 'lot.view'],
  ['items', 'Food items', 'lot.manage'],
  ['portions', 'Portion names', 'lot.manage'],
  ['printers', 'Label printers', 'lot.manage'],
] as const

type Tab = (typeof TABS)[number][0]

const GROUPS: { title: string; keys: Tab[] }[] = [
  { title: 'Lots', keys: ['lots', 'receive', 'split'] },
  { title: 'Setup', keys: ['rules', 'items', 'portions', 'printers'] },
]

export function TraceabilityPage() {
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  const [version, setVersion] = useState(0)
  const allowed = TABS.filter(([, , permission]) => me?.permissions.includes(permission))
  const requested = params.get('tab')
  const tab: Tab = (allowed.find(([key]) => key === requested) ?? allowed[0])?.[0] ?? 'lots'
  const refresh = () => setVersion((v) => v + 1)
  const groups = GROUPS
    .map((g) => ({ title: g.title, items: allowed.filter(([key]) => g.keys.includes(key)).map(([key, label]) => ({ key, label })) }))
    .filter((g) => g.items.length > 0)

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Food Traceability</h1>
      <SectionTabs label="Traceability" groups={groups} active={tab} onSelect={(key) => setParams({ tab: key })} />
      {tab === 'lots' && <LotsTab key={version} />}
      {tab === 'receive' && <ReceiveLotForm onSaved={refresh} />}
      {tab === 'split' && <SplitLotForm onSaved={refresh} />}
      {tab === 'rules' && <RulesTab />}
      {tab === 'items' && <FoodItemsTab />}
      {tab === 'portions' && <PortionNamesTab />}
      {tab === 'printers' && <PrintersTab />}
    </div>
  )
}
