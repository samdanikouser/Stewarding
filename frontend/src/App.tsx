import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/AppLayout'
import { RequireModule } from '@/components/RequireModule'
import { useAuth } from '@/lib/auth'
import { AttendancePage } from '@/pages/AttendancePage'
import { AuditPage } from '@/pages/AuditPage'
import { BreakagePage } from '@/pages/BreakagePage'
import { TraceabilityPage } from '@/pages/TraceabilityPage'
import { ChangePasswordPage } from '@/pages/ChangePasswordPage'
import { CheckInPage } from '@/pages/CheckInPage'
import { SchedulePage } from '@/pages/SchedulePage'
import { CountSheetPage } from '@/pages/CountSheetPage'
import { ChecklistsPage } from '@/pages/ChecklistsPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { EmployeesPage } from '@/pages/EmployeesPage'
import { InventoryPage } from '@/pages/InventoryPage'
import { LoginPage } from '@/pages/LoginPage'
import { ModulePage } from '@/pages/ModulePage'
import { ScanPage } from '@/pages/ScanPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { ReportsPage } from '@/pages/ReportsPage'
import { RosterPage } from '@/pages/RosterPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { TasksPage } from '@/pages/TasksPage'
import { StockMovementsPage } from '@/pages/StockMovementsPage'
import { MonitoringPage } from '@/pages/MonitoringPage'
import { TrainingCoursePage } from '@/pages/training/TrainingCoursePage'
import { TrainingPage } from '@/pages/training/TrainingPage'

export default function App() {
  const { me, loading } = useAuth()
  if (loading) return <div className="p-8 text-sm text-ink-muted">Loading...</div>
  if (!me) return <LoginPage />
  if (me.change_required) return <ChangePasswordPage />

  return (
    <Routes>
      <Route path="count-sheet" element={<RequireModule module="stock-movements"><CountSheetPage /></RequireModule>} />
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="employees" element={<RequireModule module="employees"><EmployeesPage /></RequireModule>} />
        <Route path="check-in" element={<RequireModule module="check-in"><CheckInPage /></RequireModule>} />
        <Route path="my-schedule" element={<RequireModule module="my-schedule"><SchedulePage /></RequireModule>} />
        <Route path="attendance" element={<RequireModule module="attendance"><AttendancePage /></RequireModule>} />
        <Route path="roster" element={<RequireModule module="roster"><RosterPage /></RequireModule>} />
        <Route path="checklists" element={<RequireModule module="checklists"><ChecklistsPage /></RequireModule>} />
        <Route path="daily-checklists" element={<Navigate to="/checklists" replace />} />
        <Route path="weekly-checklists" element={<Navigate to="/checklists" replace />} />
        <Route path="monitoring" element={<RequireModule module="monitoring"><MonitoringPage /></RequireModule>} />
        <Route path="temperature" element={<Navigate to="/monitoring" replace />} />
        <Route path="equipment" element={<Navigate to="/settings/monitoring" replace />} />
        <Route path="inventory" element={<RequireModule module="inventory"><InventoryPage /></RequireModule>} />
        <Route path="crockery" element={<Navigate to="/inventory" replace />} />
        <Route path="smallware" element={<Navigate to="/inventory" replace />} />
        <Route path="stock-movements" element={<RequireModule module="stock-movements"><StockMovementsPage /></RequireModule>} />
        <Route path="breakage" element={<RequireModule module="breakage"><BreakagePage /></RequireModule>} />
        <Route path="traceability" element={<RequireModule module="traceability"><TraceabilityPage /></RequireModule>} />
        <Route path="training" element={<RequireModule module="training"><TrainingPage /></RequireModule>} />
        <Route path="training/:assignmentId" element={<RequireModule module="training"><TrainingCoursePage /></RequireModule>} />
        <Route path="tasks" element={<RequireModule module="tasks"><TasksPage /></RequireModule>} />
        <Route path="reports" element={<RequireModule module="reports"><ReportsPage /></RequireModule>} />
        <Route path="settings" element={<RequireModule module="settings"><SettingsPage /></RequireModule>} />
        <Route path="settings/:section" element={<RequireModule module="settings"><SettingsPage /></RequireModule>} />
        <Route path="audit" element={<RequireModule module="audit"><AuditPage /></RequireModule>} />
        <Route path="scan/:token" element={<ScanPage />} />
        <Route path="account" element={<ProfilePage />} />
        <Route path=":key" element={<ModulePage />} />
      </Route>
    </Routes>
  )
}
