/**
 * 그림 첨부 크게 보기.
 *
 * 인수인계에 올린 화면 캡처를 내려받아 열지 않고 그 자리에서 본다. 첨부가 여러 장이면
 * ←/→ 로 넘긴다. Esc 로 닫히되, 뒤에 열린 서랍(Drawer)까지 함께 닫히지 않게 먼저 받아 멈춘다.
 */
import { useEffect, useRef } from 'react'
import { ChevronLeft, ChevronRight, Download, X } from 'lucide-react'
import { adminApi, formatBytes, type AttachmentRow } from '@/services/api/admin'

interface Props {
  images: AttachmentRow[]
  index: number
  onIndex: (index: number) => void
  onClose: () => void
}

export default function ImageLightbox({ images, index, onIndex, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const latest = useRef({ images, index, onIndex, onClose })
  latest.current = { images, index, onIndex, onClose }

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      const { images: list, index: at, onIndex: go, onClose: close } = latest.current
      if (e.key === 'Escape') { e.stopPropagation(); close(); return }
      if (list.length < 2) return
      if (e.key === 'ArrowLeft') { e.stopPropagation(); go((at - 1 + list.length) % list.length) }
      if (e.key === 'ArrowRight') { e.stopPropagation(); go((at + 1) % list.length) }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  const image = images[index]
  if (!image) return null
  const move = (delta: number) => onIndex((index + delta + images.length) % images.length)

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/80 p-3" role="dialog" aria-modal="true"
         aria-label={`그림 보기: ${image.name}`} onClick={onClose}>
      <div className="flex items-center gap-2 text-white/90 text-sm shrink-0"
           onClick={(e) => e.stopPropagation()}>
        <span className="truncate flex-1" title={image.name}>
          {image.name} <span className="text-white/60">· {formatBytes(image.size)}</span>
          {images.length > 1 && <span className="text-white/60 tabular-nums"> · {index + 1}/{images.length}</span>}
        </span>
        <a href={adminApi.attachmentUrl(image.id)} download className="hover:text-white p-1"
           aria-label={`${image.name} 내려받기`}><Download size={18} /></a>
        <button ref={closeRef} className="hover:text-white p-1" aria-label="닫기" onClick={onClose}>
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 min-h-0 flex items-center gap-2" onClick={onClose}>
        {images.length > 1 && (
          <button className="text-white/70 hover:text-white p-2 shrink-0" aria-label="이전 그림"
                  onClick={(e) => { e.stopPropagation(); move(-1) }}><ChevronLeft size={28} /></button>
        )}
        <img src={adminApi.attachmentPreviewUrl(image.id)} alt={image.name}
             className="max-h-full max-w-full m-auto object-contain"
             onClick={(e) => e.stopPropagation()} />
        {images.length > 1 && (
          <button className="text-white/70 hover:text-white p-2 shrink-0" aria-label="다음 그림"
                  onClick={(e) => { e.stopPropagation(); move(1) }}><ChevronRight size={28} /></button>
        )}
      </div>
      <p className="text-center text-white/50 text-xs shrink-0 pt-1">
        빈 곳을 누르거나 Esc 로 닫습니다{images.length > 1 ? ' · ← → 로 넘깁니다' : ''}
      </p>
    </div>
  )
}
