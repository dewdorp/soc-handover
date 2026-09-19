/**
 * 통합검색 (/search?q=, UI_STRUCTURE §2) — 인수인계 · 할일 · 일정을 종류별로.
 *
 * 종류마다 상위 20건과 전체 건수를 보여주고, '목록에서 모두 보기'로 같은 검색어를 각 목록에
 * 넘긴다(인수인계 목록에서는 컬럼 필터·저장된 보기와 함께 쓸 수 있다).
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, Search } from 'lucide-react'
import { HIT_ICON } from '@/features/search/CommandPalette'
import Highlight from '@/features/search/Highlight'
import { recentSearches, rememberSearch } from '@/features/search/recent'
import { HIT_LABEL, hitHref, listHref, searchApi, type HitType } from '@/services/api/search'

const ORDER: HitType[] = ['handover', 'task', 'schedule']
const LIMIT = 20
const EMPTY: Record<HitType, string> = {
  handover: '맞는 인수인계가 없습니다.', task: '맞는 할일이 없습니다.', schedule: '맞는 일정이 없습니다.',
}
const SCOPE_NOTE: Record<HitType, string> = {
  handover: '제목·내용·비고·관계사·전달자·담당자·확인자·태그',
  task: '제목·내용 (완료·취소 포함)',
  schedule: '제목·내용',
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = (params.get('q') ?? '').trim()
  const [draft, setDraft] = useState(q)
  useEffect(() => setDraft(q), [q])

  const { data, isFetching, isError } = useQuery({
    queryKey: ['global-search', q, LIMIT], queryFn: () => searchApi.global(q, LIMIT), enabled: q.length > 0,
  })
  useEffect(() => { if (q) rememberSearch(q) }, [q])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const term = draft.trim()
    setParams(term ? { q: term } : {})
  }
  const total = Object.values(data?.totals ?? {}).reduce((a, b) => a + (b ?? 0), 0)

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-4xl mx-auto p-4 space-y-4">
        <form onSubmit={submit} className="flex gap-2">
          <div className="relative flex-1">
            <Search size={15} className="absolute left-2.5 top-2.5 text-ink-faint" />
            <input className="input w-full h-9 pl-8 text-md" value={draft} autoFocus aria-label="통합검색"
                   placeholder="인수인계 · 할일 · 일정 검색" onChange={(e) => setDraft(e.target.value)} />
          </div>
          <button className="btn btn-primary h-9">검색</button>
        </form>

        {!q && (
          <div className="card p-4 space-y-2 text-ink-muted">
            <p>여러 곳을 한 번에 찾습니다. 어디서든 <kbd className="border border-surface-border rounded px-1">Ctrl</kbd>+<kbd className="border border-surface-border rounded px-1">K</kbd> 로 바로 찾을 수 있습니다.</p>
            <ul className="text-sm space-y-0.5">
              {ORDER.map((t) => <li key={t}><b className="text-ink">{HIT_LABEL[t]}</b> — {SCOPE_NOTE[t]}</li>)}
            </ul>
            {recentSearches().length > 0 && (
              <div className="flex flex-wrap items-center gap-1 pt-1">
                <span className="text-sm">최근 검색</span>
                {recentSearches().map((r) => (
                  <button key={r} className="chip hover:border-brand" onClick={() => setParams({ q: r })}>{r}</button>
                ))}
              </div>
            )}
          </div>
        )}

        {q && (
          <p className="text-ink-muted">
            '<b className="text-ink">{q}</b>' {isFetching && !data ? '찾는 중…' : isError ? '검색하지 못했습니다.' : `검색 결과 ${total}건`}
          </p>
        )}

        {q && data && ORDER.map((type) => {
          const group = data.hits.filter((h) => h.type === type)
          const count = data.totals[type] ?? 0
          const more = listHref(type, q)
          const Icon = HIT_ICON[type]
          return (
            <section key={type} className="card" aria-label={`${HIT_LABEL[type]} 결과`}>
              <header className="flex items-center gap-2 px-3 py-2 border-b border-surface-border">
                <Icon size={14} className="text-ink-faint" />
                <h2 className="font-medium">{HIT_LABEL[type]}</h2>
                <span className="chip h-5 tabular-nums">{count}</span>
                <span className="text-xs text-ink-faint hidden sm:inline">{SCOPE_NOTE[type]}</span>
                <span className="flex-1" />
                {more && count > 0 && (
                  <Link to={more} className="text-sm text-brand hover:underline inline-flex items-center gap-0.5">
                    목록에서 모두 보기 <ArrowRight size={12} />
                  </Link>
                )}
              </header>
              {count === 0 ? (
                <p className="px-3 py-3 text-sm text-ink-faint">{EMPTY[type]}</p>
              ) : (
                <ul className="divide-y divide-surface-border/70">
                  {group.map((hit) => (
                    <li key={hit.id}>
                      <Link to={hitHref(hit)} className="flex gap-3 px-3 py-2 hover:bg-surface-sunken">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-ink-faint tabular-nums text-sm">#{hit.id}</span>
                            <span className="truncate font-medium"><Highlight text={hit.title} term={q} /></span>
                            {hit.matched.filter((m) => m !== '제목').map((m) => (
                              <span key={m} className="chip h-4 text-[11px] px-1.5 shrink-0" title={`${m} 칸에서 찾았습니다`}>{m}</span>
                            ))}
                          </div>
                          {hit.snippet && <p className="text-sm text-ink-muted truncate"><Highlight text={hit.snippet} term={q} /></p>}
                        </div>
                        <div className="text-sm text-ink-muted shrink-0 text-right">
                          {hit.company && <div>{hit.company}</div>}
                          {hit.date && <div className="tabular-nums text-xs text-ink-faint">{hit.date}</div>}
                        </div>
                      </Link>
                    </li>
                  ))}
                  {count > group.length && (
                    <li className="px-3 py-2 text-sm text-ink-faint">
                      상위 {group.length}건만 보입니다.{more ? ' 나머지는 목록에서 보십시오.' : ' 검색어를 더 구체적으로 적어 보십시오.'}
                    </li>
                  )}
                </ul>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
