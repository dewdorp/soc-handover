import { useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import Sidebar from '@/layouts/Sidebar'
import Topbar from '@/layouts/Topbar'
import { useMe } from '@/hooks/useAuth'

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const { data: me, isLoading } = useMe()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="h-full grid place-items-center text-ink-muted text-sm">
        불러오는 중…
      </div>
    )
  }

  if (!me) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  // 초기 비밀번호를 바꾸지 않은 계정은 변경 화면 밖으로 나갈 수 없다.
  if (me.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }

  return (
    <div className="h-full flex flex-col">
      <Topbar onToggleSidebar={() => setCollapsed((v) => !v)} />
      <div className="flex-1 flex min-h-0">
        <Sidebar collapsed={collapsed} />
        <main className="flex-1 min-w-0 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
