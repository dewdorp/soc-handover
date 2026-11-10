/**
 * '이 공개 범위로 올리면 누가 못 보는가' — 저장 전에 보여 주는 경고.
 *
 * 그룹을 제한해 놓고 다른 그룹 사람을 담당자나 전파 대상으로 넣으면, **그 사람에게는
 * 제한이 풀린다**(일을 해야 하므로 서버가 열어 준다). 막지 않는 대신, 그것이 의도한
 * 일인지 쓰는 사람이 저장 전에 알게 한다. 판정은 서버가 한다 — 화면은 묻기만 한다.
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { groupsApi } from '@/services/api/groups'

interface Props {
  visibility: 'ALL' | 'GROUPS'
  groupIds: number[]
  /** 담당자 · 확인자 · 공동 담당 · 전파 대상으로 넣으려는 사람 */
  userIds: (number | null | undefined)[]
}

export default function ScopeWarning({ visibility, groupIds, userIds }: Props) {
  const ids = [...new Set(userIds.filter((x): x is number => typeof x === 'number' && x > 0))]
  const enabled = visibility === 'GROUPS' && groupIds.length > 0 && ids.length > 0
  const { data } = useQuery({
    queryKey: ['scope-check', visibility, [...groupIds].sort().join(','), [...ids].sort().join(',')],
    queryFn: () => groupsApi.scopeCheck({ visibility, group_ids: groupIds, user_ids: ids }),
    enabled,
    staleTime: 30_000,
  })
  if (!enabled || !data || data.outsiders.length === 0) return null
  return (
    <div role="alert" className="rounded bg-state-urgent-soft/30 p-2 text-sm space-y-1">
      <p className="flex gap-1.5">
        <AlertTriangle size={14} className="shrink-0 mt-0.5 text-state-urgent" />
        <span>
          <strong>{data.group_names.join(' · ')}</strong> 에만 공개하는 글인데,
          아래 사람은 그 그룹에 속해 있지 않습니다. 그대로 저장하면 이 사람들에게는
          이 글만 따로 열립니다.
        </span>
      </p>
      <ul className="pl-6 list-disc">
        {data.outsiders.map((x) => (
          <li key={x.user_id}>
            {x.display_name}
            <span className="text-ink-muted">
              {x.has_any_group ? ' (다른 그룹 소속)' : ' (소속 그룹 없음)'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
