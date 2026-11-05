import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, createRoutesFromElements, Navigate, Route, RouterProvider } from 'react-router-dom'
import { clearRecentSearches } from '@/features/search/recent'
import { watchSessionChanges } from '@/services/sessionChanges'
import type { Me } from '@/types/api'
import AppShell from '@/layouts/AppShell'
import WorkspaceLayout from '@/layouts/WorkspaceLayout'
import LoginPage from '@/features/auth/LoginPage'
import ChangePasswordPage from '@/features/auth/ChangePasswordPage'
import DashboardPage from '@/pages/DashboardPage'
import HandoverListPage from '@/features/handovers/HandoverListPage'
import ImportWizardPage from '@/features/import/ImportWizardPage'
import NotificationPage from '@/features/notifications/NotificationPage'
import ShiftPage from '@/features/shift/ShiftPage'
import MyNotesPage from '@/features/mywork/MyNotesPage'
import MyWorkPage from '@/features/mywork/MyWorkPage'
import TaskPage from '@/features/tasks/TaskPage'
import CalendarPage from '@/features/calendar/CalendarPage'
import RosterPage from '@/features/calendar/RosterPage'
import CredentialsPage from '@/features/credentials/CredentialsPage'
import SearchPage from '@/features/search/SearchPage'
import AuditPage from '@/features/audit/AuditPage'
import AdminPage from '@/features/admin/AdminPage'
import SettingsPage from '@/features/admin/SettingsPage'
import StatsPage from '@/features/stats/StatsPage'
import NotFoundPage from '@/pages/NotFoundPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // 인증/권한 오류는 재시도하지 않는다
        const status = (error as { status?: number }).status
        if (status === 401 || status === 403 || status === 404 || status === 412) return false
        return failureCount < 2
      },
    },
  },
})

const router = createBrowserRouter(createRoutesFromElements(
  <>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/change-password" element={<ChangePasswordPage />} />
    <Route element={<AppShell />}>
      <Route index element={<DashboardPage />} />
      <Route element={<WorkspaceLayout area="handovers" />}>
        <Route path="/handovers/*" element={<HandoverListPage />} />
        <Route path="/shift/*" element={<ShiftPage />} />
      </Route>
      <Route element={<WorkspaceLayout area="work" />}>
        <Route path="/my-work" element={<MyWorkPage />} />
        <Route path="/my-work/notes" element={<MyNotesPage />} />
        <Route path="/tasks/*" element={<TaskPage />} />
        <Route path="/schedules" element={<CalendarPage />} />
        <Route path="/schedules/roster" element={<RosterPage />} />
      </Route>
      <Route path="/credentials" element={<CredentialsPage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/import/*" element={<ImportWizardPage />} />
      <Route path="/stats" element={<StatsPage />} />
      <Route path="/audit" element={<AuditPage />} />
      <Route path="/notifications" element={<NotificationPage />} />
      <Route path="/admin/*" element={<AdminPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/404" element={<NotFoundPage />} />
      <Route path="*" element={<Navigate to="/404" replace />} />
    </Route>
  </>,
))

export default function App() {
  const [session, setSession] = useState(0)
  useEffect(() => watchSessionChanges(expectedUserId => {
    if (expectedUserId !== undefined && queryClient.getQueryData<Me | null>(['me'])?.id !== expectedUserId) return
    clearRecentSearches()
    queryClient.clear()
    setSession(s => s + 1)
  }), [])
  return <QueryClientProvider client={queryClient}><RouterProvider key={session} router={router} /></QueryClientProvider>
}
