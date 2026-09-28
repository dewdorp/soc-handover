import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import {
  LayoutDashboard, ClipboardList, ArrowLeftRight, UserCheck, ListTodo,
  CalendarDays, Search, FileSpreadsheet, BarChart3, ShieldCheck, KeyRound,
  Settings, Users,
} from 'lucide-react'
import { useCan } from '@/hooks/useAuth'

interface NavEntry {
  to: string
  label: string
  icon: typeof LayoutDashboard
  /** 필요한 권한(없으면 모두 표시) */
  permission?: string
  end?: boolean
}

const GROUPS: { title?: string; items: NavEntry[] }[] = [
  { items: [{ to: '/', label: '대시보드', icon: LayoutDashboard, end: true }] },
  {
    title: '업무 연속성',
    items: [
      { to: '/handovers', label: '인수인계', icon: ClipboardList },
      { to: '/shift', label: '교대 인수인계', icon: ArrowLeftRight },
      { to: '/my-work', label: '내 업무', icon: UserCheck },
    ],
  },
  {
    title: '실행',
    items: [
      { to: '/tasks', label: '할일', icon: ListTodo },
      { to: '/schedules', label: '일정', icon: CalendarDays },
      { to: '/credentials', label: '비밀번호', icon: KeyRound, permission: 'credential:read' },
    ],
  },
  {
    title: '탐색',
    items: [
      { to: '/search', label: '통합검색', icon: Search },
    ],
  },
  {
    title: '데이터 · 운영',
    items: [
      { to: '/import', label: 'Excel Import/Export', icon: FileSpreadsheet, permission: 'import:run' },
      { to: '/stats', label: '통계', icon: BarChart3, permission: 'stats:read_all' },
      { to: '/audit', label: '감사로그', icon: ShieldCheck, permission: 'audit:read_self' },
      { to: '/admin/users', label: '관리자', icon: Users, permission: 'user:manage' },
      { to: '/settings', label: '설정', icon: Settings, permission: 'settings:manage' },
    ],
  },
]

export default function Sidebar({ collapsed }: { collapsed: boolean }) {
  const can = useCan()

  return (
    <nav
      className={clsx(
        'shrink-0 border-r border-surface-border bg-surface-sunken overflow-y-auto',
        collapsed ? 'w-14' : 'w-[216px]',
      )}
      aria-label="주 메뉴"
    >
      <div className="p-2 space-y-3">
        {GROUPS.map((group, gi) => {
          const items = group.items.filter((i) => !i.permission || can(i.permission))
          if (items.length === 0) return null
          return (
            <div key={gi}>
              {group.title && !collapsed && (
                <div className="px-2.5 pb-1 text-xs text-ink-faint tracking-wide">
                  {group.title}
                </div>
              )}
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.end}
                      className={({ isActive }) =>
                        clsx('nav-item', isActive && 'nav-item-active',
                          collapsed && 'justify-center px-0')
                      }
                      title={collapsed ? item.label : undefined}
                    >
                      <item.icon size={15} strokeWidth={1.8} className="shrink-0" />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </nav>
  )
}
