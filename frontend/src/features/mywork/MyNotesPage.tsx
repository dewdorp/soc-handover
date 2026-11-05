import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useBlocker, useNavigate } from 'react-router-dom'
import { LockKeyhole, Plus, Search } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { notesApi, type NoteText, type PersonalNote } from '@/services/api/notes'
import { taskApi } from '@/services/api/tasks'

const EMPTY = { title: '', body: '' }
const formatTime = (iso: string) => new Date(iso).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' })

type PendingAction = { kind: 'select'; note: PersonalNote | null } | { kind: 'reload' } | { kind: 'delete' }

export default function MyNotesPage() {
  const { data: me } = useMe()
  return me && <Notes key={me.id} userId={me.id} />
}

function Notes({ userId }: { userId: number }) {
  const list = useQuery({ queryKey: ['personal-notes', userId], queryFn: ({ signal }) => notesApi.list(userId, signal) })
  const [search, setSearch] = useState('')
  const [original, setOriginal] = useState<PersonalNote | null>(null)
  const [draft, setDraft] = useState<NoteText>(EMPTY)
  const [action, setAction] = useState<PendingAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  // '고른 글만' 넘긴다 — 메모 전체가 아니라, 지금 선택한 범위.
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const [selected, setSelected] = useState('')
  const readSelection = () => {
    const el = bodyRef.current
    if (!el) return
    setSelected(el.value.slice(el.selectionStart, el.selectionEnd).trim())
  }
  const source = original ?? EMPTY
  const dirty = draft.title !== source.title || draft.body !== source.body
  const canSave = !list.isPending && !busy && !conflict && dirty && Boolean(draft.title.trim())
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && nextLocation.pathname !== '/login' && nextLocation.pathname !== '/change-password'
    && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  function open(note: PersonalNote | null) {
    setOriginal(note)
    setDraft(note ? { title: note.title, body: note.body } : EMPTY)
    setConflict(false)
    setError('')
    setNotice('')
  }
  function select(note: PersonalNote | null) {
    if (dirty) setAction({ kind: 'select', note })
    else open(note)
  }
  function edit(text: NoteText) {
    setDraft(text)
    setNotice('')
  }
  async function commit(kind: 'save' | 'delete' | 'reload') {
    setAction(null)
    setError('')
    setBusy(true)
    try {
      if (kind === 'save') {
        const text = { title: draft.title.trim(), body: draft.body }
        open(original ? await notesApi.update(userId, original, text) : await notesApi.create(userId, text))
        setNotice('저장했습니다.')
      } else if (kind === 'delete' && original) {
        await notesApi.remove(userId, original)
        open(null)
        setNotice('삭제했습니다.')
      } else if (kind === 'reload' && original) {
        open(await notesApi.get(userId, original.id))
      }
      await list.refetch()
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 409) {
        setConflict(true)
        setError('다른 창에서 메모가 변경되었습니다. 작성한 내용은 이 화면에 남아 있습니다.')
      } else setError(e instanceof ApiRequestError ? e.message : '요청을 처리하지 못했습니다. 다시 시도해 주세요.')
    } finally { setBusy(false) }
  }
  const term = search.trim().toLocaleLowerCase()
  const filtered = list.data?.filter(note => [note.title, note.body].some(s => s.toLocaleLowerCase().includes(term)))
  const leaving = blocker.state === 'blocked'

  return <div className="mx-auto w-full max-w-6xl p-3 sm:p-5 space-y-4">
    <header className="flex items-start justify-between gap-3">
      <div><h1 className="text-lg font-semibold">내 메모</h1>
        <p className="mt-1 flex items-center gap-1.5 text-ink-muted"><LockKeyhole size={14} aria-hidden="true" />나만 볼 수 있는 업무 메모입니다.</p></div>
      <button type="button" className="btn" disabled={busy} onClick={() => select(null)}><Plus size={14} />새 메모</button>
    </header>
    <div className="grid gap-3 md:grid-cols-[minmax(14rem,1fr)_minmax(0,2fr)] items-start">
      <section className="card min-w-0 p-3" aria-label="메모 목록">
        <h2 className="font-semibold mb-2">메모 목록 {filtered && <span className="text-ink-muted font-normal">{filtered.length}건</span>}</h2>
        <label className="relative block"><Search size={14} className="absolute left-2 top-2 text-ink-muted" aria-hidden="true" />
          <input type="search" aria-label="메모 검색" className="input w-full pl-7" placeholder="제목·내용 검색" data-grid-search value={search} onChange={e => setSearch(e.target.value)} /></label>
        {list.isPending && <p className="pt-3 text-ink-muted">불러오는 중…</p>}
        {list.isError && <p className="pt-3" role="alert">목록을 불러오지 못했습니다. <button className="text-brand underline" onClick={() => list.refetch()}>다시 시도</button></p>}
        {filtered?.length === 0 && <p className="py-5 text-center text-ink-muted">{term ? '검색 결과가 없습니다.' : '저장한 메모가 없습니다.'}</p>}
        <ul className="mt-2 max-h-52 overflow-auto md:max-h-[62vh]">{filtered?.map(note => <li key={note.id}>
          <button type="button" aria-pressed={original?.id === note.id} disabled={busy} onClick={() => { if (original?.id !== note.id) select(note) }}
            className={`w-full rounded-md border-l-2 px-2 py-2 text-left ${original?.id === note.id ? 'border-brand bg-brand-soft' : 'border-transparent hover:bg-surface-sunken'}`}>
            <span className="block truncate font-medium">{note.title}</span>
            <time className="block text-xs text-ink-muted" dateTime={note.updated_at}>{formatTime(note.updated_at)}</time>
          </button></li>)}</ul>
      </section>
      <form className="card min-w-0 p-3 sm:p-4 space-y-3" onSubmit={e => { e.preventDefault(); if (canSave) void commit('save') }}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{original ? '메모 편집' : '새 메모'}</h2>
          <span className="text-sm text-ink-muted" role="status">{busy ? '처리 중…' : dirty ? '저장하지 않은 변경사항' : notice}</span></div>
        <label className="block"><span className="block mb-1">제목</span>
          <input className="input w-full" placeholder="메모 제목" required maxLength={200} disabled={busy} value={draft.title} onChange={e => edit({ ...draft, title: e.target.value })} /></label>
        <label className="block"><span className="block mb-1">내용</span>
          <textarea ref={bodyRef} className="input w-full h-60 min-h-32 py-2 resize-y" placeholder="기억해 둘 내용을 적어 주세요." maxLength={50000} disabled={busy} value={draft.body}
            onSelect={readSelection} onKeyUp={readSelection} onMouseUp={readSelection}
            onChange={e => { edit({ ...draft, body: e.target.value }); readSelection() }} /></label>
        <SelectionActions selected={selected} busy={busy} onError={setError} />
        {error && <div className="text-state-urgent" role="alert">{error} {conflict && <button type="button" className="btn" disabled={busy} onClick={() => setAction({ kind: 'reload' })}>최신 내용 불러오기</button>}</div>}
        <div className="flex justify-end gap-2">{original && <button type="button" className="btn text-state-urgent" disabled={busy || conflict} onClick={() => setAction({ kind: 'delete' })}>삭제</button>}
          <button className="btn btn-primary" disabled={!canSave}>저장</button></div>
      </form>
    </div>
    {(action || leaving) && <ConfirmDialog title={leaving ? '이 화면을 나갈까요?' : action?.kind === 'delete' ? '메모를 삭제할까요?' : action?.kind === 'reload' ? '최신 내용을 불러올까요?' : '작성 중인 메모를 닫을까요?'}
      confirmLabel={leaving ? '나가기' : action?.kind === 'delete' ? '삭제' : action?.kind === 'reload' ? '불러오기' : '변경사항 버리기'} danger={action?.kind === 'delete'} busy={busy}
      onCancel={() => { setAction(null); if (leaving) blocker.reset() }} onConfirm={() => {
        if (leaving) { blocker.proceed(); return }
        if (action?.kind === 'select') { open(action.note); setAction(null) }
        else if (action) void commit(action.kind)
      }}>{action?.kind === 'delete' && !leaving ? `‘${original?.title}’ 메모를 삭제하면 복구할 수 없습니다.` : '계속하면 이 화면의 변경사항을 버립니다.'}</ConfirmDialog>}
  </div>
}


// --------------------------------------------------------------------------- 고른 글로 만들기

/**
 * 메모에서 **선택한 범위만** 할 일 · 인계 초안으로 옮긴다.
 *
 * 메모로 되돌아오는 링크는 만들지 않는다. 개인 메모는 공유 문서·검색·내보내기에서
 * 빠져 있는 자리인데, 만들어진 업무가 메모를 가리키면 그 경계가 무너진다. 옮긴 뒤에는
 * 두 글이 서로 모르는 별개의 기록이다.
 */
function SelectionActions({ selected, busy, onError }: {
  selected: string
  busy: boolean
  onError: (message: string) => void
}) {
  const navigate = useNavigate()
  const firstLine = selected.split('\n').find(l => l.trim())?.trim() ?? ''
  const title = firstLine.slice(0, 200)

  const toTask = useMutation({
    mutationFn: () => taskApi.create({ title, description: selected.slice(0, 5000) }),
    onSuccess: (task) => navigate(`/tasks?id=${task.id}`),
    onError: (e) => onError(e instanceof ApiRequestError ? e.message : '할 일을 만들지 못했습니다.'),
  })

  const toHandover = () => {
    // 라우터 state 로만 넘긴다 — 디스크(localStorage)에 남기지 않는다(공용 PC).
    navigate('/handovers', { state: { draft: { title, content: selected.slice(0, 100000) } } })
  }

  if (!selected) {
    return (
      <p className="text-sm text-ink-faint">
        내용에서 옮길 부분을 <strong>선택</strong>하면 할 일 · 인계 초안으로 만들 수 있습니다.
        메모 전체가 아니라 고른 글만 넘어가며, 메모로 되돌아오는 링크는 만들지 않습니다.
      </p>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-surface-border bg-surface-sunken px-2 py-1.5">
      <span className="text-sm text-ink-muted">고른 글 {selected.length}자</span>
      <span className="flex-1" />
      <button type="button" className="btn btn-sm" disabled={busy || !title || toTask.isPending}
              onClick={() => toTask.mutate()}>내 할 일로 만들기</button>
      <button type="button" className="btn btn-sm" disabled={busy || !title} onClick={toHandover}>
        인계 초안 만들기
      </button>
    </div>
  )
}
