/**
 * 본문 그림 크게 보기 — 화면에 맞춤 / 원래 크기, 원본 받기, Esc · 바깥 눌러 닫기.
 * 원본 받기는 일반 첨부 받기와 같은 길(/download)이라 권한 판정 · 감사 기록이 그대로 적용된다.
 */
import { useState } from 'react'
import { Download, Maximize2, Minimize2, X } from 'lucide-react'
import { inlineIdOf } from '@/features/richtext/doc'
import { useEscape } from '@/hooks/useHotkeys'

export default function ImageLightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const [actual, setActual] = useState(false)
  const id = inlineIdOf(src)
  // Esc 는 이 창만 닫는다 — 먼저 받아 멈춰서, 뒤에 있는 인수인계 상세까지 닫히지 않게 한다.
  useEscape(onClose)
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/80" role="dialog" aria-modal="true"
         aria-label={alt ? `그림 크게 보기: ${alt}` : '그림 크게 보기'} onClick={onClose}>
      <div className="flex items-center gap-2 px-3 py-2 text-white text-sm" onClick={(e) => e.stopPropagation()}>
        <span className="flex-1 truncate">{alt || '본문 그림'}</span>
        <button type="button" className="btn btn-sm" onClick={() => setActual((v) => !v)}>
          {actual ? <><Minimize2 size={12} /> 화면에 맞춤</> : <><Maximize2 size={12} /> 원래 크기</>}
        </button>
        {id !== null && (
          <a className="btn btn-sm" href={`/api/v1/attachments/${id}/download`} download>
            <Download size={12} /> 원본 받기
          </a>
        )}
        <button type="button" className="btn btn-sm" onClick={onClose} aria-label="닫기"><X size={12} /> 닫기</button>
      </div>
      <div className="flex-1 overflow-auto flex items-start justify-center p-3" onClick={onClose}>
        <img src={src} alt={alt || '본문 그림'} onClick={(e) => e.stopPropagation()}
             className={actual ? 'max-w-none' : 'max-w-full max-h-full object-contain'} />
      </div>
    </div>
  )
}
