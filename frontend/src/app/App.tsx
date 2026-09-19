import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '@/layouts/AppShell'
import LoginPage from '@/features/auth/LoginPage'
import ChangePasswordPage from '@/features/auth/ChangePasswordPage'
import DashboardPage from '@/pages/DashboardPage'
import HandoverListPage from '@/features/handovers/HandoverListPage'
import ImportWizardPage from '@/features/import/ImportWizardPage'
import NotificationPage from '@/features/notifications/NotificationPage'
import ShiftPage from '@/features/shift/ShiftPage'
import MyWorkPage from '@/features/mywork/MyWorkPage'
import TaskPage from '@/features/tasks/TaskPage'
import CalendarPage from '@/features/calendar/CalendarPage'
import SearchPage from '@/features/search/SearchPage'
import {
  AdminPage, AiSearchPage, AuditPage,
  NotFoundPage, SettingsPage,
  StatsPage,
} from '@/pages/placeholders'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // 인증/권한 오류는 재시도하지 않는다
        const status = (error as { status?: number }).status
        if (status === 401 || status === 403 || status === 404) return false
        return failureCount < 2
      },
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="/handovers/*" element={<HandoverListPage />} />
            <Route path="/shift/*" element={<ShiftPage />} />
            <Route path="/my-work" element={<MyWorkPage />} />
            <Route path="/tasks/*" element={<TaskPage />} />
            <Route path="/schedules" element={<CalendarPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/ai" element={<AiSearchPage />} />
            <Route path="/import/*" element={<ImportWizardPage />} />
            <Route path="/stats" element={<StatsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/notifications" element={<NotificationPage />} />
            <Route path="/admin/*" element={<AdminPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/404" element={<NotFoundPage />} />
            <Route path="*" element={<Navigate to="/404" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
