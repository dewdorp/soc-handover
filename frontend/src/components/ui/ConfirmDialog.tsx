/**
 * 되돌리기 어려운 작업 앞의 확인창.
 *
 * window.confirm · window.prompt 는 앱을 품은 창(데스크톱 앱 안의 브라우저·임베드)에서 뜨지 않고
 * 곧바로 '취소'로 끝나는 경우가 있어, 누른 사람은 아무 일도 안 일어난 이유를 알 수 없다. 앱 안에서 그린다.
 * 기본 포커스는 '취소' — Enter 를 습관처럼 눌러 인계·가져오기가 실행되지 않게 한다.
 * input 을 주면 사유 입력 칸이 생기고(삭제 사유 등), required 면 비어 있는 동안 확인이 잠긴다.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface Props {
  title: string
  children?: ReactNode
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  input?: { label: string; placeholder?: string; required?: boolean }
  onConfirm: (value: string) => void
  onCancel: () => void
}

export default function ConfirmDialog({ title, children, confirmLabel, danger, busy, input, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const latestCancel = useRef(onCancel)
  latestCancel.current = onCancel
  const [value, setValue] = useState('')
  const blocked = Boolean(input?.required && !value.trim())

  useEffect(() => {
    // 입력 칸이 있으면 거기에 바로 쓸 수 있게, 없으면 '취소'에
    ;(inputRef.current ?? cancelRef.current)?.focus()
    // 뒤에 열린 창·패널까지 Esc 로 닫히지 않게 먼저 받아서 멈춘다(capture)
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      latestCancel.current()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
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
        {input && (
          <label className="block space-y-0.5">
            <span className="text-ink-muted">{input.label}{input.required && <span className="text-state-urgent"> *</span>}</span>
            <textarea ref={inputRef} className="input w-full h-16 py-1 resize-y" value={value}
                      placeholder={input.placeholder} onChange={(e) => setValue(e.target.value)} />
          </label>
        )}
        <div className="flex justify-end gap-2">
          <button ref={cancelRef} className="btn" onClick={onCancel}>취소</button>
          <button className={`btn ${danger ? 'text-state-urgent' : 'btn-primary'}`}
                  disabled={busy || blocked} onClick={() => onConfirm(value.trim())}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}
