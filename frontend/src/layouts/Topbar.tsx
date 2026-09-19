import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell, LogOut, Menu, Search, ShieldAlert } from 'lucide-react'
import { useFeatures, useLogout, useMe } from '@/hooks/useAuth'
import { notificationApi } from '@/services/api/shift'

const ROLE_LABEL: Record<string, string> = {
  ADMIN: '관리자',
  MANAGER: '근무 관리자',
  ANALYST: 'SOC 근무자',
}

export default function Topbar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
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

  return (
    <header className="h-12 shrink-0 border-b border-surface-border bg-surface flex items-center gap-3 px-3">
      <button className="btn btn-sm" onClick={onToggleSidebar} aria-label="메뉴 접기/펼치기">
        <Menu size={15} />
      </button>

      <div className="font-semibold tracking-tight text-md whitespace-nowrap">
        SOC 인수인계
      </div>

      <button
        className="flex-1 max-w-xl h-7 px-2.5 rounded border border-surface-border
                   bg-surface-sunken text-ink-faint flex items-center gap-2 hover:bg-white"
        onClick={() => navigate('/search')}
      >
        <Search size={14} />
        <span className="text-sm">통합 검색</span>
        <kbd className="ml-auto text-xs border border-surface-border rounded px-1 bg-surface">
          Ctrl K
        </kbd>
      </button>

      {features?.database_warning && (
        <span
          className="chip border-amber-300 bg-amber-50 text-amber-800"
          title={features.database_warning}
        >
          <ShieldAlert size={13} />
          개발용 DB
        </span>
      )}

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

      <div className="text-sm text-right leading-tight">
        <div className="font-medium">{me?.display_name}</div>
        <div className="text-ink-faint text-xs">{ROLE_LABEL[me?.role_code ?? ''] ?? ''}</div>
      </div>

      <button
        className="btn btn-sm"
        onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}
      >
        <LogOut size={14} />
        로그아웃
      </button>
    </header>
  )
}
