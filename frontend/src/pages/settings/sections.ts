export const SECTION_GROUPS = [
  { title: 'Company', items: [['organization', 'Organization'], ['locations', 'Locations'], ['shifts', 'Shifts'], ['closures', 'Closed days']] },
  { title: 'People', items: [['attendance', 'Check-in and attendance rules'], ['roles', 'Roles'], ['approvals', 'Approvals and escalation']] },
  { title: 'Food safety', items: [['monitoring', 'Monitoring setup'], ['monitoring-rules', 'Monitoring rules'], ['qr-codes', 'QR codes']] },
  { title: 'Stock', items: [['items', 'Item master'], ['inventory', 'Categories & units'], ['suppliers', 'Suppliers'], ['breakage', 'Breakage approval'], ['receiving', 'Receiving']] },
  { title: 'Training', items: [['training-courses', 'Courses and materials'], ['training-progress', 'Assignments and progress']] },
  { title: 'Lists', items: [['lists', 'Dropdown lists']] },
] as const

export type SectionKey = (typeof SECTION_GROUPS)[number]['items'][number][0]

export const FIRST_SECTION: SectionKey = 'organization'

/** Addresses from before "Rules & alerts" was split by topic. */
const RENAMED: Record<string, SectionKey> = { general: 'attendance' }

export const isSection = (key: string | null | undefined): key is SectionKey =>
  SECTION_GROUPS.some((group) => group.items.some(([sectionKey]) => sectionKey === key))

/** The section an address names, following a renamed one, or nothing when it names none. */
export const resolveSection = (key: string | null | undefined): SectionKey | null =>
  isSection(key) ? key : key && Object.hasOwn(RENAMED, key) ? RENAMED[key] : null
