/** 교대 인수인계 — Cockpit · 인수 확인함 · 인계 이력. 탭은 주소에 있다(/shift, /shift/inbox, /shift/history). */
import { useQuery } from '@tanstack/react-query'
import { NavLink, useLocation } from 'react-router-dom'
import CockpitView from '@/features/shift/CockpitView'
import HistoryView from '@/features/shift/HistoryView'
import InboxView from '@/features/shift/InboxView'
import { shiftApi } from '@/services/api/shift'

export default function ShiftPage() {
  const { pathname } = useLocation()
  const tab = pathname.startsWith('/shift/inbox') ? 'inbox'
    : pathname.startsWith('/shift/history') ? 'history' : 'cockpit'
  const { data: inbox } = useQuery({ queryKey: ['inbox'], queryFn: shiftApi.inbox, refetchInterval: 30_000 })

  const link = (active: boolean) =>
    `px-3 h-8 inline-flex items-center gap-1.5 border-b-2 ${active
      ? 'border-brand text-brand font-medium' : 'border-transparent text-ink-muted hover:text-ink'}`

  return (
    <div className="h-full flex flex-col min-h-0">
      <nav className="flex items-center gap-1 px-3 border-b border-surface-border" aria-label="교대 인수인계">
        <h1 className="text-md font-medium mr-3">교대 인수인계</h1>
        <NavLink to="/shift" end className={() => link(tab === 'cockpit')}>Cockpit · 인계하기</NavLink>
        <NavLink to="/shift/inbox" className={() => link(tab === 'inbox')}>
          인수 확인함
          {(inbox?.length ?? 0) > 0 && (
            <span className="min-w-4 h-4 px-1 rounded-full bg-state-check text-white text-xs leading-4 text-center">
              {inbox!.length}
            </span>
          )}
        </NavLink>
        <NavLink to="/shift/history" className={() => link(tab === 'history')}>인계 이력</NavLink>
      </nav>
      {tab === 'cockpit' && <CockpitView />}
      {tab === 'inbox' && <InboxView />}
      {tab === 'history' && <HistoryView />}
    </div>
  )
}
