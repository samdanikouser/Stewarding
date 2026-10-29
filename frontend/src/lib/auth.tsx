import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, tokenStore } from '@/lib/api'

export interface Me {
  id: number
  email: string
  change_required: boolean
  role: string
  role_label: string
  tier: 'manager' | 'supervisor' | 'steward'
  employee: { id: number; name: string; code: string } | null
  permissions: string[]
  by_location: boolean
  locations: { id: number; code: string; name: string; timezone: string; geofence: boolean }[]
  modules: { key: string; label: string }[]
}

interface AuthState {
  me: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  changePassword: (current: string, next: string) => Promise<void>
  refresh: () => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(Boolean(tokenStore.get()))

  const navigate = useNavigate()

  // an expired session keeps the address, so signing in again returns to the page that was open
  const endSession = useCallback(() => {
    tokenStore.clear()
    setMe(null)
  }, [])

  // signing out on purpose goes back to the start, so the next person does not land on this person's page
  const logout = useCallback(() => {
    endSession()
    navigate('/', { replace: true })
  }, [endSession, navigate])

  useEffect(() => {
    if (!tokenStore.get()) return
    api<Me>('/auth/me')
      .then(setMe)
      .catch(endSession)
      .finally(() => setLoading(false))
  }, [endSession])

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api<{ access_token: string }>('/auth/login', { body: { email, password } })
    tokenStore.set(access_token)
    setMe(await api<Me>('/auth/me'))
  }, [])

  const changePassword = useCallback(async (current: string, next: string) => {
    const { access_token } = await api<{ access_token: string }>('/auth/change-password', { body: { current_password: current, new_password: next } })
    tokenStore.set(access_token)
    setMe(await api<Me>('/auth/me'))
  }, [])

  /** Reloads the signed-in user, so new locations and changed access show up without signing in again. */
  const refresh = useCallback(async () => {
    setMe(await api<Me>('/auth/me'))
  }, [])

  const value = useMemo(() => ({ me, loading, login, changePassword, refresh, logout }), [me, loading, login, changePassword, refresh, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
