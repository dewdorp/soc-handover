/**
 * 열람 그룹 관리 — 그룹 만들기 · 이름 바꾸기 · 사용 중지 · 구성원 · 미분류 자료 이관.
 *
 * 이 화면은 그룹의 **이름과 건수**만 다룬다. 업무 제목·내용은 어디에도 나오지 않는다.
 * 그룹을 관리하는 권한이 다른 그룹 업무를 읽는 권한은 아니기 때문이다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Users, X } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useEscape } from '@/hooks/useHotkeys'
import { adminApi } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'
import { groupsApi, type Group } from '@/services/api/groups'

export default function GroupsTab() {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<Group | null>(null)
  const [memberOf, setMemberOf] = useState<Group | null>(null)
  const [stopping, setStopping] = useState<Group | null>(null)

  const { data: groups, isFetching } = useQuery({ queryKey: ['groups'], queryFn: () => groupsApi.list() })
  const { data: unclassified } = useQuery({
    queryKey: ['groups-unclassified'], queryFn: () => groupsApi.unclassified(),
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['groups'] })
    qc.invalidateQueries({ queryKey: ['groups-unclassified'] })
  }
  const fail = (err: unknown) => setError(err instanceof ApiRequestError ? err.message : '처리하지 못했습니다.')

  const toggle = useMutation({
    mutationFn: (g: Group) => groupsApi.update(g.id, { is_active: !g.is_active }),
    onSuccess: () => { setError(null); setStopping(null); refresh() },
    onError: (e) => { setStopping(null); fail(e) },
  })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-md font-medium">열람 그룹</h2>
        <span className="text-sm text-ink-faint">{groups ? `${groups.length}개` : ''}</span>
        <span className="flex-1" />
        <button className="btn btn-sm btn-primary" onClick={() => setCreating(true)}>
          <Plus size={12} /> 그룹
        </button>
      </div>

      <p className="text-sm text-ink-muted max-w-3xl leading-relaxed">
        그룹은 <strong>누가 어느 업무 원문을 볼 수 있는가</strong>를 정한다. 역할(관리자 · 근무 관리자)과는
        별개이며, 그룹을 관리할 수 있다고 해서 다른 그룹의 업무 내용이 보이지는 않는다.
        사용 중지한 그룹은 구성원을 지우지 않아도 그 즉시 열람에서 빠진다.
      </p>

      {error && <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}

      <div className={`overflow-auto border border-surface-border rounded bg-surface ${isFetching ? 'opacity-70' : ''}`}>
        <table className="w-full text-base whitespace-nowrap">
          <thead className="bg-surface-sunken text-ink-muted">
            <tr>{['그룹', '설명', '구성원', '업무', '상태', ''].map((h) => (
              <th key={h} className="text-left font-medium px-2 py-1">{h}</th>))}</tr>
          </thead>
          <tbody>
            {(groups ?? []).map((g) => (
              <tr key={g.id} className="border-t border-surface-border">
                <td className="px-2 py-1 font-medium">
                  {g.name}
                  {g.code === 'UNCLASSIFIED' && (
                    <span className="ml-1.5 text-xs text-ink-faint">(예약)</span>)}
                </td>
                <td className="px-2 py-1 text-ink-muted max-w-sm truncate" title={g.description ?? ''}>
                  {g.description ?? '—'}
                </td>
                <td className="px-2 py-1 tabular-nums">{g.member_count}</td>
                <td className="px-2 py-1 tabular-nums">{g.handover_count}</td>
                <td className="px-2 py-1">
                  {g.is_active
                    ? <span className="text-state-done">사용</span>
                    : <span className="text-ink-faint">중지</span>}
                </td>
                <td className="px-2 py-1 text-right space-x-1">
                  <button className="btn btn-sm" onClick={() => setMemberOf(g)}>
                    <Users size={12} /> 구성원
                  </button>
                  <button className="btn btn-sm" onClick={() => setRenaming(g)}>고치기</button>
                  <button
                    className="btn btn-sm"
                    disabled={g.code === 'UNCLASSIFIED' && g.is_active}
                    title={g.code === 'UNCLASSIFIED' && g.is_active ? '예약 그룹은 중지할 수 없습니다.' : ''}
                    onClick={() => (g.is_active ? setStopping(g) : toggle.mutate(g))}
                  >
                    {g.is_active ? '중지' : '다시 사용'}
                  </button>
                </td>
              </tr>
            ))}
            {groups?.length === 0 && (
              <tr><td colSpan={6} className="px-2 py-6 text-center text-ink-faint">그룹이 없습니다.</td></tr>)}
          </tbody>
        </table>
      </div>

      {unclassified && unclassified.total > 0 && (
        <MovePanel summary={unclassified} groups={(groups ?? []).filter((g) => g.is_active && g.code !== 'UNCLASSIFIED')}
                   onDone={refresh} onError={fail} />
      )}

      {creating && <GroupForm onClose={() => setCreating(false)} onDone={() => { setCreating(false); refresh() }} onError={fail} />}
      {renaming && <GroupForm group={renaming} onClose={() => setRenaming(null)} onDone={() => { setRenaming(null); refresh() }} onError={fail} />}
      {memberOf && <MemberPanel group={memberOf} onClose={() => setMemberOf(null)} onDone={refresh} onError={fail} />}

      {stopping && (
        <ConfirmDialog
          title={`'${stopping.name}' 그룹을 사용 중지합니다`}
          confirmLabel="사용 중지"
          busy={toggle.isPending}
          onConfirm={() => toggle.mutate(stopping)}
          onCancel={() => setStopping(null)}
        >
          <p>구성원은 그대로 남지만, 이 그룹에만 공개된 업무는 <strong>다음 요청부터</strong> 보이지 않습니다.</p>
          <p className="mt-1 text-ink-muted">그룹을 다시 사용으로 바꾸면 되돌아옵니다.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- 그룹 만들기 · 고치기

function GroupForm({ group, onClose, onDone, onError }: {
  group?: Group
  onClose: () => void
  onDone: () => void
  onError: (e: unknown) => void
}) {
  useEscape(onClose)
  const [name, setName] = useState(group?.name ?? '')
  const [description, setDescription] = useState(group?.description ?? '')
  const save = useMutation({
    mutationFn: () => (group
      ? groupsApi.update(group.id, { name: name.trim(), description: description.trim() || null })
      : groupsApi.create({ name: name.trim(), description: description.trim() || null })),
    onSuccess: onDone, onError,
  })

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-start justify-center p-4" role="dialog" aria-modal="true"
         aria-label={group ? '그룹 고치기' : '그룹 만들기'}>
      <form
        className="bg-surface rounded shadow-lg border border-surface-border w-full max-w-md mt-16 p-3 space-y-2"
        onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate() }}
      >
        <div className="flex items-center">
          <h3 className="font-medium flex-1">{group ? '그룹 고치기' : '그룹 만들기'}</h3>
          <button type="button" className="btn btn-sm" onClick={onClose} aria-label="닫기"><X size={14} /></button>
        </div>
        <label className="block text-sm">
          그룹 이름 *
          <input className="input w-full mt-0.5" value={name} maxLength={60} required autoFocus
                 onChange={(e) => setName(e.target.value)} placeholder="관제1팀 · CERT · 야간조" />
        </label>
        <label className="block text-sm">
          설명
          <input className="input w-full mt-0.5" value={description} maxLength={500}
                 onChange={(e) => setDescription(e.target.value)} placeholder="무엇을 보는 그룹인지" />
        </label>
        <div className="flex justify-end gap-1 pt-1">
          <button type="button" className="btn btn-sm" onClick={onClose}>취소</button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={!name.trim() || save.isPending}>저장</button>
        </div>
      </form>
    </div>
  )
}

// --------------------------------------------------------------------------- 구성원

function MemberPanel({ group, onClose, onDone, onError }: {
  group: Group
  onClose: () => void
  onDone: () => void
  onError: (e: unknown) => void
}) {
  useEscape(onClose)
  const qc = useQueryClient()
  const { data: members } = useQuery({
    queryKey: ['group-members', group.id], queryFn: () => groupsApi.members(group.id),
  })
  const { data: users } = useQuery({ queryKey: ['admin-users', '', '', 'true'], queryFn: () => adminApi.users('', '', 'true') })
  const [adding, setAdding] = useState('')

  const change = useMutation({
    // 소속은 '통째로 바꾸기'라서, 지금 소속을 먼저 읽고 이 그룹 하나만 더하거나 뺀다.
    mutationFn: async ({ userId, join }: { userId: number; join: boolean }) => {
      const own = await groupsApi.userGroups(userId)
      const ids = new Set(own.map((g) => g.id))
      if (join) ids.add(group.id)
      else ids.delete(group.id)
      const def = own.find((g) => g.is_default)
      const keepDefault = def && ids.has(def.id) ? def.id : (ids.size ? [...ids][0] : null)
      return groupsApi.setMemberships(userId, [...ids], keepDefault)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group-members', group.id] })
      setAdding('')
      onDone()
    },
    onError,
  })

  const memberIds = new Set((members ?? []).map((m) => m.user_id))
  const candidates = (users?.items ?? []).filter((u) => !memberIds.has(u.id))

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-start justify-center p-4" role="dialog" aria-modal="true"
         aria-label={`${group.name} 구성원`}>
      <div className="bg-surface rounded shadow-lg border border-surface-border w-full max-w-lg mt-12 p-3 space-y-2">
        <div className="flex items-center">
          <h3 className="font-medium flex-1">{group.name} · 구성원 {members?.length ?? 0}명</h3>
          <button className="btn btn-sm" onClick={onClose} aria-label="닫기"><X size={14} /></button>
        </div>
        <p className="text-sm text-ink-muted">바꾸면 그 사람의 <strong>다음 요청부터</strong> 적용된다.</p>

        <div className="flex gap-1">
          <select className="input flex-1" value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="추가할 사람">
            <option value="">사람 고르기…</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.username})</option>)}
          </select>
          <button className="btn btn-sm btn-primary" disabled={!adding || change.isPending}
                  onClick={() => change.mutate({ userId: Number(adding), join: true })}>넣기</button>
        </div>

        <ul className="max-h-72 overflow-auto divide-y divide-surface-border border border-surface-border rounded">
          {(members ?? []).map((m) => (
            <li key={m.user_id} className="flex items-center gap-2 px-2 py-1 text-base">
              <span className="flex-1">
                {m.display_name} <span className="text-ink-faint text-sm">({m.username})</span>
                {m.is_default && <span className="ml-1.5 text-xs text-brand">기본</span>}
                {!m.is_active && <span className="ml-1.5 text-xs text-ink-faint">비활성</span>}
              </span>
              <button className="btn btn-sm" disabled={change.isPending}
                      onClick={() => change.mutate({ userId: m.user_id, join: false })}>빼기</button>
            </li>
          ))}
          {members?.length === 0 && <li className="px-2 py-4 text-center text-ink-faint text-sm">아직 아무도 없습니다.</li>}
        </ul>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- 미분류 이관

function MovePanel({ summary, groups, onDone, onError }: {
  summary: { group_name: string; total: number; by_company: { company_id: number; company_name: string; count: number }[] }
  groups: Group[]
  onDone: () => void
  onError: (e: unknown) => void
}) {
  const [to, setTo] = useState('')
  const [company, setCompany] = useState('')
  const [moved, setMoved] = useState<{ moved: number; remaining: number } | null>(null)
  const move = useMutation({
    mutationFn: () => groupsApi.move({
      to_group_id: Number(to),
      company_id: company ? Number(company) : null,
    }),
    onSuccess: (r) => { setMoved(r); onDone() }, onError,
  })

  return (
    <section className="border border-surface-border rounded bg-surface-sunken p-3 space-y-2">
      <h3 className="font-medium">
        '{summary.group_name}'에 남은 자료 <span className="tabular-nums">{summary.total}건</span>
      </h3>
      <p className="text-sm text-ink-muted max-w-3xl leading-relaxed">
        그룹 기능을 켜기 전에 쌓인 자료다. <strong>전체 공개로 바뀐 것이 아니라</strong> '{summary.group_name}' 그룹
        하나에 속해 있다. 관계사별로 실제 그룹으로 옮기면 그 순간부터 그 그룹만 보게 된다.
      </p>
      <div className="flex flex-wrap items-end gap-1.5">
        <label className="text-sm">
          옮길 그룹
          <select className="input w-44 mt-0.5 block" value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">고르기…</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        </label>
        <label className="text-sm">
          관계사 (비우면 전부)
          <select className="input w-56 mt-0.5 block" value={company} onChange={(e) => setCompany(e.target.value)}>
            <option value="">전부 ({summary.total}건)</option>
            {summary.by_company.map((c) => (
              <option key={c.company_id} value={c.company_id}>{c.company_name} ({c.count}건)</option>))}
          </select>
        </label>
        <button className="btn btn-sm btn-primary" disabled={!to || move.isPending} onClick={() => move.mutate()}>
          옮기기
        </button>
      </div>
      {moved && (
        <p className="text-sm text-state-done" role="status">
          {moved.moved}건을 옮겼습니다. 남은 미분류 {moved.remaining}건.
        </p>
      )}
    </section>
  )
}
