/** 단축키 도움말(?) — 한/영 상태와 상관없이 같은 키로 동작한다. */
import { useEffect } from 'react'
import { Keyboard, X } from 'lucide-react'
import { SHORTCUTS } from '@/hooks/useHotkeys'

export default function ShortcutHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" onClick={onClose}
         role="dialog" aria-modal="true" aria-labelledby="shortcut-title">
      <div className="card w-[480px] max-w-full shadow-xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <Keyboard size={16} className="text-ink-faint" />
          <h2 id="shortcut-title" className="font-medium flex-1">키보드 단축키</h2>
          <button onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink"><X size={16} /></button>
        </div>
        {SHORTCUTS.map((g) => (
          <section key={g.group}>
            <h3 className="text-sm text-ink-muted mb-1">{g.group}</h3>
            <dl className="grid grid-cols-[7rem_1fr] gap-y-1 text-sm">
              {g.items.map((s) => (
                <div key={s.keys} className="contents">
                  <dt><kbd className="border border-surface-border rounded px-1.5 bg-surface-sunken tabular-nums">{s.keys}</kbd></dt>
                  <dd>{s.action}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        <p className="text-xs text-ink-faint">
          한글 입력 상태에서도 같은 키로 동작합니다. 글자를 입력하는 중이거나 창이 열려 있으면 한 글자 단축키는 쉽니다.
          Ctrl+N · Ctrl+Shift+T 는 브라우저가 새 창·닫은 탭에 쓰는 키라 Alt+N · Alt+T 로 바꿨습니다.
        </p>
      </div>
    </div>
  )
}
