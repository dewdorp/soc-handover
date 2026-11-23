/**
 * 서식 있는 본문의 문서 구조 — 편집기와 보기 화면이 같이 쓰는 약속.
 *
 * 서버(backend/app/core/richdoc.py)가 허용 목록으로 다시 검사한다. 여기의 normalizeDoc 은
 * '저장하기 전에 서버가 거절할 것을 미리 걸러' 사용자가 422 를 만나지 않게 하는 것이다 —
 * 보안의 근거는 서버 검사다.
 */

export interface RichMark {
  type: string
  attrs?: Record<string, unknown>
}

export interface RichNode {
  type: string
  attrs?: Record<string, unknown>
  content?: RichNode[]
  marks?: RichMark[]
  text?: string
}

export interface RichDoc extends RichNode {
  type: 'doc'
}

/** 글자색 — 서버 TEXT_COLORS 와 같아야 한다 */
export const TEXT_COLORS: { value: string; label: string }[] = [
  { value: '#dc2626', label: '빨강' },
  { value: '#ea580c', label: '주황' },
  { value: '#16a34a', label: '초록' },
  { value: '#2563eb', label: '파랑' },
  { value: '#7c3aed', label: '보라' },
  { value: '#6b7280', label: '회색' },
]

/** 강조색 — 서버 HIGHLIGHT_COLORS 와 같아야 한다 */
export const HIGHLIGHT_COLORS: { value: string; label: string }[] = [
  { value: '#fef08a', label: '노랑' },
  { value: '#fecaca', label: '분홍' },
  { value: '#bbf7d0', label: '연두' },
  { value: '#bfdbfe', label: '하늘' },
]

/** 코드 · 로그 블록 종류 — 이름표만 붙인다(실행하지 않는다). 서버 CODE_LANGUAGES 와 같다. */
export const CODE_LANGUAGES: { value: string; label: string }[] = [
  { value: 'log', label: '로그' },
  { value: 'http', label: 'HTTP' },
  { value: 'json', label: 'JSON' },
  { value: 'sql', label: 'SQL' },
  { value: 'powershell', label: 'PowerShell' },
  { value: 'bash', label: 'Shell' },
  { value: 'regex', label: '정규표현식' },
  { value: 'xml', label: 'XML' },
  { value: 'python', label: 'Python' },
  { value: 'plain', label: '일반 텍스트' },
]
export const CODE_LANGUAGE_LABEL: Record<string, string> =
  Object.fromEntries(CODE_LANGUAGES.map((x) => [x.value, x.label]))

/** 그림 너비(%) — 서버 IMAGE_WIDTHS 와 같다 */
export const IMAGE_WIDTHS = [25, 50, 75, 100] as const

const INLINE_SRC = /^\/api\/v1\/attachments\/(\d{1,12})\/inline$/
const SAFE_LINK = /^(https?:\/\/|mailto:)/i

export const inlineIdOf = (src: unknown): number | null => {
  const m = typeof src === 'string' ? INLINE_SRC.exec(src) : null
  return m ? Number(m[1]) : null
}
export const isSafeLink = (href: unknown): href is string =>
  typeof href === 'string' && SAFE_LINK.test(href.trim())

const NODE_ATTRS: Record<string, string[]> = {
  heading: ['level'],
  orderedList: ['start'],
  taskItem: ['checked'],
  codeBlock: ['language'],
  image: ['src', 'alt', 'title', 'width'],
  tableHeader: ['colspan', 'rowspan', 'colwidth'],
  tableCell: ['colspan', 'rowspan', 'colwidth'],
}
const KNOWN_NODES = new Set([
  'doc', 'paragraph', 'text', 'hardBreak', 'horizontalRule', 'heading', 'bulletList', 'orderedList',
  'listItem', 'taskList', 'taskItem', 'blockquote', 'codeBlock', 'image', 'table', 'tableRow',
  'tableHeader', 'tableCell',
])
const KNOWN_MARKS = new Set(['bold', 'italic', 'underline', 'strike', 'code', 'link', 'textStyle', 'highlight'])
const TEXT_COLOR_SET = new Set(TEXT_COLORS.map((c) => c.value))
const HIGHLIGHT_SET = new Set(HIGHLIGHT_COLORS.map((c) => c.value))
const LANG_SET = new Set(['', ...CODE_LANGUAGES.map((c) => c.value)])

/**
 * 저장하기 전에 서버 허용 목록에 맞춘다.
 *  · 외부 주소 그림(다른 웹페이지에서 복사한 그림 등)은 빼고 그 자리를 비운다
 *  · 팔레트 밖 글자색 · 강조색, 위험한 링크, 모르는 서식은 떼어 낸다(글은 남긴다)
 *  · 제목 1 · 4~6 은 제목 2 · 3 으로 맞춘다
 * 빠진 것이 있으면 dropped 에 센다 — 화면이 '외부 그림 n개는 넣지 않았습니다'라고 알린다.
 */
export function normalizeDoc(doc: RichNode): { doc: RichDoc; dropped: number } {
  let dropped = 0
  const walk = (node: RichNode): RichNode | null => {
    if (!KNOWN_NODES.has(node.type)) {
      // 모르는 블록은 글만 살린다(예: 다른 편집기의 특수 요소)
      const text = collectText(node)
      dropped += 1
      return text ? { type: 'paragraph', content: [{ type: 'text', text }] } : null
    }
    if (node.type === 'image' && inlineIdOf(node.attrs?.src) === null) {
      dropped += 1
      return null
    }
    const out: RichNode = { type: node.type }
    const allowed = NODE_ATTRS[node.type]
    if (allowed && node.attrs) {
      const attrs: Record<string, unknown> = {}
      for (const key of allowed) {
        const v = node.attrs[key]
        if (v === undefined || v === null) continue
        if (node.type === 'heading' && key === 'level') attrs.level = Number(v) <= 2 ? 2 : 3
        else if (node.type === 'codeBlock' && key === 'language') attrs.language = LANG_SET.has(String(v)) ? v : 'plain'
        else if (node.type === 'image' && key === 'width') { if ((IMAGE_WIDTHS as readonly number[]).includes(Number(v))) attrs.width = Number(v) }
        else if ((key === 'alt' || key === 'title') && typeof v === 'string') attrs[key] = v.slice(0, 300)
        else if (key === 'colwidth') { if (Array.isArray(v) && v.every((x) => typeof x === 'number')) attrs.colwidth = v.map((x) => Math.min(2000, Math.max(20, Math.round(x)))) }
        else if (key === 'colspan' || key === 'rowspan') attrs[key] = Math.max(1, Math.min(key === 'colspan' ? 50 : 500, Number(v) || 1))
        else if (key === 'start') attrs.start = Math.max(1, Math.min(10000, Number(v) || 1))
        else attrs[key] = v
      }
      if (node.type === 'heading' && !attrs.level) attrs.level = 2
      if (Object.keys(attrs).length) out.attrs = attrs
    } else if (node.type === 'heading') {
      out.attrs = { level: 2 }
    }
    if (node.type === 'text') {
      if (!node.text) return null
      out.text = node.text
      const marks = (node.marks ?? []).flatMap((m): RichMark[] => {
        if (!KNOWN_MARKS.has(m.type)) { dropped += 1; return [] }
        if (m.type === 'link') return isSafeLink(m.attrs?.href) ? [{ type: 'link', attrs: { href: String(m.attrs!.href).trim() } }] : []
        if (m.type === 'textStyle') return TEXT_COLOR_SET.has(String(m.attrs?.color)) ? [{ type: 'textStyle', attrs: { color: m.attrs!.color } }] : []
        if (m.type === 'highlight') return [{ type: 'highlight', ...(HIGHLIGHT_SET.has(String(m.attrs?.color)) ? { attrs: { color: m.attrs!.color } } : {}) }]
        return [{ type: m.type }]
      })
      if (marks.length) out.marks = marks
      return out
    }
    if (node.content?.length) {
      const kids = node.content.map(walk).filter((x): x is RichNode => x !== null)
      if (kids.length) out.content = kids
    }
    return out
  }
  const result = walk(doc) ?? { type: 'doc' }
  return { doc: { ...result, type: 'doc' } as RichDoc, dropped }
}

function collectText(node: RichNode): string {
  if (node.type === 'text') return node.text ?? ''
  return (node.content ?? []).map(collectText).join(' ').trim()
}

/** 내용이 비었는가(빈 문단만 있는 문서) */
export function isEmptyDoc(doc: RichNode | null | undefined): boolean {
  if (!doc) return true
  const visit = (n: RichNode): boolean => {
    if (n.type === 'text') return !(n.text ?? '').trim()
    if (['image', 'table', 'horizontalRule', 'codeBlock'].includes(n.type)) return false
    return (n.content ?? []).every(visit)
  }
  return visit(doc)
}

/** 서식 없는 옛 글 → 문서 구조(줄마다 한 문단). 서버 richdoc.from_text 와 같은 규칙. */
export function textToDoc(text: string | null | undefined): RichDoc {
  const lines = (text ?? '').split('\n')
  return {
    type: 'doc',
    content: lines.map((line) => (line ? { type: 'paragraph', content: [{ type: 'text', text: line }] } : { type: 'paragraph' })),
  }
}

/**
 * 표준 양식 같은 '간단한 마크다운' → 문서 구조.
 * `## 제목` → 제목2, `- 항목` → 글머리 목록, `1. 항목` → 번호 목록, 나머지는 문단.
 */
export function outlineToDoc(text: string): RichDoc {
  const content: RichNode[] = []
  let list: RichNode | null = null
  const para = (s: string): RichNode => (s ? { type: 'paragraph', content: [{ type: 'text', text: s }] } : { type: 'paragraph' })
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^-\s+(.*)$/.exec(line)
    const numbered = /^\d+\.\s*(.*)$/.exec(line)
    if (bullet || numbered) {
      const kind = bullet ? 'bulletList' : 'orderedList'
      if (!list || list.type !== kind) { list = { type: kind, content: [] }; content.push(list) }
      list.content!.push({ type: 'listItem', content: [para((bullet ?? numbered)![1])] })
      continue
    }
    list = null
    const heading = /^#{1,3}\s+(.*)$/.exec(line)
    if (heading) content.push({ type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: heading[1] }] })
    else if (line) content.push(para(line))
  }
  return { type: 'doc', content: content.length ? content : [{ type: 'paragraph' }] }
}
