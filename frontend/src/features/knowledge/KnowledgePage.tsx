/** SOC 운영 지식: SOP·런북·장비 가이드·참고 자료. 문서 첨부와 공개 그룹을 같은 화면에서 관리. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, FilePlus, Pin, Search, Trash2 } from 'lucide-react'
import Attachments from '@/components/Attachments'
import { useMyGroups } from '@/features/handovers/ScopePicker'
import { ApiRequestError } from '@/services/api/client'
import { CATEGORIES, knowledgeApi, type KnowledgeArticle, type KnowledgeInput, type KnowledgeCategory } from '@/services/api/knowledge'

const TEMPLATE = [
  '1. 목적 및 적용 범위\n\n2. 탐지·확인 기준\n\n3. 1차 확인 방법\n\n4. 즉시 조치\n\n5. 후속 확인 및 교대 인계\n\n6. 관련 자료 및 수정 이력',
  '1. 탐지 개요\n\n2. 확인할 로그·증적\n\n3. 정상/오탐 구분\n\n4. 추가 조사\n\n5. 조치·차단·재발 방지\n\n6. 보고·연락 기준',
]

function blank(): KnowledgeInput {
  return { category: '운영 절차', title: '', body: '', visibility: 'ALL',
           group_ids: [], is_pinned: false, review_due: null }
}
function errorText(err: unknown): string {
  return err instanceof ApiRequestError ? err.message : '요청을 처리하지 못했습니다.'
}

export default function KnowledgePage() {
  const qc = useQueryClient()
  const { data: mine = [] } = useMyGroups()
  const [q, setQ] = useState('')
  const [applied, setApplied] = useState('')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [draft, setDraft] = useState<KnowledgeInput | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [offset, setOffset] = useState(0)
  const rows = useQuery({
    queryKey: ['knowledge', applied, category, offset],
    queryFn: () => knowledgeApi.list(applied, category, offset),
  })
  const detail = useQuery({
    queryKey: ['knowledge-detail', selected],
    queryFn: () => knowledgeApi.get(selected!),
    enabled: selected != null,
  })
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
    onSuccess: () => { setSelected(null); qc.invalidateQueries({ queryKey: ['knowledge'] }); setMessage('삭제했습니다.') },
    onError: (err) => setMessage(errorText(err)),
  })
  const openEditor = (row?: KnowledgeArticle) => {
    setEditingId(row?.id ?? null)
    setDraft(row ? {
      category: row.category, title: row.title, body: row.body,
      visibility: row.visibility, group_ids: [...row.group_ids],
      is_pinned: row.is_pinned, review_due: row.review_due, version_no: row.version_no,
    } : blank())
    setMessage('')
  }
  const onSave = () => {
    if (!draft?.title.trim()) { setMessage('제목을 입력하십시오.'); return }
    if (draft.visibility === 'GROUPS' && !draft.group_ids.length) {
      setMessage('그룹을 고르거나 전체 공개를 선택하십시오.'); return
    }
    save.mutate({ ...draft, title: draft.title.trim() })
  }
  const set = (v: Partial<KnowledgeInput>) => setDraft((d) => d ? { ...d, ...v } : d)

  return (
    <div className="p-3 sm:p-4 space-y-3 h-full overflow-auto">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold flex gap-2 items-center"><BookOpen size={18} /> 운영 지식</h1>
          <p className="text-sm text-ink-muted">관제 절차·분석 가이드·비상 연락·점검 체크리스트와 문서 파일을 함께 보관합니다.</p>
        </div>
        <button className="btn btn-primary" onClick={() => openEditor()}><FilePlus size={14} /> 새 문서</button>
      </header>
      {message && <p role="status" className="text-sm text-ink-muted">{message}</p>}
      <div className="grid grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)] gap-3 min-h-[440px]">
        <aside className="card p-3 space-y-2">
          <div className="flex gap-1">
            <input className="input w-full" placeholder="제목·본문 검색" aria-label="운영 지식 검색"
                   value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter') { setApplied(q.trim()); setOffset(0) } }} />
            <button className="btn" aria-label="검색" onClick={() => { setApplied(q.trim()); setOffset(0) }}><Search size={15}/></button>
          </div>
          <select className="input w-full" aria-label="문서 분류" value={category}
                  onChange={(e) => { setCategory(e.target.value); setOffset(0) }}>
            <option value="">전체 분류</option>
            {CATEGORIES.map((x) => <option key={x}>{x}</option>)}
          </select>
          {rows.isLoading && <p className="text-ink-muted p-3">불러오는 중…</p>}
          {rows.isError && <div role="alert" className="text-state-urgent p-3">목록 오류 <button onClick={() => rows.refetch()}>다시 시도</button></div>}
          <div className="divide-y divide-surface-border/70">
            {rows.data?.map((row) => (
              <button key={row.id} onClick={() => { setSelected(row.id); setDraft(null); setMessage('') }}
                      className={`block text-left w-full py-2.5 px-1 hover:bg-surface-sunken rounded ${selected === row.id ? 'bg-brand-soft' : ''}`}>
                <span className="text-sm text-ink-faint">{row.category} {row.visibility === 'ALL' ? '· 전체' : '· 그룹'}</span>
                <span className="block font-medium break-words">{row.is_pinned && <Pin size={12} className="inline mr-1"/>}{row.title}</span>
                {row.review_due && <span className="block text-xs text-ink-faint">재검토: {row.review_due}</span>}
              </button>
            ))}
          </div>
          {rows.data?.length === 0 && <p className="text-ink-muted p-3">등록된 자료가 없습니다.</p>}
          <div className="flex justify-between">
            <button className="btn btn-sm" disabled={offset===0} onClick={() => setOffset(Math.max(0,offset-50))}>이전</button>
            <button className="btn btn-sm" disabled={(rows.data?.length ?? 0)<50} onClick={() => setOffset(offset+50)}>다음</button>
          </div>
        </aside>
        <section className="card p-3 sm:p-4 min-w-0">
          {draft ? (
            <div className="space-y-3">
              <h2 className="font-semibold">{editingId == null ? '운영 문서 등록' : '운영 문서 수정'}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <label className="space-y-1 block"><span className="text-sm">분류</span>
                  <select className="input w-full" value={draft.category} onChange={(e) => set({category:e.target.value as KnowledgeCategory})}>
                    {CATEGORIES.map(x => <option key={x}>{x}</option>)}
                  </select></label>
                <label className="space-y-1 block"><span className="text-sm">재검토 예정일 (선택)</span>
                  <input type="date" className="input w-full" value={draft.review_due ?? ''}
                         onChange={(e) => set({review_due:e.target.value||null})}/></label>
              </div>
              <label className="space-y-1 block"><span className="text-sm">제목</span>
                <input className="input w-full" maxLength={200} value={draft.title} onChange={(e)=>set({title:e.target.value})}/></label>
              <label className="space-y-1 block"><span className="text-sm">절차·참고 내용</span>
                <textarea className="input w-full min-h-[240px] resize-y" value={draft.body} onChange={(e)=>set({body:e.target.value})}/></label>
              {editingId == null && <div className="flex gap-2 flex-wrap">
                <button className="btn btn-sm" onClick={()=>set({body:TEMPLATE[0]})}>운영 절차 양식</button>
                <button className="btn btn-sm" onClick={()=>set({body:TEMPLATE[1]})}>분석 가이드 양식</button>
              </div>}
              <fieldset className="space-y-2 border rounded border-surface-border p-2">
                <legend className="text-sm px-1">공개 범위</legend>
                <div className="flex flex-wrap gap-3">
                  <label><input type="radio" checked={draft.visibility==='ALL'} onChange={()=>set({visibility:'ALL',group_ids:[]})}/> 전체 공유 (그룹 미지정)</label>
                  <label><input type="radio" checked={draft.visibility==='GROUPS'} onChange={()=>set({visibility:'GROUPS'})}/> 그룹 선택</label>
                </div>
                {draft.visibility==='GROUPS' && <div className="flex gap-3 flex-wrap">
                  {mine.map(g => <label key={g.id}><input type="checkbox" checked={draft.group_ids.includes(g.id)}
                    onChange={(e)=>set({group_ids:e.target.checked?[...draft.group_ids,g.id]:draft.group_ids.filter(id=>id!==g.id)})}/> {g.name}</label>)}
                  {!mine.length && <p className="text-state-urgent">소속 그룹이 없습니다. 관리자에게 문의하세요.</p>}
                </div>}
              </fieldset>
              <label className="text-sm"><input type="checkbox" checked={draft.is_pinned} onChange={(e)=>set({is_pinned:e.target.checked})}/> 목록 상단에 고정</label>
              <div className="flex gap-2 justify-end">
                <button className="btn" onClick={()=>{setDraft(null);setEditingId(null)}}>취소</button>
                <button className="btn btn-primary" disabled={save.isPending} onClick={onSave}>저장</button>
              </div>
              <p className="text-xs text-ink-faint">첨부파일은 문서 저장 후 추가할 수 있습니다.</p>
            </div>
          ) : selected != null ? (
            detail.isLoading ? <p>문서를 불러오는 중…</p> :
            detail.isError || !detail.data ? <div role="alert">열람할 수 없는 문서입니다. <button onClick={()=>detail.refetch()}>재시도</button></div> :
            <article className="space-y-3">
              <div className="flex gap-2 justify-between items-start">
                <div>
                  <p className="text-sm text-ink-muted">{detail.data.category} · {detail.data.visibility==='ALL'?'전체 공유':'그룹 공개'}</p>
                  <h2 className="text-lg font-semibold break-words">{detail.data.title}</h2>
                  <p className="text-xs text-ink-muted">v{detail.data.version_no} · 재검토 {detail.data.review_due ?? '미지정'}</p>
                </div>
                {detail.data.can_edit && <div className="flex gap-1 shrink-0">
                  <button className="btn btn-sm" onClick={()=>openEditor(detail.data)}>수정</button>
                  <button className="btn btn-sm" aria-label="문서 삭제" disabled={remove.isPending}
                    onClick={()=>{if(window.confirm('이 문서를 삭제하시겠습니까?'))remove.mutate(detail.data.id)}}><Trash2 size={13}/></button>
                </div>}
              </div>
              <pre className="whitespace-pre-wrap break-words text-sm font-sans leading-relaxed min-h-32">{detail.data.body || '본문이 없습니다.'}</pre>
              <div className="pt-3 border-t border-surface-border">
                <h3 className="font-semibold mb-2">첨부 문서</h3>
                <Attachments entityType="KNOWLEDGE" entityId={detail.data.id} canUpload={detail.data.can_edit}
                             invalidate={[[ 'knowledge-detail',detail.data.id ]]}/>
              </div>
            </article>
          ) : <div className="grid place-items-center min-h-64 text-ink-muted">왼쪽 목록에서 운영 문서를 선택하거나 새로 등록하세요.</div>}
        </section>
      </div>
    </div>
  )
}
