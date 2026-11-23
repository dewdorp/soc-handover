/**
 * 저장하지 않은 글이 있을 때 화면을 떠나기 전에 묻는다.
 *
 * · 다른 메뉴로 이동(앱 안의 이동) → 확인 창
 * · 새로고침 · 탭 닫기 → 브라우저 기본 경고
 * 표 · 스크린샷 · 로그를 한참 붙여 넣은 글이 실수 한 번에 사라지면 다시 만들기 어렵다.
 */
import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'
import ConfirmDialog from '@/components/ui/ConfirmDialog'

export function useUnsavedGuard(dirty: boolean, what = '작성 중인 내용') {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && nextLocation.pathname !== '/login' && nextLocation.pathname !== '/change-password'
    && (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search))

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const dialog = blocker.state === 'blocked' ? (
    <ConfirmDialog title="저장하지 않고 나갈까요?" confirmLabel="나가기" danger
                   onConfirm={() => blocker.proceed?.()} onCancel={() => blocker.reset?.()}>
      {what}을(를) 아직 저장하지 않았습니다. 나가면 사라집니다.
    </ConfirmDialog>
  ) : null

  return dialog
}
