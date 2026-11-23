/**
 * 서식 있는 본문 편집기 — 표 · 스크린샷 · 로그 블록을 쓰기 쉽게.
 *
 * 평소엔 자주 쓰는 것만 보인다(굵게 · 목록 · 체크 · 표 · 그림 · 로그 · 링크 · 되돌리기).
 * 나머지는 '더 보기'에 넣고, 표 · 그림 · 코드 블록 안에 있을 때만 그에 맞는 도구가 나온다.
 *
 * 그림
 *   Ctrl+V(스크린샷) · 끌어다 놓기 · 파일 선택 → 곧바로 서버에 '초안'으로 올리고 그 주소를 넣는다.
 *   Base64 로 본문에 넣지 않는다. 다른 웹페이지에서 복사한 외부 그림은 넣지 않는다.
 * 붙여넣기
 *   Excel · 웹의 표는 표로 들어온다(그림으로 바뀌지 않게, 표가 있으면 표를 먼저 쓴다).
 *   붙여 넣은 HTML 의 style · 스크립트 · 외부 그림은 버린다.
 *
 * 저장하는 구조는 서버 허용 목록에 맞춰(normalizeDoc) 내보낸다. 보안의 근거는 서버 검사다.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { Color, TextStyle } from '@tiptap/extension-text-style'
import Highlight from '@tiptap/extension-highlight'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Placeholder } from '@tiptap/extensions'
import {
  Bold, Code, Ellipsis, Eye, EyeOff, Heading2, Heading3, Highlighter, ImagePlus, Italic, Link2,
  List, ListOrdered, ListTodo, Minus, Palette, Quote, Redo2, SquareCode, Strikethrough, Table2,
  Underline as UnderlineIcon, Undo2,
} from 'lucide-react'
import RichView from '@/features/richtext/RichView'
import {
  CODE_LANGUAGES, HIGHLIGHT_COLORS, IMAGE_WIDTHS, TEXT_COLORS, inlineIdOf, isSafeLink,
  normalizeDoc, textToDoc, type RichDoc, type RichNode,
} from '@/features/richtext/doc'
import type { RichEditorProps } from '@/features/richtext/editorTypes'
import { ApiRequestError } from '@/services/api/client'
import { inlineApi } from '@/services/api/inline'

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']

/** 그림 너비(%) · 설명(alt)을 담는 그림 요소. 외부 주소 · Base64 는 받지 않는다. */
const SocImage = Image.extend({
  addAttributes() {
    return {
      src: { default: null },
      alt: { default: null },
      title: { default: null },
      width: {
        default: null,
        parseHTML: (el) => {
          const w = Number(el.getAttribute('data-width'))
          return (IMAGE_WIDTHS as readonly number[]).includes(w) ? w : null
        },
        renderHTML: (attrs) => (attrs.width ? { 'data-width': attrs.width, style: `width:${attrs.width}%` } : {}),
      },
    }
  },
}).configure({ inline: false, allowBase64: false })

/** 붙여 넣은 HTML 정리 — 스크립트 · 스타일 · 외부 그림을 버린다(표 · 굵게 · 목록은 남긴다) */
function cleanPastedHtml(html: string): string {
  const parsed = new DOMParser().parseFromString(html, 'text/html')   // 스크립트를 실행하지 않는다
  parsed.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach((el) => el.remove())
  parsed.querySelectorAll('img').forEach((img) => {
    if (inlineIdOf(img.getAttribute('src')) === null) img.remove()
  })
  parsed.querySelectorAll('*').forEach((el) => {
    for (const attr of [...el.attributes]) {
      if (attr.name === 'style' || attr.name === 'class' || attr.name.startsWith('on')) el.removeAttribute(attr.name)
    }
  })
  return parsed.body.innerHTML
}

export default function RichEditor({
  value, fallbackText, onChange, variant = 'full', placeholder, ariaLabel = '본문', onBusyChange, autoFocus,
  onSubmitShortcut,
}: RichEditorProps) {
  const submitRef = useRef(onSubmitShortcut)
  submitRef.current = onSubmitShortcut
  const [uploading, setUploading] = useState(0)
  const [notice, setNotice] = useState<{ text: string; bad: boolean } | null>(null)
  const [preview, setPreview] = useState(false)
  const [current, setCurrent] = useState<RichDoc | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const editorRef = useRef<Editor | null>(null)
  const compact = variant === 'compact'

  useEffect(() => { onBusyChange?.(uploading > 0) }, [uploading, onBusyChange])

  const emit = useCallback((editor: Editor) => {
    const { doc, dropped } = normalizeDoc(editor.getJSON() as RichNode)
    setCurrent(doc)
    onChange(doc)
    if (dropped) setNotice({ text: `넣을 수 없는 요소 ${dropped}개(외부 그림 · 알 수 없는 서식)는 저장하지 않습니다.`, bad: false })
  }, [onChange])

  /** 그림 파일들을 올리고 그 자리에 넣는다. 위치를 주면 거기에(끌어다 놓기). */
  const uploadImages = useCallback(async (files: File[], at?: number) => {
    const editor = editorRef.current
    if (!editor) return
    const images = files.filter((f) => IMAGE_TYPES.includes(f.type))
    if (!images.length) {
      setNotice({ text: 'PNG · JPG · GIF · WEBP 그림만 본문에 넣을 수 있습니다. 다른 파일은 첨부로 올리십시오.', bad: true })
      return
    }
    setNotice(null)
    let pos = at
    for (const file of images) {
      setUploading((n) => n + 1)
      try {
        const got = await inlineApi.upload(file)
        const node = { type: 'image', attrs: { src: got.url, alt: null, width: null } }
        if (pos !== undefined) {
          editor.chain().focus().insertContentAt(pos, node).run()
          pos += 1
        } else {
          editor.chain().focus().insertContent(node).run()
        }
      } catch (err) {
        setNotice({ text: err instanceof ApiRequestError ? err.message : '그림을 올리지 못했습니다. 다시 시도하십시오.', bad: true })
      } finally {
        setUploading((n) => n - 1)
      }
    }
  }, [])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        link: {
          openOnClick: false,
          autolink: true,
          defaultProtocol: 'https',
          // http · https · mailto 만 링크로 만든다(javascript: 등은 글로 남는다)
          isAllowedUri: (url) => isSafeLink(url),
        },
      }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Table.configure({ resizable: !compact, lastColumnResizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      SocImage,
      Placeholder.configure({ placeholder: placeholder ?? (compact ? '댓글을 입력하십시오 — 스크린샷은 Ctrl+V' : '내용을 입력하십시오 — 스크린샷은 Ctrl+V, 표는 Excel 에서 복사해 붙여 넣어도 됩니다') }),
    ],
    content: (value as object | null | undefined) ?? textToDoc(fallbackText ?? ''),
    autofocus: autoFocus ? 'end' : false,
    shouldRerenderOnTransaction: true,
    editorProps: {
      attributes: { 'aria-label': ariaLabel, role: 'textbox', 'aria-multiline': 'true', spellcheck: 'false' },
      transformPastedHTML: cleanPastedHtml,
      handleKeyDown: (_view, event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && submitRef.current) {
          event.preventDefault()
          submitRef.current()
          return true
        }
        return false
      },
      handlePaste: (_view, event) => {
        const data = event.clipboardData
        if (!data) return false
        // Excel · 웹 표는 표로 넣는다. Excel 은 표와 함께 그림도 클립보드에 넣으므로 표를 먼저 본다.
        const html = data.getData('text/html')
        if (html && /<table[\s>]/i.test(html)) return false
        const files = [...data.files].filter((f) => f.type.startsWith('image/'))
        if (!files.length) return false
        event.preventDefault()
        void uploadImages(files)
        return true
      },
      handleDrop: (view, event, _slice, moved) => {
        if (moved) return false
        const files = [...(event.dataTransfer?.files ?? [])]
        if (!files.length) return false
        event.preventDefault()
        const at = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos
        void uploadImages(files, at)
        return true
      },
    },
    onCreate: ({ editor: e }) => { editorRef.current = e; setCurrent(normalizeDoc(e.getJSON() as RichNode).doc) },
    onUpdate: ({ editor: e }) => emit(e),
  })

  if (!editor) return <div className="rich-editor-loading">편집기를 준비하는 중…</div>

  return (
    <div className={`rich-editor ${compact ? 'compact' : ''}`}>
      <Toolbar editor={editor} compact={compact} preview={preview}
               onPreview={() => setPreview((v) => !v)} onPickImage={() => fileInput.current?.click()} />
      <ContextBar editor={editor} />
      {preview ? (
        <div className="rich-preview" aria-label="미리보기">
          <RichView doc={current} empty="(아직 내용이 없습니다)" />
        </div>
      ) : (
        <EditorContent editor={editor} className="rich-content" />
      )}
      <input ref={fileInput} type="file" accept={IMAGE_TYPES.join(',')} multiple hidden
             onChange={(e) => { const fs = [...(e.target.files ?? [])]; e.target.value = ''; if (fs.length) void uploadImages(fs) }} />
      {(uploading > 0 || notice) && (
        <div className="rich-status" role={notice?.bad ? 'alert' : 'status'}>
          {uploading > 0 && <span>그림 올리는 중… ({uploading})</span>}
          {notice && <span className={notice.bad ? 'text-state-urgent' : 'text-ink-muted'}>{notice.text}</span>}
          {notice && <button type="button" className="btn btn-sm" onClick={() => setNotice(null)}>닫기</button>}
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- 도구 막대

function Tool({ label, keys, active, disabled, onClick, children }: {
  label: string; keys?: string; active?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode
}) {
  return (
    <button type="button" className={`rt-tool ${active ? 'is-active' : ''}`} onClick={onClick}
            disabled={disabled} aria-pressed={active} aria-label={label}
            title={keys ? `${label} (${keys})` : label} onMouseDown={(e) => e.preventDefault()}>
      {children}
    </button>
  )
}

function Toolbar({ editor, compact, preview, onPreview, onPickImage }: {
  editor: Editor; compact: boolean; preview: boolean; onPreview: () => void; onPickImage: () => void
}) {
  const [more, setMore] = useState(false)
  const [tableForm, setTableForm] = useState(false)
  const [linkForm, setLinkForm] = useState(false)
  const chain = () => editor.chain().focus()
  const off = preview
  return (
    <div className="rt-toolbar" role="toolbar" aria-label="서식 도구">
      <Tool label="굵게" keys="Ctrl+B" active={editor.isActive('bold')} disabled={off}
            onClick={() => chain().toggleBold().run()}><Bold size={14} /></Tool>
      <Tool label="글머리 목록" keys="Ctrl+Shift+8" active={editor.isActive('bulletList')} disabled={off}
            onClick={() => chain().toggleBulletList().run()}><List size={14} /></Tool>
      <Tool label="번호 목록" keys="Ctrl+Shift+7" active={editor.isActive('orderedList')} disabled={off}
            onClick={() => chain().toggleOrderedList().run()}><ListOrdered size={14} /></Tool>
      {!compact && (
        <Tool label="체크리스트" keys="Ctrl+Shift+9" active={editor.isActive('taskList')} disabled={off}
              onClick={() => chain().toggleTaskList().run()}><ListTodo size={14} /></Tool>
      )}
      <span className="rt-sep" />
      <Tool label="표 넣기" active={tableForm} disabled={off || editor.isActive('table')}
            onClick={() => { setTableForm((v) => !v); setLinkForm(false) }}><Table2 size={14} /></Tool>
      <Tool label="그림 넣기 (스크린샷은 Ctrl+V)" disabled={off} onClick={onPickImage}><ImagePlus size={14} /></Tool>
      <Tool label="로그 · 코드 블록" keys="Ctrl+Alt+C" active={editor.isActive('codeBlock')} disabled={off}
            onClick={() => chain().toggleCodeBlock({ language: 'log' }).run()}><SquareCode size={14} /></Tool>
      <Tool label="링크" keys="Ctrl+K" active={editor.isActive('link') || linkForm} disabled={off}
            onClick={() => { setLinkForm((v) => !v); setTableForm(false) }}><Link2 size={14} /></Tool>
      <span className="rt-sep" />
      <Tool label="실행 취소" keys="Ctrl+Z" disabled={off || !editor.can().undo()}
            onClick={() => chain().undo().run()}><Undo2 size={14} /></Tool>
      <Tool label="다시 실행" keys="Ctrl+Y" disabled={off || !editor.can().redo()}
            onClick={() => chain().redo().run()}><Redo2 size={14} /></Tool>
      <Tool label="더 보기" active={more} disabled={off} onClick={() => setMore((v) => !v)}><Ellipsis size={14} /></Tool>
      <span className="flex-1" />
      <Tool label={preview ? '편집으로 돌아가기' : '미리보기'} active={preview} onClick={onPreview}>
        {preview ? <EyeOff size={14} /> : <Eye size={14} />}<span className="text-xs">{preview ? '편집' : '미리보기'}</span>
      </Tool>

      {more && !off && (
        <div className="rt-more" role="group" aria-label="더 많은 서식">
          <Tool label="기울임" keys="Ctrl+I" active={editor.isActive('italic')} onClick={() => chain().toggleItalic().run()}><Italic size={14} /></Tool>
          <Tool label="밑줄" keys="Ctrl+U" active={editor.isActive('underline')} onClick={() => chain().toggleUnderline().run()}><UnderlineIcon size={14} /></Tool>
          <Tool label="취소선" keys="Ctrl+Shift+S" active={editor.isActive('strike')} onClick={() => chain().toggleStrike().run()}><Strikethrough size={14} /></Tool>
          <Tool label="글 속 코드" keys="Ctrl+E" active={editor.isActive('code')} onClick={() => chain().toggleCode().run()}><Code size={14} /></Tool>
          <Tool label="제목(크게)" keys="Ctrl+Alt+2" active={editor.isActive('heading', { level: 2 })} onClick={() => chain().toggleHeading({ level: 2 }).run()}><Heading2 size={14} /></Tool>
          <Tool label="제목(작게)" keys="Ctrl+Alt+3" active={editor.isActive('heading', { level: 3 })} onClick={() => chain().toggleHeading({ level: 3 }).run()}><Heading3 size={14} /></Tool>
          <Tool label="인용" keys="Ctrl+Shift+B" active={editor.isActive('blockquote')} onClick={() => chain().toggleBlockquote().run()}><Quote size={14} /></Tool>
          <Tool label="구분선" onClick={() => chain().setHorizontalRule().run()}><Minus size={14} /></Tool>
          {compact && <Tool label="체크리스트" active={editor.isActive('taskList')} onClick={() => chain().toggleTaskList().run()}><ListTodo size={14} /></Tool>}
          <span className="rt-sep" />
          <span className="rt-label"><Palette size={12} /> 글자색</span>
          {TEXT_COLORS.map((c) => (
            <button key={c.value} type="button" className="rt-swatch" style={{ backgroundColor: c.value }}
                    title={`글자색: ${c.label}`} aria-label={`글자색 ${c.label}`}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => chain().setColor(c.value).run()} />
          ))}
          <button type="button" className="btn btn-sm" onMouseDown={(e) => e.preventDefault()}
                  onClick={() => chain().unsetColor().run()}>색 없음</button>
          <span className="rt-label"><Highlighter size={12} /> 강조</span>
          {HIGHLIGHT_COLORS.map((c) => (
            <button key={c.value} type="button" className="rt-swatch" style={{ backgroundColor: c.value }}
                    title={`강조: ${c.label}`} aria-label={`강조 ${c.label}`}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => chain().toggleHighlight({ color: c.value }).run()} />
          ))}
        </div>
      )}
      {tableForm && !off && <TableForm onInsert={(rows, cols, header) => {
        chain().insertTable({ rows, cols, withHeaderRow: header }).run()
        // focus() 는 다음 화면 갱신 때 커서를 돌려준다 — 그 사이 친 첫 글자가 사라지지 않게 바로 옮긴다
        editor.view.focus()
        setTableForm(false)
      }} onCancel={() => setTableForm(false)} />}
      {linkForm && !off && <LinkForm editor={editor} onDone={() => setLinkForm(false)} />}
    </div>
  )
}

function TableForm({ onInsert, onCancel }: { onInsert: (r: number, c: number, h: boolean) => void; onCancel: () => void }) {
  const [rows, setRows] = useState(3)
  const [cols, setCols] = useState(4)
  const [header, setHeader] = useState(true)
  return (
    <div className="rt-popover" role="group" aria-label="표 넣기">
      <label>행 <input type="number" className="input input-sm w-14" min={1} max={30} value={rows}
                       aria-label="행 수" onChange={(e) => setRows(Math.max(1, Math.min(30, Number(e.target.value) || 1)))} /></label>
      <label>열 <input type="number" className="input input-sm w-14" min={1} max={12} value={cols}
                       aria-label="열 수" onChange={(e) => setCols(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} /></label>
      <label className="inline-flex items-center gap-1"><input type="checkbox" checked={header}
             onChange={(e) => setHeader(e.target.checked)} /> 첫 행은 머리글</label>
      <button type="button" className="btn btn-sm btn-primary" onClick={() => onInsert(rows, cols, header)}>표 넣기</button>
      <button type="button" className="btn btn-sm" onClick={onCancel}>취소</button>
    </div>
  )
}

function LinkForm({ editor, onDone }: { editor: Editor; onDone: () => void }) {
  const [href, setHref] = useState(String(editor.getAttributes('link').href ?? ''))
  const [error, setError] = useState('')
  const apply = () => {
    const url = href.trim()
    if (!url) { editor.chain().focus().extendMarkRange('link').unsetLink().run(); editor.view.focus(); onDone(); return }
    const full = /^[a-z]+:/i.test(url) ? url : `https://${url}`
    if (!isSafeLink(full)) { setError('http · https · mailto 주소만 링크로 걸 수 있습니다.'); return }
    if (editor.state.selection.empty && !editor.isActive('link')) {
      editor.chain().focus().insertContent({ type: 'text', text: url, marks: [{ type: 'link', attrs: { href: full } }] }).run()
    } else {
      editor.chain().focus().extendMarkRange('link').setLink({ href: full }).run()
    }
    editor.view.focus()   // 표 넣기와 같다 — 주소 칸을 닫자마자 치는 글자가 편집기로 가게
    onDone()
  }
  return (
    <div className="rt-popover" role="group" aria-label="링크">
      <input className="input input-sm w-72" placeholder="https://" value={href} aria-label="링크 주소" autoFocus
             onChange={(e) => { setHref(e.target.value); setError('') }}
             onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); apply() } if (e.key === 'Escape') onDone() }} />
      <button type="button" className="btn btn-sm btn-primary" onClick={apply}>적용</button>
      {editor.isActive('link') && (
        <button type="button" className="btn btn-sm" onClick={() => { editor.chain().focus().extendMarkRange('link').unsetLink().run(); onDone() }}>링크 해제</button>
      )}
      <button type="button" className="btn btn-sm" onClick={onDone}>취소</button>
      {error && <span className="text-state-urgent text-xs">{error}</span>}
    </div>
  )
}

/** 표 · 그림 · 코드 블록 안에 있을 때만 나오는 도구 */
function ContextBar({ editor }: { editor: Editor }) {
  const chain = () => editor.chain().focus()
  if (editor.isActive('image')) {
    const attrs = editor.getAttributes('image')
    const id = inlineIdOf(attrs.src)
    return (
      <div className="rt-context" role="group" aria-label="그림 도구">
        <span className="rt-label">그림 크기</span>
        {IMAGE_WIDTHS.map((w) => (
          <button key={w} type="button" className={`btn btn-sm ${(attrs.width ?? 100) === w ? 'btn-primary' : ''}`}
                  onClick={() => chain().updateAttributes('image', { width: w === 100 ? null : w }).run()}>{w}%</button>
        ))}
        <input className="input input-sm w-56" placeholder="그림 설명(캡션)" aria-label="그림 설명"
               value={String(attrs.alt ?? '')} maxLength={300}
               onChange={(e) => editor.chain().updateAttributes('image', { alt: e.target.value || null }).run()} />
        {id !== null && <a className="btn btn-sm" href={`/api/v1/attachments/${id}/download`} download>원본 받기</a>}
        <button type="button" className="btn btn-sm" onClick={() => chain().deleteSelection().run()}>그림 빼기</button>
      </div>
    )
  }
  if (editor.isActive('codeBlock')) {
    return (
      <div className="rt-context" role="group" aria-label="코드 블록 도구">
        <span className="rt-label">종류</span>
        <select className="input input-sm" aria-label="코드 종류" value={String(editor.getAttributes('codeBlock').language ?? 'log')}
                onChange={(e) => chain().updateAttributes('codeBlock', { language: e.target.value }).run()}>
          {CODE_LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
        </select>
        <span className="text-xs text-ink-faint">붙여 넣은 로그는 글자 그대로 저장됩니다(실행되지 않음).</span>
      </div>
    )
  }
  if (editor.isActive('table')) {
    const b = (label: string, run: () => boolean, can = true) => (
      <button type="button" className="btn btn-sm" disabled={!can} onMouseDown={(e) => e.preventDefault()}
              onClick={() => run()}>{label}</button>
    )
    return (
      <div className="rt-context" role="group" aria-label="표 도구">
        {b('위에 행', () => chain().addRowBefore().run())}
        {b('아래에 행', () => chain().addRowAfter().run())}
        {b('왼쪽에 열', () => chain().addColumnBefore().run())}
        {b('오른쪽에 열', () => chain().addColumnAfter().run())}
        <span className="rt-sep" />
        {b('행 삭제', () => chain().deleteRow().run())}
        {b('열 삭제', () => chain().deleteColumn().run())}
        <span className="rt-sep" />
        {b('셀 합치기', () => chain().mergeCells().run(), editor.can().mergeCells())}
        {b('셀 나누기', () => chain().splitCell().run(), editor.can().splitCell())}
        {b('머리글 행', () => chain().toggleHeaderRow().run())}
        <span className="rt-sep" />
        {b('표 삭제', () => chain().deleteTable().run())}
      </div>
    )
  }
  return null
}
