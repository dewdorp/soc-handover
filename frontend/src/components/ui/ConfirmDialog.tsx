/**
 * 되돌리기 어려운 작업 앞의 확인창.
 *
 * window.confirm 은 앱을 품은 창(데스크톱 앱 안의 브라우저·임베드)에서 뜨지 않고 곧바로
 * '취소'로 끝나는 경우가 있어, 누른 사람은 아무 일도 안 일어난 이유를 알 수 없다. 앱 안에서 그린다.
 * 기본 포커스는 '취소' — Enter 를 습관처럼 눌러 인계·가져오기가 실행되지 않게 한다.
 */
import { useEffect, useRef, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface Props {
  title: string
  children?: ReactNode
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmDialog({ title, children, confirmLabel, danger, busy, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const latestCancel = useRef(onCancel)
  latestCancel.current = onCancel

  useEffect(() => {
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') latestCancel.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4"
         role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" onClick={onCancel}>
      <div className="card w-[440px] max-w-full shadow-xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-2">
          <AlertTriangle size={18} className={`shrink-0 mt-0.5 ${danger ? 'text-state-urgent' : 'text-state-check'}`} />
          <h2 id="confirm-title" className="font-medium">{title}</h2>
        </div>
        {children && <div className="text-base text-ink-muted space-y-1">{children}</div>}
        <div className="flex justify-end gap-2">
          <button ref={cancelRef} className="btn" onClick={onCancel}>취소</button>
          <button className={`btn ${danger ? 'text-state-urgent' : 'btn-primary'}`}
                  disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}
