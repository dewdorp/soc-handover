/** 관리자 (/admin/users · codes · shifts · backup) — ADMIN 전용. */
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import BackupTab from '@/features/admin/BackupTab'
import CodesTab from '@/features/admin/CodesTab'
import ShiftsTab from '@/features/admin/ShiftsTab'
import UsersTab from '@/features/admin/UsersTab'
import { useCan } from '@/hooks/useAuth'

const TABS = [
  { to: 'users', label: '사용자' }, { to: 'codes', label: '상태 · 관계사' },
  { to: 'shifts', label: '교대 시간' }, { to: 'backup', label: '백업' },
]

export default function AdminPage() {
  const can = useCan()
  if (!can('user:manage')) return <p className="p-4 text-ink-muted">관리자만 볼 수 있는 화면입니다.</p>
  const tab = ({ isActive }: { isActive: boolean }) =>
    `px-3 h-8 inline-flex items-center border-b-2 ${isActive ? 'border-brand text-brand font-medium' : 'border-transparent text-ink-muted hover:text-ink'}`
  return (
    <div className="h-full flex flex-col min-h-0">
      <nav className="flex flex-wrap items-center gap-1 px-3 border-b border-surface-border" aria-label="관리자">
        <h1 className="text-md font-medium mr-3">관리자</h1>
        {TABS.map((t) => <NavLink key={t.to} to={`/admin/${t.to}`} className={tab}>{t.label}</NavLink>)}
      </nav>
      <div className="flex-1 min-h-0 overflow-auto p-3">
        <Routes>
          <Route path="users" element={<UsersTab />} />
          <Route path="codes" element={<CodesTab />} />
          <Route path="shifts" element={<ShiftsTab />} />
          <Route path="backup" element={<BackupTab />} />
          <Route path="*" element={<Navigate to="/admin/users" replace />} />
        </Routes>
      </div>
    </div>
  )
}
