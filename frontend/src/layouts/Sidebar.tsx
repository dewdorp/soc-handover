import { useId, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import clsx from 'clsx'
import {
  LayoutDashboard, ClipboardList, UserCheck, FileSpreadsheet, BarChart3, ShieldCheck, KeyRound,
  Settings, Users, ChevronDown, CalendarClock, BookOpen,
} from 'lucide-react'
import { useCan } from '@/hooks/useAuth'

interface NavEntry {
  to: string
  label: string
  icon: typeof LayoutDashboard
  permission?: string
  sections?: string[]
}

const MAIN: NavEntry[] = [
  { to: '/', label: '대시보드', icon: LayoutDashboard },
  { to: '/handovers', label: '인수인계', icon: ClipboardList, sections: ['/handovers', '/shift'] },
  { to: '/my-work', label: '내 업무', icon: UserCheck, sections: ['/my-work', '/tasks'] },
  { to: '/schedules', label: '일정 · 근무표', icon: CalendarClock, sections: ['/schedules'] },
  { to: '/credentials', label: '비밀번호', icon: KeyRound, permission: 'credential:read' },
  { to: '/knowledge', label: '운영 지식', icon: BookOpen, permission: 'handover:read' },
]

const OPERATIONS: NavEntry[] = [
  { to: '/import', label: 'Excel Import/Export', icon: FileSpreadsheet, permission: 'import:run' },
  { to: '/stats', label: '통계', icon: BarChart3, permission: 'stats:read_all' },
  { to: '/audit', label: '감사로그', icon: ShieldCheck, permission: 'audit:read_self' },
  { to: '/admin/users', label: '관리자', icon: Users, permission: 'user:manage', sections: ['/admin'] },
  { to: '/settings', label: '설정', icon: Settings, permission: 'settings:manage' },
]

function isCurrent(item: NavEntry, pathname: string) {
  return (item.sections ?? [item.to]).some((path) => pathname === path || pathname.startsWith(`${path}/`))
}

function NavItems({ items, collapsed, pathname }: { items: NavEntry[]; collapsed: boolean; pathname: string }) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const active = isCurrent(item, pathname)
        return (
          <li key={item.to}>
            <Link
              to={item.to}
              aria-current={active ? (pathname === item.to ? 'page' : 'location') : undefined}
              className={clsx('nav-item', active && 'nav-item-active', collapsed && 'justify-center px-0')}
              title={collapsed ? item.label : undefined}
            >
              <item.icon size={16} strokeWidth={1.8} aria-hidden="true" className="shrink-0" />
              <span className={collapsed ? 'sr-only' : 'truncate'}>{item.label}</span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function Operations({ items, pathname }: { items: NavEntry[]; pathname: string }) {
  const [open, setOpen] = useState(() => items.some((item) => isCurrent(item, pathname)))
  const id = useId()
  return (
    <>
      <button type="button" className="nav-item w-full" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <Settings size={16} strokeWidth={1.8} aria-hidden="true" />
        운영·관리
        <ChevronDown size={14} aria-hidden="true" className={clsx('ml-auto', !open && '-rotate-90')} />
      </button>
      <div id={id} className="pl-2" hidden={!open}><NavItems items={items} collapsed={false} pathname={pathname} /></div>
    </>
  )
}

export default function Sidebar({ collapsed }: { collapsed: boolean }) {
  const can = useCan()
  const { pathname } = useLocation()
  const allowed = (item: NavEntry) => !item.permission || can(item.permission)
  const operations = OPERATIONS.filter(allowed)

  return (
    <nav className={clsx('shrink-0 border-r border-surface-nav bg-surface-nav overflow-y-auto', collapsed ? 'w-14' : 'w-[216px]')} aria-label="주 메뉴">
      <div className="px-2 py-3">
        <NavItems items={MAIN.filter(allowed)} collapsed={collapsed} pathname={pathname} />
        {operations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-white/15" role="group" aria-label="운영 도구">
            {collapsed ? <NavItems items={operations} collapsed pathname={pathname} />
              : <Operations key={pathname} items={operations} pathname={pathname} />}
          </div>
        )}
      </div>
    </nav>
  )
}
