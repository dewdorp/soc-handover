/**
 * 서식 있는 본문 보기 — 인계 본문 · 댓글 · 운영 지식 · 할일 설명.
 *
 * HTML 문자열을 끼워 넣지 않는다(dangerouslySetInnerHTML 없음). 문서 구조를 React 요소로
 * 직접 그리므로 로그에 든 `<script>` 나 태그는 **글자 그대로** 보이고 실행될 길이 없다.
 * 링크 · 색 · 그림 주소는 서버가 허용 목록으로 검사한 값이지만, 그리기 직전에 한 번 더 본다.
 *
 * 편집기(Tiptap)를 불러오지 않는다 — 보는 화면은 가볍게 두고, 편집할 때만 편집기를 받는다.
 */
import { useState, type ReactNode } from 'react'
import { Check, Copy, ImageOff, RotateCcw } from 'lucide-react'
import ImageLightbox from '@/features/richtext/ImageLightbox'
import {
  CODE_LANGUAGE_LABEL, HIGHLIGHT_COLORS, TEXT_COLORS, inlineIdOf, isSafeLink,
  type RichMark, type RichNode,
} from '@/features/richtext/doc'

const TEXT_COLOR = new Set(TEXT_COLORS.map((c) => c.value))
const HIGHLIGHT = new Set(HIGHLIGHT_COLORS.map((c) => c.value))

interface Props {
  /** 서식 구조. 없으면 서식 없는 옛 글이다 — text 를 그대로 보여 준다. */
  doc?: RichNode | null
  text?: string | null
  /** 비었을 때 보여 줄 말 */
  empty?: string
  className?: string
}

export default function RichView({ doc, text, empty = '(없음)', className = '' }: Props) {
  const [zoom, setZoom] = useState<{ src: string; alt: string } | null>(null)
  if (!doc) {
    return text?.trim()
      ? <p className={`whitespace-pre-wrap break-words ${className}`}>{text}</p>
      : <p className={`text-ink-faint ${className}`}>{empty}</p>
  }
  return (
    <div className={`rich-view ${className}`}>
      {(doc.content ?? []).map((n, i) => <Block key={i} node={n} onZoom={setZoom} />)}
      {zoom && <ImageLightbox src={zoom.src} alt={zoom.alt} onClose={() => setZoom(null)} />}
    </div>
  )
}

type Zoom = (img: { src: string; alt: string }) => void

function Block({ node, onZoom }: { node: RichNode; onZoom: Zoom }): ReactNode {
  const kids = (node.content ?? []).map((n, i) => <Block key={i} node={n} onZoom={onZoom} />)
  switch (node.type) {
    case 'paragraph':
      return <p>{inlines(node.content, onZoom)}</p>
    case 'heading':
      return node.attrs?.level === 3 ? <h4>{inlines(node.content, onZoom)}</h4> : <h3>{inlines(node.content, onZoom)}</h3>
    case 'bulletList':
      return <ul>{kids}</ul>
    case 'orderedList':
      return <ol start={Number(node.attrs?.start ?? 1)}>{kids}</ol>
    case 'listItem':
      return <li>{kids}</li>
    case 'taskList':
      return <ul className="task-list">{kids}</ul>
    case 'taskItem':
      return (
        <li className="task-item" data-checked={node.attrs?.checked ? 'true' : 'false'}>
          <input type="checkbox" checked={Boolean(node.attrs?.checked)} readOnly disabled
                 aria-label={node.attrs?.checked ? '완료' : '미완료'} />
          <div>{kids}</div>
        </li>
      )
    case 'blockquote':
      return <blockquote>{kids}</blockquote>
    case 'horizontalRule':
      return <hr />
    case 'codeBlock':
      return <CodeBlock language={String(node.attrs?.language ?? '')} text={plain(node)} />
    case 'image':
      return <Figure node={node} onZoom={onZoom} />
    case 'table':
      // 넓은 표는 이 상자 안에서만 가로로 민다 — 화면 전체가 밀리지 않게.
      return <div className="table-wrap" role="region" aria-label="표" tabIndex={0}><table><tbody>{kids}</tbody></table></div>
    case 'tableRow':
      return <tr>{kids}</tr>
    case 'tableHeader':
    case 'tableCell': {
      const Tag = node.type === 'tableHeader' ? 'th' : 'td'
      const width = Array.isArray(node.attrs?.colwidth) ? (node.attrs!.colwidth as number[])[0] : undefined
      return (
        <Tag colSpan={Number(node.attrs?.colspan ?? 1)} rowSpan={Number(node.attrs?.rowspan ?? 1)}
             style={width ? { minWidth: width } : undefined}>{kids}</Tag>
      )
    }
    default:
      return null      // 모르는 요소는 그리지 않는다(서버가 이미 막는다)
  }
}

function inlines(nodes: RichNode[] | undefined, onZoom: Zoom): ReactNode[] {
  return (nodes ?? []).map((n, i) => {
    if (n.type === 'hardBreak') return <br key={i} />
    if (n.type === 'image') return <Figure key={i} node={n} onZoom={onZoom} />
    if (n.type !== 'text') return null
    return <Marked key={i} text={n.text ?? ''} marks={n.marks ?? []} />
  })
}

function Marked({ text, marks }: { text: string; marks: RichMark[] }) {
  let out: ReactNode = text
  for (const m of marks) {
    switch (m.type) {
      case 'bold': out = <strong>{out}</strong>; break
      case 'italic': out = <em>{out}</em>; break
      case 'underline': out = <u>{out}</u>; break
      case 'strike': out = <s>{out}</s>; break
      case 'code': out = <code className="inline-code">{out}</code>; break
      case 'textStyle': {
        const color = String(m.attrs?.color ?? '')
        if (TEXT_COLOR.has(color)) out = <span style={{ color }}>{out}</span>
        break
      }
      case 'highlight': {
        const color = String(m.attrs?.color ?? '#fef08a')
        out = <mark style={{ backgroundColor: HIGHLIGHT.has(color) ? color : '#fef08a' }}>{out}</mark>
        break
      }
      case 'link': {
        const href = m.attrs?.href
        // 다시 한 번 본다 — http · https · mailto 만. 새 창 + 이 화면에 손대지 못하게.
        if (isSafeLink(href)) {
          out = <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="break-all">{out}</a>
        }
        break
      }
    }
  }
  return <>{out}</>
}

function plain(node: RichNode): string {
  if (node.type === 'text') return node.text ?? ''
  if (node.type === 'hardBreak') return '\n'
  return (node.content ?? []).map(plain).join('')
}

/** 로그 · 코드 — 고정폭, 줄바꿈 켜고 끄기, 원문 그대로 복사 */
function CodeBlock({ language, text }: { language: string; text: string }) {
  const [copied, setCopied] = useState(false)
  const [wrap, setWrap] = useState(true)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // http 내부망 등 클립보드 API 가 막힌 곳 — 옛 방식으로
      const area = document.createElement('textarea')
      area.value = text
      area.setAttribute('readonly', '')
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      document.body.removeChild(area)
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="code-block">
      <div className="code-head">
        <span>{CODE_LANGUAGE_LABEL[language] ?? '코드'}</span>
        <span className="flex-1" />
        <button type="button" onClick={() => setWrap((w) => !w)} title="긴 줄 접기 / 가로로 보기">
          {wrap ? '가로로 보기' : '줄 접기'}
        </button>
        <button type="button" onClick={copy} title="원문 그대로 복사" aria-label="코드 복사">
          {copied ? <><Check size={12} /> 복사됨</> : <><Copy size={12} /> 복사</>}
        </button>
      </div>
      <pre className={wrap ? 'wrap' : ''}><code>{text}</code></pre>
    </div>
  )
}

/** 본문 그림 — 눌러서 크게, 못 불러오면 다시 시도 */
function Figure({ node, onZoom }: { node: RichNode; onZoom: Zoom }) {
  const src = String(node.attrs?.src ?? '')
  const alt = String(node.attrs?.alt ?? '')
  const width = Number(node.attrs?.width ?? 100)
  const [failed, setFailed] = useState(false)
  const [nonce, setNonce] = useState(0)
  if (inlineIdOf(src) === null) return null       // 내부 그림 주소가 아니면 그리지 않는다
  return (
    <figure className="rich-figure" style={{ width: `${[25, 50, 75, 100].includes(width) ? width : 100}%` }}>
      {failed ? (
        <div className="img-failed" role="alert">
          <ImageOff size={16} /> 그림을 불러오지 못했습니다.
          <button type="button" className="btn btn-sm" onClick={() => { setFailed(false); setNonce((n) => n + 1) }}>
            <RotateCcw size={12} /> 다시 시도
          </button>
        </div>
      ) : (
        <button type="button" className="block w-full cursor-zoom-in" onClick={() => onZoom({ src, alt })}
                title="눌러서 크게 보기">
          <img key={nonce} src={nonce ? `${src}?r=${nonce}` : src} alt={alt || '본문 그림'}
               loading="lazy" onError={() => setFailed(true)} />
        </button>
      )}
      {alt && <figcaption>{alt}</figcaption>}
    </figure>
  )
}
