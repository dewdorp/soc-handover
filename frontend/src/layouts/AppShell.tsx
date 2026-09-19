import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import CommandPalette from '@/features/search/CommandPalette'
import Sidebar from '@/layouts/Sidebar'
import Topbar from '@/layouts/Topbar'
import { useMe } from '@/hooks/useAuth'

/** 이보다 좁으면 메뉴를 접는다 — 펼친 메뉴(216px)가 본문을 짓눌러 표가 글자 단위로 꺾인다. */
const NARROW = '(max-width: 1023px)'

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(() => window.matchMedia(NARROW).matches)
  useEffect(() => {
    // 좁아질 때만 접는다. 넓어질 때 다시 펴지는 않는다(사용자가 접어 둔 것일 수 있다).
    const mq = window.matchMedia(NARROW)
    const onChange = (e: MediaQueryListEvent) => { if (e.matches) setCollapsed(true) }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // 통합검색(UI_STRUCTURE §10): Ctrl+K(맥 Cmd+K) 는 어디서든 팔레트, '/' 는 목록 검색창이 있으면
  // 거기로, 없으면 팔레트. 입력 중인 칸에서는 '/' 를 가로채지 않는다.
  const [paletteOpen, setPaletteOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(true)
        return
      }
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return
      e.preventDefault()
      const gridSearch = document.querySelector<HTMLInputElement>('[data-grid-search]')
      if (gridSearch) { gridSearch.focus(); gridSearch.select() } else setPaletteOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
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
      <Topbar onToggleSidebar={() => setCollapsed((v) => !v)} onOpenSearch={() => setPaletteOpen(true)} />
      <div className="flex-1 flex min-h-0">
        <Sidebar collapsed={collapsed} />
        <main className="flex-1 min-w-0 overflow-auto">
          <Outlet />
        </main>
      </div>
      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}
