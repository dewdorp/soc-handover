/**
 * 통합검색 팔레트 (Ctrl+K, UI_STRUCTURE §10) — 인수인계 · 할일 · 일정을 입력하는 대로 찾는다.
 *
 * ↑↓ 로 고르고 Enter 로 연다. 맨 아래 '전체 결과 보기'는 /search 화면으로 간다.
 * 결과마다 어느 칸에서 걸렸는지 보여준다 — 확인자 이름으로만 걸린 건은 제목만 봐서는 이유를 모른다.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { CalendarDays, ClipboardList, CornerDownLeft, FileText, Search } from 'lucide-react'
import Highlight from '@/features/search/Highlight'
import { recentSearches, rememberSearch } from '@/features/search/recent'
import { HIT_LABEL, hitHref, searchApi, type GlobalHit, type HitType } from '@/services/api/search'

export const HIT_ICON: Record<HitType, typeof FileText> = { handover: FileText, task: ClipboardList, schedule: CalendarDays }
const ORDER: HitType[] = ['handover', 'task', 'schedule']

type Row = { kind: 'hit'; hit: GlobalHit } | { kind: 'all' } | { kind: 'recent'; term: string }

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [active, setActive] = useState(0)
  const list = useRef<HTMLUListElement>(null)
  const recent = useMemo(() => recentSearches(), [])

  useEffect(() => {
    const t = window.setTimeout(() => setTerm(q.trim()), 200)
    return () => window.clearTimeout(t)
  }, [q])
  useEffect(() => setActive(0), [term])
  useEffect(() => {
    // 뒤의 상세 패널까지 Esc 로 닫히지 않게 먼저 받아서 멈춘다(capture)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const { data, isFetching, isError } = useQuery({
    queryKey: ['global-search', term, 5], queryFn: () => searchApi.global(term, 5),
    enabled: term.length > 0, placeholderData: keepPreviousData, staleTime: 10_000,
  })
  const hits = term ? data?.hits ?? [] : []          // 새 결과가 올 때까지 앞 결과를 둔다(깜빡임 없이)
  const rows: Row[] = term
    ? [...ORDER.flatMap((t) => hits.filter((h) => h.type === t).map((hit) => ({ kind: 'hit' as const, hit }))), { kind: 'all' }]
    : recent.map((r) => ({ kind: 'recent', term: r }))

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-row="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const go = (row: Row | undefined) => {
    if (!row) return
    if (row.kind === 'recent') { setQ(row.term); return }
    rememberSearch(term || q)
    navigate(row.kind === 'hit' ? hitHref(row.hit) : `/search?q=${encodeURIComponent(term || q.trim())}`)
    onClose()
  }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => (rows.length ? (a + 1) % rows.length : 0)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => (rows.length ? (a - 1 + rows.length) % rows.length : 0)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      if (term !== q.trim() && q.trim()) {          // 입력 직후 Enter — 기다리지 않고 전체 결과로
        rememberSearch(q)
        navigate(`/search?q=${encodeURIComponent(q.trim())}`)
        onClose()
      } else go(rows[active])
    }
  }

  const total = Object.values(data?.totals ?? {}).reduce((a, b) => a + (b ?? 0), 0)
  let index = -1

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-start justify-center p-4 pt-[10vh]" onClick={onClose}
         role="dialog" aria-modal="true" aria-label="통합검색">
      <div className="card w-[640px] max-w-full shadow-xl flex flex-col max-h-[75vh]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-3 h-11 border-b border-surface-border">
          <Search size={16} className="text-ink-faint shrink-0" />
          <input autoFocus className="flex-1 bg-transparent outline-none text-md" value={q}
                 placeholder="인수인계 · 할일 · 일정 검색 (제목·내용·관계사·인명·태그)"
                 onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
                 role="combobox" aria-expanded aria-controls="palette-results"
                 aria-activedescendant={rows.length ? `palette-row-${active}` : undefined} />
          {isFetching && <span className="text-xs text-ink-faint">찾는 중…</span>}
          <kbd className="text-xs border border-surface-border rounded px-1 text-ink-faint">Esc</kbd>
        </div>

        <ul ref={list} id="palette-results" role="listbox" className="flex-1 overflow-y-auto py-1">
          {!term && (
            <li className="px-3 py-2 text-sm text-ink-muted">
              인수인계는 제목·내용·비고·관계사·전달자·담당자·확인자·태그로, 할일·일정은 제목·내용으로 찾습니다.
              {recent.length > 0 && <div className="mt-2 text-xs text-ink-faint">최근 검색</div>}
            </li>
          )}
          {!term && recent.map((r, i) => (
            <li key={r} id={`palette-row-${i}`} data-row={i} role="option" aria-selected={active === i}
                onMouseEnter={() => setActive(i)} onClick={() => setQ(r)}
                className={`px-3 py-1.5 cursor-pointer flex items-center gap-2 ${active === i ? 'bg-brand-soft' : ''}`}>
              <Search size={12} className="text-ink-faint" />{r}
            </li>
          ))}

          {term && isError && <li className="px-3 py-3 text-sm text-state-urgent">검색하지 못했습니다. 잠시 뒤 다시 시도하십시오.</li>}
          {term && !isFetching && !isError && hits.length === 0 && (
            <li className="px-3 py-3 text-sm text-ink-muted">'{term}' 에 맞는 결과가 없습니다.</li>
          )}

          {term && ORDER.map((type) => {
            const group = hits.filter((h) => h.type === type)
            if (!group.length) return null
            const Icon = HIT_ICON[type]
            return (
              <li key={type} role="presentation">
                <div className="px-3 pt-2 pb-0.5 text-xs text-ink-faint">
                  {HIT_LABEL[type]} · {data?.totals[type] ?? group.length}건
                </div>
                <ul role="presentation">
                  {group.map((hit) => {
                    index += 1
                    const i = index
                    return (
                      <li key={`${hit.type}-${hit.id}`} id={`palette-row-${i}`} data-row={i} role="option" aria-selected={active === i}
                          onMouseEnter={() => setActive(i)} onClick={() => go({ kind: 'hit', hit })}
                          className={`px-3 py-1.5 cursor-pointer flex gap-2 ${active === i ? 'bg-brand-soft' : ''}`}>
                        <Icon size={14} className="text-ink-faint shrink-0 mt-0.5" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate"><Highlight text={hit.title} term={term} /></span>
                            {hit.matched.filter((m) => m !== '제목').slice(0, 2).map((m) => (
                              <span key={m} className="chip h-4 text-[11px] px-1.5 shrink-0">{m}</span>
                            ))}
                          </div>
                          {hit.snippet && <div className="text-xs text-ink-muted truncate"><Highlight text={hit.snippet} term={term} /></div>}
                        </div>
                        <div className="text-xs text-ink-faint shrink-0 text-right">
                          {hit.company && <div>{hit.company}</div>}
                          {hit.date && <div className="tabular-nums">{hit.date}</div>}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </li>
            )
          })}

          {term && (() => {
            const i = rows.length - 1
            return (
              <li id={`palette-row-${i}`} data-row={i} role="option" aria-selected={active === i}
                  onMouseEnter={() => setActive(i)} onClick={() => go({ kind: 'all' })}
                  className={`mt-1 mx-1 px-2 py-1.5 rounded cursor-pointer flex items-center gap-2 border-t border-surface-border ${active === i ? 'bg-brand-soft' : ''}`}>
                <Search size={12} className="text-brand" />
                <span>'{term}' 전체 결과 보기{data ? ` · ${total}건` : ''}</span>
                <CornerDownLeft size={12} className="ml-auto text-ink-faint" />
              </li>
            )
          })()}
        </ul>

        <div className="px-3 py-1.5 border-t border-surface-border text-xs text-ink-faint flex gap-3">
          <span>↑↓ 이동</span><span>Enter 열기</span><span>Esc 닫기</span>
          <span className="ml-auto">목록 화면에서는 <kbd className="border border-surface-border rounded px-1">/</kbd> 로 그 화면 검색창</span>
        </div>
      </div>
    </div>
  )
}
