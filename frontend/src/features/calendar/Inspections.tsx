/**
 * 오늘 돌아야 하는 정기 점검 — 근무 시작 점검 · 장비 상태 · 수집 상태 · 관계사 주기 점검.
 *
 * 새 메뉴를 만들지 않았다. 점검은 '점검' 종류의 반복 일정으로 등록하고, 여기서 그 날
 * 회차의 완료만 표시한다. 할 일 목록이 인계 · 할일 · 점검 셋으로 쪼개지면 야간에
 * 혼자 보는 사람이 어느 목록을 봐야 하는지부터 헷갈린다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CheckCircle2, ClipboardCheck, Circle } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import { scheduleApi } from '@/services/api/schedules'

export default function Inspections({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const rows = useQuery({ queryKey: ['inspections'], queryFn: () => scheduleApi.inspections() })
  const done = useMutation({
    mutationFn: async (v: { id: number; day: string; on: boolean }) => {
      if (v.on) await scheduleApi.completeInspection(v.id, v.day)
      else await scheduleApi.reopenInspection(v.id, v.day)
    },
    onSuccess: () => {
      setError('')
      qc.invalidateQueries({ queryKey: ['inspections'] })
      qc.invalidateQueries({ queryKey: ['closing-check'] })
    },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '처리하지 못했습니다.'),
  })

  const list = rows.data ?? []
  const pending = list.filter((x) => !x.is_done).length
  if (compact && list.length === 0) return null

  return (
    <section className="card p-3 space-y-2 min-w-0" aria-label="오늘 점검">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="font-medium flex items-center gap-1.5">
          <ClipboardCheck size={15} /> 오늘 점검
        </h2>
        {list.length > 0 && (
          <span className={`text-sm ${pending ? 'text-state-check' : 'text-state-done'}`}>
            {pending ? `${pending}건 남음` : '모두 완료'}
          </span>
        )}
      </div>
      {rows.isLoading && <p className="text-sm text-ink-muted">불러오는 중…</p>}
      {rows.isError && (
        <div role="alert" className="text-sm text-state-urgent">
          점검 목록을 불러오지 못했습니다. <button className="btn btn-sm" onClick={() => rows.refetch()}>다시 시도</button>
        </div>
      )}
      {!rows.isLoading && list.length === 0 && (
        <p className="text-sm text-ink-muted">
          오늘 돌 점검이 없습니다. 정기 점검은 <Link className="text-brand hover:underline" to="/schedules">일정</Link> 에서
          종류를 ‘점검’으로, 반복을 ‘매일 · 매주 · 매월’로 등록하면 여기에 나타납니다.
        </p>
      )}
      <ul className="divide-y divide-surface-border/60">
        {list.map((x) => (
          <li key={`${x.schedule_id}-${x.occurrence_date}`} className="py-1.5 flex items-start gap-2">
            <button aria-label={`${x.title} ${x.is_done ? '완료 취소' : '완료 처리'}`}
                    className="mt-0.5 shrink-0" disabled={done.isPending}
                    onClick={() => done.mutate({ id: x.schedule_id, day: x.occurrence_date, on: !x.is_done })}>
              {x.is_done
                ? <CheckCircle2 size={17} className="text-state-done" />
                : <Circle size={17} className="text-ink-faint" />}
            </button>
            <div className="min-w-0 flex-1">
              <p className={`break-words ${x.is_done ? 'text-ink-muted line-through' : 'font-medium'}`}>{x.title}</p>
              <p className="text-xs text-ink-faint">
                {x.company && `${x.company} · `}
                {x.recurrence_text && `${x.recurrence_text} · `}
                담당 {x.owner_name ?? '근무자'}
                {x.is_done && x.done_by_name && ` · ${x.done_by_name} 완료`}
              </p>
            </div>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}
    </section>
  )
}
