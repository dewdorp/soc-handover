import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { shiftApi } from '@/services/api/shift'

const AREAS = {
  handovers: [
    { to: '/handovers', label: '인수인계 기록' },
    { to: '/shift', label: '인계 준비' },
    { to: '/shift/inbox', label: '인수 확인함' },
    { to: '/shift/history', label: '인계 이력' },
  ],
  work: [
    { to: '/my-work', label: '내 담당 업무' },
    { to: '/my-work/notes', label: '내 메모' },
    { to: '/tasks', label: '팀 할일' },
    { to: '/schedules', label: '팀 일정' },
    { to: '/schedules/roster', label: '근무표' },
  ],
}

export default function WorkspaceLayout({ area }: { area: keyof typeof AREAS }) {
  const isHandover = area === 'handovers'
  const { data: inbox } = useQuery({
    queryKey: ['inbox'], queryFn: shiftApi.inbox, enabled: isHandover, refetchInterval: 30_000,
  })
  return (
    <div className="h-full flex flex-col min-h-0">
      <nav aria-label={isHandover ? '인수인계 메뉴' : '업무 메뉴'}
           className="shrink-0 flex flex-wrap gap-x-1 border-b border-surface-border bg-surface px-2">
        {AREAS[area].map(({ to, label }) => (
          <NavLink key={to} to={to} end={to === '/shift' || to === '/my-work' || to === '/schedules'}
                   className={({ isActive }) => `px-2 sm:px-3 py-2 inline-flex items-center gap-1.5 border-b-2 text-sm whitespace-nowrap ${isActive
                     ? 'border-brand text-brand font-semibold' : 'border-transparent text-ink-muted hover:text-ink'}`}>
            {label}
            {to === '/shift/inbox' && !!inbox?.length && (
              <span className="px-1.5 rounded bg-brand-soft text-brand text-xs tabular-nums">{inbox.length}</span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="flex-1 min-h-0 min-w-0 overflow-auto">
        <Outlet />
      </div>
    </div>
  )
}
