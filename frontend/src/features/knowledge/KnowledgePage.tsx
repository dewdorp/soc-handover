/**
 * SOC 운영 지식 — SOP · 분석 가이드 · 비상 대응 · 장비 운용 · 점검 체크리스트 · 참고 자료.
 *
 * 한 화면에서 끝나게 둔다. 야간에 혼자 보는 사람이 문서를 찾고, 절차를 읽고,
 * 관련 인계를 열고, 첨부를 받는 일을 화면을 옮겨 다니며 하게 하면 안 된다.
 * 열람 판정은 전부 서버가 한다 — 여기 보이는 것은 이미 볼 수 있는 것뿐이다.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { BookOpen, FilePlus, History, Link2, Pin, RotateCcw, Search, Trash2 } from 'lucide-react'
import Attachments from '@/components/Attachments'
import { useMyGroups } from '@/features/handovers/ScopePicker'
import { ApiRequestError } from '@/services/api/client'
import {
  CATEGORIES, knowledgeApi,
  type KnowledgeArticle, type KnowledgeCategory, type KnowledgeInput,
} from '@/services/api/knowledge'

function blank(): KnowledgeInput {
  return { category: '운영 절차', title: '', body: '', visibility: 'ALL',
           group_ids: [], tags: [], is_pinned: false, review_due: null }
}
function errorText(err: unknown): string {
  return err instanceof ApiRequestError ? err.message : '요청을 처리하지 못했습니다.'
}
const parseTags = (text: string) =>
  text.split(/[,\s]+/).map((x) => x.trim().replace(/^#/, '')).filter(Boolean).slice(0, 20)

export default function KnowledgePage() {
  const qc = useQueryClient()
  const { data: mine = [] } = useMyGroups()
  const [q, setQ] = useState('')
  const [applied, setApplied] = useState('')
  const [category, setCategory] = useState('')
  const [tag, setTag] = useState('')
  const [reviewDueOnly, setReviewDueOnly] = useState(false)
  // 인수인계 화면에서 '관련 절차'를 눌러 들어오면 그 문서를 바로 연다.
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<number | null>(() => {
    const id = Number(params.get('id'))
    return Number.isFinite(id) && id > 0 ? id : null
  })
  const [draft, setDraft] = useState<KnowledgeInput | null>(null)
  const [tagText, setTagText] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [offset, setOffset] = useState(0)

  const rows = useQuery({
    queryKey: ['knowledge', applied, category, tag, reviewDueOnly, offset],
    queryFn: () => knowledgeApi.list({ q: applied, category, tag, reviewDueOnly, offset }),
  })
  const detail = useQuery({
    queryKey: ['knowledge-detail', selected],
    queryFn: () => knowledgeApi.get(selected!),
    enabled: selected != null,
  })
  useEffect(() => {
    const id = Number(params.get('id'))
    if (Number.isFinite(id) && id > 0) {
      setSelected(id)
      params.delete('id')          // 뒤로 가기로 같은 문서가 다시 열리지 않게 주소만 정리한다
      setParams(params, { replace: true })
    }
  }, [params, setParams])

  const save = useMutation({
    mutationFn: (v: KnowledgeInput) => editingId == null
      ? knowledgeApi.create(v)
      : knowledgeApi.update(editingId, v),
    onSuccess: (article) => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      qc.setQueryData(['knowledge-detail', article.id], article)
      setSelected(article.id); setDraft(null); setEditingId(null); setMessage('저장했습니다.')
    },
    onError: (err) => setMessage(errorText(err)),
  })
  const remove = useMutation({
    mutationFn: (id: number) => knowledgeApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      qc.invalidateQueries({ queryKey: ['knowledge-detail'] })
      setMessage('삭제했습니다. 같은 화면에서 되살릴 수 있습니다.')
    },
    onError: (err) => setMessage(errorText(err)),
  })
  const undelete = useMutation({
    mutationFn: (id: number) => knowledgeApi.restore(id),
    onSuccess: (article) => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      qc.setQueryData(['knowledge-detail', article.id], article)
      setMessage('되살렸습니다.')
    },
    onError: (err) => setMessage(errorText(err)),
  })

  const openEditor = (row?: KnowledgeArticle) => {
    setEditingId(row?.id ?? null)
    setTagText(row ? row.tags.join(', ') : '')
    setDraft(row ? {
      category: row.category, title: row.title, body: row.body,
      visibility: row.visibility, group_ids: [...row.group_ids], tags: [...row.tags],
      is_pinned: row.is_pinned, review_due: row.review_due, version_no: row.version_no,
      change_note: '',
    } : blank())
    setMessage('')
  }
  const onSave = () => {
    if (!draft?.title.trim()) { setMessage('제목을 입력하십시오.'); return }
    if (draft.visibility === 'GROUPS' && !draft.group_ids.length) {
      setMessage('그룹을 고르거나 전체 공개를 선택하십시오.'); return
    }
    save.mutate({ ...draft, title: draft.title.trim(), tags: parseTags(tagText) })
  }
  const set = (v: Partial<KnowledgeInput>) => setDraft((d) => d ? { ...d, ...v } : d)
  const useTemplate = async () => {
    try { set({ body: (await knowledgeApi.template()).body }) }
    catch (err) { setMessage(errorText(err)) }
  }

  return (
    <div className="p-3 sm:p-4 space-y-3 h-full overflow-auto">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold flex gap-2 items-center"><BookOpen size={18} /> 운영 지식</h1>
          <p className="text-sm text-ink-muted">관제 절차 · 분석 가이드 · 비상 연락 · 점검 체크리스트와 문서 파일을 함께 보관합니다.</p>
        </div>
        <button className="btn btn-primary" onClick={() => openEditor()}><FilePlus size={14} /> 새 문서</button>
      </header>
      {message && <p role="status" className="text-sm text-ink-muted">{message}</p>}
      <div className="grid grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)] gap-3 min-h-[440px]">
        <aside className="card p-3 space-y-2">
          <div className="flex gap-1">
            <input className="input w-full" placeholder="제목 · 본문 · 태그 검색" aria-label="운영 지식 검색"
                   value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter') { setApplied(q.trim()); setOffset(0) } }} />
            <button className="btn" aria-label="검색" onClick={() => { setApplied(q.trim()); setOffset(0) }}><Search size={15}/></button>
          </div>
          <select className="input w-full" aria-label="문서 분류" value={category}
                  onChange={(e) => { setCategory(e.target.value); setOffset(0) }}>
            <option value="">전체 분류</option>
            {CATEGORIES.map((x) => <option key={x}>{x}</option>)}
          </select>
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={reviewDueOnly}
                   onChange={(e) => { setReviewDueOnly(e.target.checked); setOffset(0) }} />
            재검토 기한이 지난 문서만
          </label>
          {tag && (
            <button className="chip" onClick={() => { setTag(''); setOffset(0) }}>#{tag} 해제</button>
          )}
          {rows.isLoading && <p className="text-ink-muted p-3">불러오는 중…</p>}
          {rows.isError && <div role="alert" className="text-state-urgent p-3">목록 오류 <button className="btn btn-sm" onClick={() => rows.refetch()}>다시 시도</button></div>}
          <div className="divide-y divide-surface-border/70">
            {rows.data?.map((row) => (
              <button key={row.id} onClick={() => { setSelected(row.id); setDraft(null); setMessage('') }}
                      className={`block text-left w-full py-2.5 px-1 hover:bg-surface-sunken rounded ${selected === row.id ? 'bg-brand-soft' : ''}`}>
                <span className="text-sm text-ink-faint">{row.category} {row.visibility === 'ALL' ? '· 전체' : `· ${row.group_names.join(' · ') || '그룹'}`}</span>
                <span className="block font-medium break-words">{row.is_pinned && <Pin size={12} className="inline mr-1"/>}{row.title}</span>
                {row.tags.length > 0 && (
                  <span className="block text-xs text-ink-faint truncate">{row.tags.map((t) => `#${t}`).join(' ')}</span>
                )}
                {row.review_due && (
                  <span className={`block text-xs ${row.review_overdue ? 'text-state-urgent' : 'text-ink-faint'}`}>
                    재검토: {row.review_due}{row.review_overdue && ' · 기한 지남'}
                  </span>
                )}
              </button>
            ))}
          </div>
          {rows.data?.length === 0 && <p className="text-ink-muted p-3">등록된 자료가 없습니다.</p>}
          <div className="flex justify-between">
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>이전</button>
            <button className="btn btn-sm" disabled={(rows.data?.length ?? 0) < 50} onClick={() => setOffset(offset + 50)}>다음</button>
          </div>
        </aside>

        <section className="card p-3 sm:p-4 min-w-0">
          {draft ? (
            <div className="space-y-3">
              <h2 className="font-semibold">{editingId == null ? '운영 문서 등록' : '운영 문서 수정'}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <label className="space-y-1 block"><span className="text-sm">분류</span>
                  <select className="input w-full" value={draft.category} onChange={(e) => set({ category: e.target.value as KnowledgeCategory })}>
                    {CATEGORIES.map((x) => <option key={x}>{x}</option>)}
                  </select></label>
                <label className="space-y-1 block"><span className="text-sm">재검토 예정일 (선택)</span>
                  <input type="date" className="input w-full" value={draft.review_due ?? ''}
                         onChange={(e) => set({ review_due: e.target.value || null })}/></label>
              </div>
              <label className="space-y-1 block"><span className="text-sm">제목</span>
                <input className="input w-full" maxLength={200} value={draft.title} onChange={(e) => set({ title: e.target.value })}/></label>
              <label className="space-y-1 block"><span className="text-sm">태그 (쉼표로 구분)</span>
                <input className="input w-full" placeholder="랜섬웨어, 방화벽, 월간점검" aria-label="태그"
                       value={tagText} onChange={(e) => setTagText(e.target.value)}/></label>
              <label className="space-y-1 block"><span className="text-sm">절차 · 참고 내용</span>
                <textarea className="input w-full min-h-[240px] resize-y" value={draft.body} onChange={(e) => set({ body: e.target.value })}/></label>
              <div className="flex gap-2 flex-wrap items-center">
                <button className="btn btn-sm" onClick={useTemplate}>표준 양식 넣기</button>
                <span className="text-xs text-ink-faint">목적·범위 / 탐지·확인 / 분석 / 조치 / 보고·전파 / 후속 확인 / 관련 문서</span>
              </div>
              {editingId != null && (
                <label className="space-y-1 block"><span className="text-sm">수정 사유 (선택 · 개정 이력에 남습니다)</span>
                  <input className="input w-full" maxLength={300} value={draft.change_note ?? ''}
                         onChange={(e) => set({ change_note: e.target.value })}/></label>
              )}
              <fieldset className="space-y-2 border rounded border-surface-border p-2">
                <legend className="text-sm px-1">공개 범위</legend>
                <div className="flex flex-wrap gap-3">
                  <label><input type="radio" checked={draft.visibility === 'ALL'} onChange={() => set({ visibility: 'ALL', group_ids: [] })}/> 전체 공유 (그룹 미지정)</label>
                  <label><input type="radio" checked={draft.visibility === 'GROUPS'} onChange={() => set({ visibility: 'GROUPS' })}/> 그룹 선택</label>
                </div>
                {draft.visibility === 'GROUPS' && <div className="flex gap-3 flex-wrap">
                  {mine.map((g) => <label key={g.id}><input type="checkbox" checked={draft.group_ids.includes(g.id)}
                    onChange={(e) => set({ group_ids: e.target.checked ? [...draft.group_ids, g.id] : draft.group_ids.filter((id) => id !== g.id) })}/> {g.name}</label>)}
                  {!mine.length && <p className="text-state-urgent">소속 그룹이 없습니다. 관리자에게 문의하세요.</p>}
                </div>}
              </fieldset>
              <label className="text-sm"><input type="checkbox" checked={draft.is_pinned} onChange={(e) => set({ is_pinned: e.target.checked })}/> 목록 상단에 고정</label>
              <div className="flex gap-2 justify-end">
                <button className="btn" onClick={() => { setDraft(null); setEditingId(null) }}>취소</button>
                <button className="btn btn-primary" disabled={save.isPending} onClick={onSave}>저장</button>
              </div>
              <p className="text-xs text-ink-faint">첨부파일은 문서 저장 후 추가할 수 있습니다. 첨부는 이 문서의 열람 권한을 그대로 따릅니다.</p>
            </div>
          ) : selected != null ? (
            detail.isLoading ? <p>문서를 불러오는 중…</p> :
            detail.isError || !detail.data ? <div role="alert">열람할 수 없는 문서입니다. <button className="btn btn-sm" onClick={() => detail.refetch()}>재시도</button></div> :
            <article className="space-y-3">
              {detail.data.is_deleted && (
                <div role="alert" className="rounded bg-state-urgent-soft/40 p-2 text-sm flex items-center gap-2 flex-wrap">
                  삭제된 문서입니다.
                  {detail.data.can_edit && (
                    <button className="btn btn-sm" disabled={undelete.isPending}
                            onClick={() => undelete.mutate(detail.data.id)}><RotateCcw size={12}/> 되살리기</button>
                  )}
                </div>
              )}
              <div className="flex gap-2 justify-between items-start">
                <div className="min-w-0">
                  <p className="text-sm text-ink-muted">
                    {detail.data.category} · {detail.data.visibility === 'ALL' ? '전체 공유' : `그룹 공개: ${detail.data.group_names.join(' · ')}`}
                  </p>
                  <h2 className="text-lg font-semibold break-words">{detail.data.title}</h2>
                  <p className="text-xs text-ink-muted">
                    v{detail.data.version_no} · 작성 {detail.data.created_by_name ?? '-'}
                    {detail.data.updated_by_name && ` · 최종 수정 ${detail.data.updated_by_name}`}
                    {' · 재검토 '}
                    <span className={detail.data.review_overdue ? 'text-state-urgent' : ''}>
                      {detail.data.review_due ?? '미지정'}{detail.data.review_overdue && ' (기한 지남)'}
                    </span>
                  </p>
                  {detail.data.tags.length > 0 && (
                    <p className="text-xs mt-1 flex gap-1 flex-wrap">
                      {detail.data.tags.map((t) => (
                        <button key={t} className="chip" onClick={() => { setTag(t); setOffset(0) }}>#{t}</button>
                      ))}
                    </p>
                  )}
                </div>
                {detail.data.can_edit && !detail.data.is_deleted && <div className="flex gap-1 shrink-0">
                  <button className="btn btn-sm" onClick={() => openEditor(detail.data)}>수정</button>
                  <button className="btn btn-sm" aria-label="문서 삭제" disabled={remove.isPending}
                    onClick={() => { if (window.confirm('이 문서를 삭제하시겠습니까? 되살릴 수 있습니다.')) remove.mutate(detail.data.id) }}><Trash2 size={13}/></button>
                </div>}
              </div>
              <pre className="whitespace-pre-wrap break-words text-sm font-sans leading-relaxed min-h-32">{detail.data.body || '본문이 없습니다.'}</pre>

              <div className="pt-3 border-t border-surface-border">
                <h3 className="font-semibold mb-2">첨부 문서</h3>
                <Attachments entityType="KNOWLEDGE" entityId={detail.data.id} canUpload={detail.data.can_edit && !detail.data.is_deleted}
                             invalidate={[['knowledge-detail', detail.data.id]]}/>
              </div>

              <LinkedHandovers article={detail.data} />
              <Revisions article={detail.data} onRestored={() => {
                qc.invalidateQueries({ queryKey: ['knowledge-detail', detail.data.id] })
                qc.invalidateQueries({ queryKey: ['knowledge'] })
              }} />
            </article>
          ) : <div className="grid place-items-center min-h-64 text-ink-muted">왼쪽 목록에서 운영 문서를 선택하거나 새로 등록하세요.</div>}
        </section>
      </div>
    </div>
  )
}

/** 이 절차와 엮인 인수인계. 볼 수 없는 인계는 서버가 빼고 주므로 여기 나오지 않는다. */
function LinkedHandovers({ article }: { article: KnowledgeArticle }) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState('')
  const [error, setError] = useState('')
  const links = useQuery({
    queryKey: ['knowledge-links', article.id],
    queryFn: () => knowledgeApi.links(article.id),
  })
  const add = useMutation({
    mutationFn: (id: number) => knowledgeApi.link(article.id, id),
    onSuccess: () => { setAdding(''); setError(''); qc.invalidateQueries({ queryKey: ['knowledge-links', article.id] }) },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '연결하지 못했습니다.'),
  })
  const drop = useMutation({
    mutationFn: (id: number) => knowledgeApi.unlink(article.id, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['knowledge-links', article.id] }),
  })
  return (
    <div className="pt-3 border-t border-surface-border space-y-2">
      <h3 className="font-semibold flex items-center gap-1"><Link2 size={14}/> 관련 인수인계</h3>
      {links.data?.length === 0 && <p className="text-sm text-ink-muted">연결된 인수인계가 없습니다.</p>}
      <ul className="space-y-1">
        {links.data?.map((x) => (
          <li key={x.handover_id} className="flex items-center gap-2 text-sm">
            <Link className="text-brand hover:underline break-words" to={`/handovers?id=${x.handover_id}`}>{x.title}</Link>
            {article.can_edit && (
              <button className="btn btn-sm" aria-label={`${x.title} 연결 끊기`}
                      onClick={() => drop.mutate(x.handover_id)}>끊기</button>
            )}
          </li>
        ))}
      </ul>
      <div className="flex gap-1 items-center flex-wrap">
        <input className="input w-32" inputMode="numeric" placeholder="인계 번호" aria-label="연결할 인수인계 번호"
               value={adding} onChange={(e) => setAdding(e.target.value.replace(/[^0-9]/g, ''))}/>
        <button className="btn btn-sm" disabled={!adding || add.isPending}
                onClick={() => add.mutate(Number(adding))}>연결</button>
        <span className="text-xs text-ink-faint">내가 볼 수 있는 인계만 연결됩니다.</span>
      </div>
      {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}
    </div>
  )
}

/** 개정 이력 — 판을 골라 지금 내용과 나란히 비교하고, 필요하면 되살린다. */
function Revisions({ article, onRestored }: { article: KnowledgeArticle; onRestored: () => void }) {
  const [open, setOpen] = useState(false)
  const [compare, setCompare] = useState<number | null>(null)
  const [error, setError] = useState('')
  const list = useQuery({
    queryKey: ['knowledge-revisions', article.id, article.version_no],
    queryFn: () => knowledgeApi.revisions(article.id),
    enabled: open,
  })
  const body = useQuery({
    queryKey: ['knowledge-revision', article.id, compare],
    queryFn: () => knowledgeApi.revision(article.id, compare!),
    enabled: open && compare != null,
  })
  const restore = useMutation({
    mutationFn: (versionNo: number) => knowledgeApi.restoreRevision(article.id, versionNo),
    onSuccess: () => { setCompare(null); setError(''); onRestored() },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '복원하지 못했습니다.'),
  })
  useEffect(() => { setCompare(null) }, [article.id])

  return (
    <div className="pt-3 border-t border-surface-border space-y-2">
      <button className="font-semibold flex items-center gap-1" onClick={() => setOpen((v) => !v)}>
        <History size={14}/> 개정 이력 {open ? '접기' : '펼치기'}
      </button>
      {open && (
        <div className="space-y-2">
          {list.isLoading && <p className="text-sm text-ink-muted">이력을 불러오는 중…</p>}
          <table className="w-full text-sm">
            <thead className="text-ink-muted">
              <tr><th className="text-left py-1">판</th><th className="text-left">수정자</th>
                  <th className="text-left">시각</th><th className="text-left">사유</th><th/></tr>
            </thead>
            <tbody>
              {list.data?.map((r) => (
                <tr key={r.version_no} className="border-t border-surface-border/60">
                  <td className="py-1">v{r.version_no}</td>
                  <td>{r.changed_by_name ?? '-'}</td>
                  <td className="whitespace-nowrap">{r.changed_at.slice(0, 16).replace('T', ' ')}</td>
                  <td className="break-words">{r.change_note ?? '-'}</td>
                  <td className="text-right whitespace-nowrap">
                    <button className="btn btn-sm" onClick={() => setCompare(r.version_no)}>비교</button>
                    {article.can_edit && r.version_no !== article.version_no && (
                      <button className="btn btn-sm ml-1" disabled={restore.isPending}
                              onClick={() => { if (window.confirm(`v${r.version_no} 내용으로 되돌리시겠습니까? 새 판으로 저장됩니다.`)) restore.mutate(r.version_no) }}>복원</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}
          {compare != null && body.data && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div className="min-w-0">
                <h4 className="text-sm font-medium">v{body.data.version_no} (과거)</h4>
                <pre className="whitespace-pre-wrap break-words text-xs bg-surface-sunken rounded p-2 max-h-72 overflow-auto">{body.data.body || '(본문 없음)'}</pre>
              </div>
              <div className="min-w-0">
                <h4 className="text-sm font-medium">v{article.version_no} (현재)</h4>
                <pre className="whitespace-pre-wrap break-words text-xs bg-surface-sunken rounded p-2 max-h-72 overflow-auto">{article.body || '(본문 없음)'}</pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
