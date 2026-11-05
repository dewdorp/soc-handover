/**
 * 업무에 걸린 사람들 — 대표 담당 · 공동 담당 · 필수 인수자 · 참고.
 *
 * 화면이 지키는 것
 *   · 역할이 무엇을 뜻하는지 고르는 자리에 그대로 적는다. '참고'가 확인 대기로 잡히지
 *     않는다는 사실을 모르면 아무도 참고를 쓰지 않는다.
 *   · 전파는 **누르기 전에 몇 명인지** 보여 준다. 숫자를 보지 않고 누르는 전파는
 *     '전 직원에게 침해사고 상세가 간' 사고로 끝난다.
 *   · 전파가 글의 공개 범위를 바꾸지 않는다는 것을 서버가 준 문구 그대로 보여 준다.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, UserPlus, X } from 'lucide-react'
import { useEscape } from '@/hooks/useHotkeys'
import { ApiRequestError } from '@/services/api/client'
import { groupsApi } from '@/services/api/groups'
import {
  participantApi, ROLE_HINT, ROLE_LABEL,
  type Participant, type ParticipantRole, type PropagatePreview,
} from '@/services/api/participants'
import { referenceApi } from '@/services/api/reference'

const ROLES: ParticipantRole[] = ['OWNER', 'CO_OWNER', 'REQUIRED', 'FYI']

export default function ParticipantsPanel({ handoverId, canEdit }: {
  handoverId: number
  canEdit: boolean
}) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState('')
  const [addRole, setAddRole] = useState<ParticipantRole>('REQUIRED')
  const [propagating, setPropagating] = useState(false)

  const { data } = useQuery({
    queryKey: ['participants', handoverId],
    queryFn: () => participantApi.list(handoverId),
  })
  const users = useQuery({
    queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000,
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['participants', handoverId] })
    qc.invalidateQueries({ queryKey: ['handover', handoverId] })
  }
  const fail = (e: unknown) => setError(e instanceof ApiRequestError ? e.message : '바꾸지 못했습니다.')

  const save = useMutation({
    mutationFn: (rows: Participant[]) =>
      participantApi.set(handoverId, rows.map((r) => ({ user_id: r.user_id, role: r.role }))),
    onSuccess: () => { setError(null); setAdding(''); refresh() },
    onError: fail,
  })

  const rows = data?.participants ?? []
  const counts = data?.counts
  const candidates = useMemo(
    () => (users.data ?? []).filter((u) => !rows.some((r) => r.user_id === u.id)),
    [users.data, rows])

  const setRole = (userId: number, role: ParticipantRole) =>
    save.mutate(rows.map((r) => (r.user_id === userId ? { ...r, role } : r)))
  const remove = (userId: number) => save.mutate(rows.filter((r) => r.user_id !== userId))
  const add = () => {
    const user = (users.data ?? []).find((u) => u.id === Number(adding))
    if (!user) return
    save.mutate([...rows, {
      user_id: user.id, display_name: user.display_name, username: '',
      role: addRole, role_label: ROLE_LABEL[addRole], must_ack: addRole !== 'FYI', note: null,
    }])
  }

  return (
    <section className="space-y-1.5" aria-label="담당 · 전파 대상">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-ink-muted">담당 · 전파 대상</h3>
        {counts && (
          <span className="text-sm text-ink-faint tabular-nums">
            담당 {counts.owner + counts.co_owner} · 필수 {counts.required} · 참고 {counts.fyi}
            {counts.must_ack > 0 && <> · <span className="text-state-check">확인해야 할 사람 {counts.must_ack}</span></>}
          </span>
        )}
        <span className="flex-1" />
        {canEdit && (
          <button className="btn btn-sm" onClick={() => setPropagating(true)}>
            <Send size={11} /> 그룹에 전파
          </button>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}

      {rows.length > 0 ? (
        <ul className="divide-y divide-surface-border border border-surface-border rounded">
          {rows.map((p) => (
            <li key={p.user_id} className="flex flex-wrap items-center gap-2 px-2 py-1">
              <span className="font-medium">{p.display_name}</span>
              {p.must_ack
                ? <span className="text-xs text-state-check">확인 필요</span>
                : <span className="text-xs text-ink-faint">확인 불필요</span>}
              {p.note && <span className="text-sm text-ink-faint truncate max-w-[14rem]" title={p.note}>{p.note}</span>}
              <span className="flex-1" />
              {canEdit ? (
                <>
                  <select className="input input-sm" value={p.role} aria-label={`${p.display_name} 역할`}
                          disabled={save.isPending}
                          onChange={(e) => setRole(p.user_id, e.target.value as ParticipantRole)}>
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                  </select>
                  <button className="text-ink-faint hover:text-state-urgent" aria-label={`${p.display_name} 빼기`}
                          disabled={save.isPending} onClick={() => remove(p.user_id)}>
                    <X size={12} />
                  </button>
                </>
              ) : <span className="text-sm">{p.role_label}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-faint">아직 지정된 사람이 없습니다.</p>
      )}

      {canEdit && (
        <div className="flex flex-wrap items-end gap-1.5">
          <select className="input flex-1 min-w-[10rem]" value={adding} aria-label="사람 추가"
                  onChange={(e) => setAdding(e.target.value)}>
            <option value="">사람 고르기…</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
          <select className="input" value={addRole} aria-label="추가할 역할"
                  onChange={(e) => setAddRole(e.target.value as ParticipantRole)}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <button className="btn btn-sm btn-primary" disabled={!adding || save.isPending} onClick={add}>
            <UserPlus size={11} /> 넣기
          </button>
          <p className="w-full text-xs text-ink-faint">{ROLE_HINT[addRole]}</p>
        </div>
      )}

      {propagating && (
        <PropagateDialog handoverId={handoverId} onClose={() => setPropagating(false)}
                         onDone={() => { setPropagating(false); refresh() }} onError={fail} />
      )}
    </section>
  )
}

// --------------------------------------------------------------------------- 전파

function PropagateDialog({ handoverId, onClose, onDone, onError }: {
  handoverId: number
  onClose: () => void
  onDone: () => void
  onError: (e: unknown) => void
}) {
  useEscape(onClose)
  const [picked, setPicked] = useState<number[]>([])
  const [role, setRole] = useState<ParticipantRole>('FYI')
  const [note, setNote] = useState('')
  const [excluded, setExcluded] = useState<number[]>([])
  const groups = useQuery({ queryKey: ['my-groups'], queryFn: () => groupsApi.mine(), staleTime: 60_000 })

  const body = { group_ids: picked, role, exclude_user_ids: excluded, note: note.trim() || null }
  const preview = useQuery<PropagatePreview>({
    queryKey: ['propagate-preview', handoverId, picked.join(), role, excluded.join()],
    queryFn: () => participantApi.preview(handoverId, body),
    enabled: picked.length > 0,
  })
  const apply = useMutation({
    mutationFn: () => participantApi.propagate(handoverId, body),
    onSuccess: onDone, onError,
  })

  const toggle = (id: number) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-start justify-center p-4"
         role="dialog" aria-modal="true" aria-label="그룹에 전파">
      <div className="bg-surface rounded shadow-lg border border-surface-border w-full max-w-lg mt-16 p-3 space-y-2">
        <div className="flex items-center">
          <h3 className="font-medium flex-1">그룹에 전파</h3>
          <button className="btn btn-sm" onClick={onClose} aria-label="닫기"><X size={14} /></button>
        </div>

        <fieldset className="border border-surface-border rounded p-2">
          <legend className="text-sm text-ink-muted px-1">어느 그룹에</legend>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {(groups.data ?? []).map((g) => (
              <label key={g.id} className="inline-flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={picked.includes(g.id)} onChange={() => toggle(g.id)} />
                {g.name}
              </label>
            ))}
            {groups.data?.length === 0 && (
              <span className="text-sm text-ink-faint">속한 그룹이 없습니다.</span>)}
          </div>
        </fieldset>

        <label className="block text-sm">
          어떤 역할로
          <select className="input w-full mt-0.5" value={role}
                  onChange={(e) => setRole(e.target.value as ParticipantRole)}>
            <option value="FYI">{ROLE_LABEL.FYI}</option>
            <option value="REQUIRED">{ROLE_LABEL.REQUIRED}</option>
          </select>
          <span className="block text-xs text-ink-faint mt-0.5">{ROLE_HINT[role]}</span>
        </label>

        <label className="block text-sm">
          사유 (받는 사람에게 함께 간다)
          <input className="input w-full mt-0.5" value={note} maxLength={300}
                 onChange={(e) => setNote(e.target.value)} placeholder="CERT 분석 요청 · 전사 공유" />
        </label>

        {preview.data && (
          <div className="rounded border border-surface-border bg-surface-sunken p-2 space-y-1">
            <p className="font-medium">
              {preview.data.add_count}명에게 <strong>{preview.data.role_label}</strong>(으)로 갑니다
            </p>
            <p className="text-sm tabular-nums">
              전파 뒤 — 담당 {preview.data.after.owner + preview.data.after.co_owner} ·
              필수 {preview.data.after.required} · 참고 {preview.data.after.fyi} ·
              제외 {preview.data.excluded_count}
            </p>
            {preview.data.excluded_already_stronger.length > 0 && (
              <p className="text-sm text-ink-faint">
                이미 더 강한 역할: {preview.data.excluded_already_stronger.join(', ')}
              </p>
            )}
            {preview.data.excluded_by_hand.length > 0 && (
              <p className="text-sm text-ink-faint">
                손으로 뺌: {preview.data.excluded_by_hand.join(', ')}
                <button className="ml-1 text-brand hover:underline" onClick={() => setExcluded([])}>되돌리기</button>
              </p>
            )}
            <p className="text-sm text-state-check">{preview.data.visibility_note}</p>
          </div>
        )}
        {picked.length === 0 && (
          <p className="text-sm text-ink-faint">그룹을 고르면 몇 명에게 가는지 먼저 보여 줍니다.</p>)}

        <div className="flex justify-end gap-1 pt-1">
          <button className="btn btn-sm" onClick={onClose}>취소</button>
          <button className="btn btn-sm btn-primary"
                  disabled={!preview.data?.add_count || apply.isPending}
                  onClick={() => apply.mutate()}>
            {preview.data ? `${preview.data.add_count}명에게 전파` : '전파'}
          </button>
        </div>
      </div>
    </div>
  )
}
