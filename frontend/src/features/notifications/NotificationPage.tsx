/** 알림 (FR-I-06). 누르면 읽음 처리하고 해당 화면으로 이동한다. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { CheckCheck } from 'lucide-react'
import { notificationApi, type AppNotification } from '@/services/api/shift'

const TYPE_LABEL: Record<string, string> = {
  HANDOVER_TRANSFER: '인계 받음', HANDOVER_REACK: '재확인 필요', HANDOVER_ASSIGNED: '담당 지정',
  TASK_ASSIGNED: '할일 배정', TASK_COMMENT: '할일 댓글', SCHEDULE_ASSIGNED: '일정 배정',
  IMPORTANT_HANDOVER: '중요 인수인계', TASK_DUE_SOON: '마감 임박', TASK_OVERDUE: '할일 지연',
}

export default function NotificationPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: () => notificationApi.list(false) })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['notifications'] })
    qc.invalidateQueries({ queryKey: ['unread-count'] })
    qc.invalidateQueries({ queryKey: ['me'] })
  }
  const readAll = useMutation({ mutationFn: notificationApi.readAll, onSuccess: refresh })

  const open = async (n: AppNotification) => {
    if (!n.is_read) {
      await notificationApi.read(n.id).catch(() => undefined)
      refresh()
    }
    if (n.link_type === 'HANDOVER' && n.link_id) navigate(`/handovers?id=${n.link_id}`)
    else if (n.link_type === 'SHIFT' && n.link_id) navigate(`/shift/history?session=${n.link_id}`)
    else if (n.link_type === 'TASK' && n.link_id) navigate(`/tasks?id=${n.link_id}`)
    else if (n.link_type === 'SCHEDULE' && n.link_id) navigate(`/schedules?id=${n.link_id}`)
  }

  const unread = (data ?? []).filter((n) => !n.is_read).length

  return (
    <div className="p-4 max-w-[860px] space-y-2">
      <div className="flex items-center gap-2">
        <h1 className="text-md font-medium">알림</h1>
        <span className="text-ink-muted">안 읽음 {unread}건</span>
        <span className="flex-1" />
        <button className="btn btn-sm" disabled={!unread || readAll.isPending} onClick={() => readAll.mutate()}>
          <CheckCheck size={12} /> 모두 읽음
        </button>
      </div>
      <ul className="card divide-y divide-surface-border">
        {(data ?? []).length === 0 && <li className="px-3 py-6 text-center text-ink-faint">알림이 없습니다.</li>}
        {(data ?? []).map((n) => (
          <li key={n.id}>
            <button onClick={() => open(n)}
                    className={`w-full text-left px-3 py-2 hover:bg-surface-sunken ${n.is_read ? 'text-ink-muted' : ''}`}>
              <div className="flex items-center gap-2">
                {!n.is_read && <span className="w-2 h-2 rounded-full bg-brand shrink-0" aria-label="안 읽음" />}
                <span className="chip h-5 shrink-0">{TYPE_LABEL[n.type] ?? n.type}</span>
                <span className={`truncate ${n.is_read ? '' : 'font-medium'}`}>{n.title}</span>
                <span className="flex-1" />
                <span className="text-xs text-ink-faint tabular-nums shrink-0">
                  {new Date(n.created_at).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}
                </span>
              </div>
              {n.body && <p className="text-sm text-ink-muted mt-0.5 truncate">{n.body}</p>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
