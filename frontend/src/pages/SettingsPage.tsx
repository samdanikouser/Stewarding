import type { ComponentType } from 'react'
import { Navigate, useParams, useSearchParams } from 'react-router-dom'
import { SectionTabs, type TabGroup } from '@/components/SectionTabs'
import { SettingsInventoryLists } from '@/pages/settings/SettingsInventoryLists'
import { SettingsItems } from '@/pages/settings/SettingsItems'
import { SettingsLocations } from '@/pages/settings/SettingsLocations'
import { SettingsLookups } from '@/pages/settings/SettingsLookups'
import { SettingsMonitoring } from '@/pages/settings/SettingsMonitoring'
import { SettingsOrganization } from '@/pages/settings/SettingsOrganization'
import { SettingsQrCodes } from '@/pages/settings/SettingsQrCodes'
import { SettingsRoles } from '@/pages/settings/SettingsRoles'
import { SettingsRules } from '@/pages/settings/SettingsRules'
import { SettingsSearch } from '@/pages/settings/SettingsSearch'
import { SettingsShifts } from '@/pages/settings/SettingsShifts'
import { SettingsClosures } from '@/pages/settings/SettingsClosures'
import { SettingsSuppliers } from '@/pages/settings/SettingsSuppliers'
import { SettingsTrainingCourses } from '@/pages/settings/SettingsTrainingCourses'
import { SettingsTrainingProgress } from '@/pages/settings/SettingsTrainingProgress'
import type { RulesSection } from '@/pages/settings/settingsRegistry'
import { FIRST_SECTION, SECTION_GROUPS, resolveSection, type SectionKey } from '@/pages/settings/sections'

// each topic is its own component so a half-edited form never carries over to another topic
const rules = (section: RulesSection): ComponentType => () => <SettingsRules section={section} />

const PAGES: Record<SectionKey, ComponentType> = {
  organization: SettingsOrganization,
  attendance: rules('attendance'),
  'monitoring-rules': rules('monitoring-rules'),
  'qr-codes': SettingsQrCodes,
  approvals: rules('approvals'),
  breakage: rules('breakage'),
  receiving: rules('receiving'),
  locations: SettingsLocations,
  shifts: SettingsShifts,
  closures: SettingsClosures,
  monitoring: SettingsMonitoring,
  items: SettingsItems,
  inventory: SettingsInventoryLists,
  suppliers: SettingsSuppliers,
  'training-courses': SettingsTrainingCourses,
  'training-progress': SettingsTrainingProgress,
  lists: SettingsLookups,
  roles: SettingsRoles,
}

const GROUPS: TabGroup[] = SECTION_GROUPS.map((group) => ({ title: group.title, items: group.items.map(([key, label]) => ({ key, label })) }))

export function SettingsPage() {
  const { section } = useParams()
  const [params] = useSearchParams()
  const legacy = params.get('tab')
  const wanted = resolveSection(legacy ?? section)

  if (!wanted) return <Navigate to={`/settings/${FIRST_SECTION}`} replace />
  if (legacy || wanted !== section) return <Navigate to={`/settings/${wanted}`} replace />

  const Active = PAGES[wanted]
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <SectionTabs label="Settings" groups={GROUPS} active={wanted} hrefFor={(key) => `/settings/${key}`} trailing={<SettingsSearch />} />
      <Active />
    </div>
  )
}
