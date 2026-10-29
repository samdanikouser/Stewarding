import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth'

/** Shows a page only to people whose role includes its module; everyone else goes to the dashboard. */
export function RequireModule({ module, children }: { module: string; children: ReactNode }) {
  const { me } = useAuth()
  return me?.modules.some((m) => m.key === module) ? children : <Navigate to="/" replace />
}
