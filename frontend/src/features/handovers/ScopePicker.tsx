/**
 * 공개 범위 고르기 — '내 그룹만'(그룹 여럿 선택 가능) 또는 '전체 공개'.
 *
 * 기본은 **내 기본 그룹 하나**다. 전체 공개는 손으로 골라야 한다. 등록 화면에서 아무것도
 * 건드리지 않고 올리면 서버가 기본 그룹을 넣는다(전체 공개로 넘어가지 않는다).
 *
 * 그룹 이름은 관리자가 적은 **실제 이름**을 그대로 보여 준다. '그룹1 · 그룹2' 같은
 * 자리표를 쓰면 쓰는 사람이 무엇을 고르는지 알 수 없다.
 */
import { useQuery } from '@tanstack/react-query'
import { Globe, Users } from 'lucide-react'
import { groupsApi } from '@/services/api/groups'

export type Visibility = 'GROUPS' | 'ALL'

interface Props {
  visibility: Visibility
  groupIds: number[]
  onChange: (next: { visibility: Visibility; group_ids: number[] }) => void
  /** 수정 화면에서는 이미 붙어 있는 그룹 이름을 함께 보여 준다(내 그룹이 아닐 수도 있다). */
  currentNames?: string[]
}

export function useMyGroups() {
  return useQuery({ queryKey: ['my-groups'], queryFn: () => groupsApi.mine(), staleTime: 60_000 })
}

export default function ScopePicker({ visibility, groupIds, onChange, currentNames }: Props) {
  const { data: groups } = useMyGroups()
  const mine = groups ?? []
  const toggle = (id: number) => {
    const next = groupIds.includes(id) ? groupIds.filter((g) => g !== id) : [...groupIds, id]
    onChange({ visibility: 'GROUPS', group_ids: next })
  }

  return (
    <fieldset className="border border-surface-border rounded p-2 space-y-1.5">
      <legend className="text-sm text-ink-muted px-1">공개 범위</legend>

      <label className="flex items-start gap-1.5 cursor-pointer">
        <input type="radio" name="scope" className="mt-1" checked={visibility === 'GROUPS'}
               onChange={() => onChange({ visibility: 'GROUPS', group_ids: groupIds })} />
        <span className="flex-1">
          <span className="inline-flex items-center gap-1"><Users size={12} /> 내 그룹만</span>
          <span className="block text-sm text-ink-faint">
            고른 그룹에 속한 사람만 본다. 담당자 · 인수자로 지정된 사람은 그룹과 무관하게 본다.
          </span>
        </span>
      </label>

      {visibility === 'GROUPS' && (
        <div className="pl-5 flex flex-wrap gap-x-3 gap-y-1">
          {mine.map((g) => (
            <label key={g.id} className="inline-flex items-center gap-1 cursor-pointer text-base">
              <input type="checkbox" checked={groupIds.includes(g.id)} onChange={() => toggle(g.id)} />
              <span>{g.name}{g.is_default && <span className="text-xs text-brand ml-0.5">기본</span>}</span>
            </label>
          ))}
          {mine.length === 0 && (
            <span className="text-sm text-ink-faint">
              속한 그룹이 없습니다. 관리자에게 그룹 지정을 요청하십시오 — 그때까지는 내가 쓴 글만 보입니다.
            </span>
          )}
        </div>
      )}

      <label className="flex items-start gap-1.5 cursor-pointer">
        <input type="radio" name="scope" className="mt-1" checked={visibility === 'ALL'}
               onChange={() => onChange({ visibility: 'ALL', group_ids: groupIds })} />
        <span className="flex-1">
          <span className="inline-flex items-center gap-1"><Globe size={12} /> 전체 공개</span>
          <span className="block text-sm text-ink-faint">로그인한 모든 사람이 본다. 전사 공지 · 공통 절차에만 쓴다.</span>
        </span>
      </label>

      {currentNames && currentNames.length > 0 && visibility === 'GROUPS' && (
        <p className="pl-5 text-sm text-ink-faint">지금 공개된 그룹: {currentNames.join(' · ')}</p>
      )}
    </fieldset>
  )
}

/** 목록·상세에서 범위를 한 줄로 표시한다. */
export function ScopeBadge({ visibility, groupNames }: { visibility: string; groupNames: string[] }) {
  if (visibility === 'ALL') {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-state-waiting" title="로그인한 모든 사람이 봅니다">
        <Globe size={11} /> 전체 공개
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-sm text-ink-muted"
          title={groupNames.length ? `${groupNames.join(' · ')} 그룹만 봅니다` : ''}>
      <Users size={11} /> {groupNames.length ? groupNames.join(' · ') : '그룹 미지정'}
    </span>
  )
}
