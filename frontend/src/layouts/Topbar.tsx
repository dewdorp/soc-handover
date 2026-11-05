import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell, BellOff, BellRing, Keyboard, LogOut, Menu, Search, ShieldAlert } from 'lucide-react'
import { desktopEnabled, disableDesktop, enableDesktop } from '@/features/notifications/NotificationPopups'
import { useFeatures, useLogout, useMe } from '@/hooks/useAuth'
import { notificationApi } from '@/services/api/shift'

const ROLE_LABEL: Record<string, string> = {
  ADMIN: '관리자',
  MANAGER: '근무 관리자',
  ANALYST: 'SOC 근무자',
}

export default function Topbar({ onToggleSidebar, onOpenSearch, onOpenHelp }: {
  onToggleSidebar: () => void; onOpenSearch: () => void; onOpenHelp: () => void
}) {
  const { data: me } = useMe()
  const { data: features } = useFeatures()
  const logout = useLogout()
  const navigate = useNavigate()
  // 알림은 WebSocket 없이 30초 폴링으로 본다(ASSUMPTIONS F-04).
  const { data: unread } = useQuery({
    queryKey: ['unread-count'], queryFn: notificationApi.unreadCount,
    enabled: Boolean(me), refetchInterval: 30_000,
  })
  const unreadCount = unread?.unread ?? me?.unread_notification_count ?? 0

  // 바탕화면 알림. 권한은 **사람이 눌렀을 때만** 묻는다 — 들어오자마자 묻는 창은 업무를 가린다.
  const [popup, setPopup] = useState(desktopEnabled)
  const togglePopup = async () => {
    if (popup) { disableDesktop(); setPopup(false); return }
    const result = await enableDesktop()
    if (result === 'granted') { setPopup(true); return }
    setPopup(false)
    window.alert(result === 'unsupported'
      ? '이 브라우저는 바탕화면 알림을 지원하지 않습니다. 화면 안 팝업은 그대로 뜹니다.'
      : ['브라우저가 바탕화면 알림을 막았습니다.',
         '주소창 왼쪽 자물쇠에서 알림을 허용해 주십시오.',
         '허용하지 않아도 화면 안 팝업은 그대로 뜹니다.'].join('\n'))
  }

  return (
    <header className="h-14 shrink-0 border-b border-surface-border bg-surface flex items-center gap-1.5 px-2 sm:gap-3 sm:px-3">
      <button className="btn btn-sm" onClick={onToggleSidebar} aria-label="메뉴 접기/펼치기">
        <Menu size={15} />
      </button>

      <div className="border-l-2 border-brand pl-2 font-semibold tracking-tight text-md whitespace-nowrap">
        SOC 인수인계
      </div>

      <button
        className="min-w-0 flex-1 max-w-xl h-8 px-2 sm:px-2.5 rounded-md border border-surface-border
                   bg-surface-sunken text-ink-faint flex items-center gap-2 hover:bg-white"
        onClick={onOpenSearch} aria-label="통합 검색 (Ctrl+K)" title="인수인계 · 할일 · 일정을 한 번에 찾습니다"
      >
        <Search size={14} />
        <span className="text-sm truncate">통합 검색</span>
        <kbd className="ml-auto hidden sm:inline text-xs border border-surface-border rounded px-1 bg-surface">
          Ctrl K
        </kbd>
      </button>

      {features?.database_warning && (
        <span
          className="chip border-amber-300 bg-amber-50 text-amber-800"
          title={features.database_warning}
        >
          <ShieldAlert size={13} />
          <span className="whitespace-nowrap hidden sm:inline">개발용 DB</span>
        </span>
      )}

      <button className="btn btn-sm hidden sm:inline-flex" onClick={onOpenHelp} aria-label="키보드 단축키 (?)" title="키보드 단축키 (?)">
        <Keyboard size={15} />
      </button>

      <button className="btn btn-sm hidden sm:inline-flex" onClick={togglePopup}
              aria-pressed={popup}
              aria-label={popup ? '바탕화면 알림 끄기' : '바탕화면 알림 켜기'}
              title={popup
                ? '바탕화면 알림이 켜져 있습니다 — 다른 창을 보고 있어도 뜹니다'
                : '바탕화면 알림 켜기 — 다른 창을 보고 있어도 새 알림이 뜹니다'}>
        {popup ? <BellRing size={15} className="text-brand" /> : <BellOff size={15} />}
      </button>

      <button className="btn btn-sm relative" onClick={() => navigate('/notifications')}
              aria-label={`알림${unreadCount ? ` (안 읽음 ${unreadCount}건)` : ''}`}>
        <Bell size={15} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full
                           bg-state-urgent text-white text-xs leading-4 text-center">
            {unreadCount}
          </span>
        )}
      </button>

      <div className="text-sm text-right leading-tight whitespace-nowrap hidden md:block">
        <div className="font-medium">{me?.display_name}</div>
        <div className="text-ink-faint text-xs">{ROLE_LABEL[me?.role_code ?? ''] ?? ''}</div>
      </div>

      <button
        className="btn btn-sm" aria-label="로그아웃" title={me ? `${me.display_name} 로그아웃` : '로그아웃'}
        onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })}
      >
        <LogOut size={14} />
        <span className="hidden sm:inline">로그아웃</span>
      </button>
    </header>
  )
}
