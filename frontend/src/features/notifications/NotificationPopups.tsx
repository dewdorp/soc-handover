/**
 * 알림 팝업 — 새 알림이 오면 화면 구석에 띄운다.
 *
 * 왜 필요한가
 *   종 아이콘의 빨간 숫자는 **보고 있어야** 보인다. 야간에 다른 화면을 띄워 두거나 자리를
 *   비운 사이에 들어온 인계·대근·의뢰는 종만으로는 알 수 없다. 교대 현장에서 '못 봤다'가
 *   생기는 자리가 여기다.
 *
 * 두 겹으로 띄운다
 *   1) **화면 안 팝업** — 언제나 뜬다. 브라우저 권한이 필요 없고, 화면을 보고 있으면 눈에 띈다.
 *   2) **바탕화면 알림** — 켜 두면 다른 창을 보고 있어도 뜬다. 브라우저 권한이 필요해
 *      사람이 한 번 눌러 허용해야 한다(자동으로 묻지 않는다 — 묻는 창이 업무를 가린다).
 *      폐쇄망에서도 된다. 바깥으로 나가는 통신이 없다.
 *
 * 무엇이 뜨는가
 *   **이 화면을 연 뒤에 생긴** 안 읽은 알림만. 처음 열 때 쌓여 있던 것이 우르르 뜨면
 *   아무도 읽지 않는다 — 그건 종의 숫자가 할 일이다.
 *
 * 내용은 디스크에 남기지 않는다(공용 PC). 띄운 알림 번호만 이 탭의 메모리에 둔다.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Bell, X } from 'lucide-react'
import { notificationApi, type AppNotification } from '@/services/api/shift'

/** 켜고 끈 상태만 저장한다 — 내용이 아니라 이 PC 의 설정이다(교대 PC 는 다음 사람도 쓴다). */
const DESKTOP_KEY = 'soc.desktop-notify'
const SHOW_MS = 12_000
const MAX_ON_SCREEN = 3

/** 눈에 띄어야 하는 종류 — 인계와 재확인은 놓치면 근무가 빈다. */
const URGENT = new Set(['HANDOVER_TRANSFER', 'HANDOVER_REACK', 'IMPORTANT_HANDOVER',
                        'SHIFT_CHANGE'])

const LINK: Record<string, (id: number) => string> = {
  HANDOVER: (id) => `/handovers?id=${id}`,
  TASK: (id) => `/tasks?id=${id}`,
  SCHEDULE: (id) => `/schedules?id=${id}`,
  SHIFT: () => '/shift/inbox',
  ROSTER: () => '/schedules/roster',
}

export function desktopEnabled(): boolean {
  try {
    return localStorage.getItem(DESKTOP_KEY) === '1'
  } catch {
    return false
  }
}

/** 바탕화면 알림을 켠다. 권한은 사람이 눌렀을 때만 묻는다. */
export async function enableDesktop(): Promise<NotificationPermission | 'unsupported'> {
  if (typeof Notification === 'undefined') return 'unsupported'
  const permission = Notification.permission === 'granted'
    ? 'granted'
    : await Notification.requestPermission()
  try {
    localStorage.setItem(DESKTOP_KEY, permission === 'granted' ? '1' : '0')
  } catch {
    /* 저장소를 못 쓰면 이번 세션에만 적용된다 */
  }
  return permission
}

export function disableDesktop(): void {
  try {
    localStorage.setItem(DESKTOP_KEY, '0')
  } catch {
    /* 무시 */
  }
}

export default function NotificationPopups() {
  const navigate = useNavigate()
  const [shown, setShown] = useState<AppNotification[]>([])
  //: 이미 띄운 것 · 처음 열었을 때 쌓여 있던 것. 메모리에만 둔다.
  const seen = useRef<Set<number> | null>(null)

  const { data } = useQuery({
    queryKey: ['notifications', 'popup'],
    queryFn: () => notificationApi.list(true),      // 안 읽은 것만
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    if (!data) return
    if (seen.current === null) {
      // 처음 한 번 — 이미 있던 것은 '본 것'으로 친다. 열자마자 우르르 뜨지 않게.
      seen.current = new Set(data.map((n) => n.id))
      return
    }
    const fresh = data.filter((n) => !seen.current!.has(n.id))
    if (!fresh.length) return
    fresh.forEach((n) => seen.current!.add(n.id))
    setShown((prev) => [...fresh, ...prev].slice(0, MAX_ON_SCREEN))

    if (desktopEnabled() && typeof Notification !== 'undefined'
        && Notification.permission === 'granted') {
      fresh.forEach((n) => {
        try {
          const note = new Notification(n.title, { body: n.body ?? '', tag: `soc-${n.id}` })
          note.onclick = () => {
            window.focus()
            const to = n.link_type && n.link_id ? LINK[n.link_type]?.(n.link_id) : null
            if (to) navigate(to)
            note.close()
          }
        } catch {
          /* 바탕화면 알림이 막혀 있어도 화면 안 팝업은 그대로 뜬다 */
        }
      })
    }
  }, [data, navigate])

  // 일정 시간이 지나면 스스로 사라진다. 긴급한 것은 사람이 닫을 때까지 둔다.
  useEffect(() => {
    if (!shown.length) return
    const timers = shown
      .filter((n) => !URGENT.has(n.type))
      .map((n) => window.setTimeout(
        () => setShown((prev) => prev.filter((x) => x.id !== n.id)), SHOW_MS))
    return () => timers.forEach(window.clearTimeout)
  }, [shown])

  if (!shown.length) return null

  const open = (n: AppNotification) => {
    const to = n.link_type && n.link_id ? LINK[n.link_type]?.(n.link_id) : null
    setShown((prev) => prev.filter((x) => x.id !== n.id))
    navigate(to ?? '/notifications')
  }

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-[22rem] max-w-[calc(100vw-2rem)]"
         role="region" aria-label="새 알림" aria-live="polite">
      {shown.map((n) => {
        const urgent = URGENT.has(n.type)
        return (
          <div key={n.id}
               className={`card shadow-lg border-l-4 p-3 ${urgent ? 'border-l-state-urgent' : 'border-l-brand'}`}>
            <div className="flex items-start gap-2">
              {urgent
                ? <AlertTriangle size={15} className="text-state-urgent shrink-0 mt-0.5" />
                : <Bell size={15} className="text-brand shrink-0 mt-0.5" />}
              <button className="flex-1 min-w-0 text-left" onClick={() => open(n)}>
                <span className="block font-medium break-words">{n.title}</span>
                {n.body && <span className="block text-sm text-ink-muted break-words">{n.body}</span>}
                <span className="block text-sm text-brand mt-0.5">열어 보기 →</span>
              </button>
              <button className="text-ink-faint hover:text-ink shrink-0" aria-label="닫기"
                      onClick={() => setShown((prev) => prev.filter((x) => x.id !== n.id))}>
                <X size={13} />
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
