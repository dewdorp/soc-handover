/** 검색어를 굵게 — 대소문자 구분 없이, 정규식 특수문자는 글자 그대로. */
export default function Highlight({ text, term }: { text: string; term: string }) {
  const needle = term.trim()
  if (!needle) return <>{text}</>
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <>
      {parts.map((part, i) => (part.toLowerCase() === needle.toLowerCase()
        ? <mark key={i} className="bg-amber-100 text-ink rounded-sm px-px">{part}</mark>
        : <span key={i}>{part}</span>))}
    </>
  )
}
