/**
 * 편집기 props — 편집기 본체(Tiptap)를 불러오지 않고도 쓸 수 있게 따로 둔다.
 * 보는 화면 · 목록은 이 타입만 가져가고, 편집기는 열 때 늦게 받는다(LazyRichEditor).
 */
import type { RichDoc, RichNode } from '@/features/richtext/doc'

export interface RichEditorProps {
  /** 서식 구조. 없으면 fallbackText 를 문단으로 바꿔 시작한다(서식 없는 옛 글). */
  value: RichNode | null | undefined
  fallbackText?: string | null
  /** 바뀔 때마다 — 서버 허용 목록에 맞춘 구조 */
  onChange: (doc: RichDoc) => void
  /** full = 인계 · 운영 지식 · 할일, compact = 댓글(도구가 적고 낮다) */
  variant?: 'full' | 'compact'
  placeholder?: string
  ariaLabel?: string
  /** 그림을 올리는 중인지 알려 준다 — 올리는 동안 저장 단추를 막는 데 쓴다 */
  onBusyChange?: (busy: boolean) => void
  autoFocus?: boolean
  /** Ctrl+Enter(맥은 Cmd+Enter) — 댓글 등록 등 */
  onSubmitShortcut?: () => void
}
