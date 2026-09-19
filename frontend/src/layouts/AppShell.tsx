import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import ShortcutHelp from '@/components/ui/ShortcutHelp'
import CreateHandoverDialog from '@/features/handovers/CreateHandoverDialog'
import CommandPalette from '@/features/search/CommandPalette'
import TaskCreateDialog from '@/features/tasks/TaskCreateDialog'
import Sidebar from '@/layouts/Sidebar'
import Topbar from '@/layouts/Topbar'
import { useCan, useMe } from '@/hooks/useAuth'
import { isTyping, keyCode, modalOpen } from '@/hooks/useHotkeys'
import { referenceApi } from '@/services/api/reference'

/** 이보다 좁으면 메뉴를 접는다 — 펼친 메뉴(216px)가 본문을 짓눌러 표가 글자 단위로 꺾인다. */
const NARROW = '(max-width: 1023px)'

type Overlay = 'palette' | 'help' | 'new-handover' | 'new-task' | null

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(() => window.matchMedia(NARROW).matches)
  useEffect(() => {
    // 좁아질 때만 접는다. 넓어질 때 다시 펴지는 않는다(사용자가 접어 둔 것일 수 있다).
    const mq = window.matchMedia(NARROW)
    const onChange = (e: MediaQueryListEvent) => { if (e.matches) setCollapsed(true) }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const navigate = useNavigate()
  const qc = useQueryClient()
  const can = useCan()
  const [overlay, setOverlay] = useState<Overlay>(null)
  const close = () => setOverlay(null)

  // 어디서나 쓰는 단축키(UI_STRUCTURE §10). 키 위치(e.code)로 본다 — 한글 입력 상태에서도 같게.
  //   Ctrl/Cmd+K 통합검색 · '/' 목록 검색창 또는 통합검색 · '?' 도움말 · Alt+N 새 인수인계 · Alt+T 새 할일
  //   (Ctrl+N · Ctrl+Shift+T 는 브라우저가 새 창·닫은 탭으로 가져가서 페이지에 오지 않는다)
  const allow = { handover: can('handover:create'), task: can('task:create') }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (modalOpen()) return
      const code = keyCode(e)
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && code === 'KeyK') {
        e.preventDefault(); setOverlay('palette'); return
      }
      if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        if (code === 'KeyN' && allow.handover) { e.preventDefault(); setOverlay('new-handover') }
        else if (code === 'KeyT' && allow.task) { e.preventDefault(); setOverlay('new-task') }
        return
      }
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || isTyping(e.target) || code !== 'Slash') return
      e.preventDefault()
      if (e.shiftKey || e.key === '?') { setOverlay('help'); return }      // Shift+/ = '?'
      const gridSearch = document.querySelector<HTMLInputElement>('[data-grid-search]')
      if (gridSearch) { gridSearch.focus(); gridSearch.select() } else setOverlay('palette')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [allow.handover, allow.task])

  const needRefs = overlay === 'new-handover'
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: referenceApi.companies, staleTime: 5 * 60_000, enabled: needRefs })
  const { data: statuses } = useQuery({ queryKey: ['statuses'], queryFn: referenceApi.statuses, staleTime: 5 * 60_000, enabled: needRefs })
  const { data: priorities } = useQuery({ queryKey: ['priorities'], queryFn: referenceApi.priorities, staleTime: 5 * 60_000, enabled: needRefs })

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
      <Topbar onToggleSidebar={() => setCollapsed((v) => !v)} onOpenSearch={() => setOverlay('palette')}
              onOpenHelp={() => setOverlay('help')} />
      <div className="flex-1 flex min-h-0">
        <Sidebar collapsed={collapsed} />
        <main className="flex-1 min-w-0 overflow-auto">
          <Outlet />
        </main>
      </div>
      {overlay === 'palette' && <CommandPalette onClose={close} />}
      {overlay === 'help' && <ShortcutHelp onClose={close} />}
      {overlay === 'new-task' && (
        <TaskCreateDialog onClose={close} onCreated={(t) => navigate(`/tasks?id=${t.id}`)} />
      )}
      {overlay === 'new-handover' && companies && statuses && priorities && (
        <CreateHandoverDialog companies={companies} statuses={statuses} priorities={priorities}
                              onClose={close}
                              onCreated={(id) => {
                                close()
                                qc.invalidateQueries({ queryKey: ['handovers'] })
                                navigate(`/handovers?id=${id}`)
                              }} />
      )}
    </div>
  )
}
