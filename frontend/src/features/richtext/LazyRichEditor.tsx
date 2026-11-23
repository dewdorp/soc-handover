/**
 * 편집기를 열 때만 불러온다. 편집기(Tiptap · ProseMirror)는 화면 파일보다 크므로,
 * 인계 목록 · 상세 보기만 하는 사람은 받지 않게 한다. 모두 같은 서버에서 받는다(외부 CDN 없음).
 */
import { lazy, Suspense } from 'react'
import type { RichEditorProps } from '@/features/richtext/editorTypes'

const RichEditor = lazy(() => import('@/features/richtext/RichEditor'))

export default function LazyRichEditor(props: RichEditorProps) {
  return (
    <Suspense fallback={
      <div className="rich-editor-loading" role="status">편집기를 불러오는 중…</div>
    }>
      <RichEditor {...props} />
    </Suspense>
  )
}
