/**
 * 변경이력 탭 (UI_STRUCTURE §4.1).
 *
 * 복원은 되돌리기가 아니라 **새 버전 생성**이다. 그래서 "v3으로 복원" 뒤에도 v4·v5가
 * 그대로 남는다. 화면도 그 사실을 숨기지 않는다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { handoverApi } from '@/services/api/handovers'
import { ApiRequestError } from '@/services/api/client'
import type { DiffField, VersionSummary } from '@/types/handover'

const FIELD_LABELS: Record<string, string> = {
  company_id: '관계사', title: '제목', content: '내용', remark: '비고',
  status_code: '상태', priority_code: '중요도', registered_date: '등록일',
  work_date: '수행일', completed_at: '완료시각', sender_id: '전달자',
  assignee_id: '담당자', checker_id: '확인자', is_important: '중요',
  is_pinned: '상단고정', is_recurring: '반복', tags: '태그', is_deleted: '삭제됨',
  sender_name_raw: '전달자(원본)', assignee_name_raw: '담당자(원본)',
  checker_name_raw: '확인자(원본)', import_job_id: 'Import 작업', source_file: '원본 파일',
}

const CHANGE_LABELS: Record<string, string> = {
  CREATE: '최초등록', UPDATE: '수정', RESTORE: '복원',
  DELETE: '삭제', UNDELETE: '복구', IMPORT: 'Excel 가져오기',
}

export function fieldLabel(name: string): string {
  return FIELD_LABELS[name] ?? name
}

interface Props {
  handoverId: number
  currentVersion: number
  canEdit: boolean
}

export default function VersionHistory({ handoverId, currentVersion, canEdit }: Props) {
  const qc = useQueryClient()
  const [compare, setCompare] = useState<[number, number] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { data: versions } = useQuery({
    queryKey: ['versions', handoverId],
    queryFn: () => handoverApi.versions(handoverId),
  })

  const { data: diff } = useQuery({
    queryKey: ['diff', handoverId, compare],
    queryFn: () => handoverApi.diff(handoverId, compare![0], compare![1]),
    enabled: compare !== null,
  })

  const restore = useMutation({
    mutationFn: ({ no, reason }: { no: number; reason: string }) =>
      handoverApi.restore(handoverId, no, currentVersion, reason),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['handover', handoverId] })
      qc.invalidateQueries({ queryKey: ['versions', handoverId] })
      qc.invalidateQueries({ queryKey: ['handovers'] })
    },
    onError: (err) => setError(err instanceof ApiRequestError
      ? err.message : '복원하지 못했습니다.'),
  })

  // window.prompt 는 앱을 품은 창(데스크톱 앱 안의 브라우저)에서 그냥 취소되는 경우가 있어 앱 안에서 묻는다.
  const [restoring, setRestoring] = useState<number | null>(null)

  const rows = versions ?? []

  return (
    <div className="space-y-2">
      {error && (
        <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200
                                   rounded px-2 py-1">{error}</p>
      )}

      <ul className="divide-y divide-surface-border border border-surface-border rounded">
        {rows.map((v, i) => (
          <VersionRow key={v.version_no} version={v}
                      previous={rows[i + 1]?.version_no}
                      isCurrent={v.version_no === currentVersion}
                      canEdit={canEdit}
                      onCompare={(from, to) => setCompare([from, to])}
                      onRestore={setRestoring} />
        ))}
        {rows.length === 0 && (
          <li className="px-2 py-3 text-ink-faint">이력을 불러오는 중…</li>
        )}
      </ul>

      {restoring != null && (
        <ConfirmDialog title={`v${restoring} 내용으로 되돌립니다`} confirmLabel="복원" busy={restore.isPending}
                       input={{ label: '복원 사유', required: true, placeholder: '예: 잘못 수정해서 되돌림' }}
                       onCancel={() => setRestoring(null)}
                       onConfirm={(reason) => { restore.mutate({ no: restoring, reason }); setRestoring(null) }}>
          <p>지금 내용을 지우는 것이 아니라, 그 버전의 내용으로 <b>새 버전</b>을 만듭니다.</p>
        </ConfirmDialog>
      )}

      {diff && (
        <div className="card p-2 space-y-1.5">
          <h4 className="font-medium">v{diff.from_version} → v{diff.to_version} 비교</h4>
          {diff.fields.length === 0 && (
            <p className="text-ink-faint">두 버전의 내용이 같습니다.</p>
          )}
          {diff.fields.map((f) => <DiffRow key={f.field} field={f} />)}
        </div>
      )}
    </div>
  )
}

function VersionRow({ version, previous, isCurrent, canEdit, onCompare, onRestore }: {
  version: VersionSummary; previous?: number; isCurrent: boolean; canEdit: boolean
  onCompare: (from: number, to: number) => void; onRestore: (no: number) => void
}) {
  // 최초등록은 모든 필드가 '변경'이라 나열해봐야 정보가 없다. 무엇이 바뀌었는지가 의미 있는
  // 것은 수정·복원부터다.
  const changed = version.change_type === 'CREATE'
    ? '' : version.changed_fields.map(fieldLabel).join(', ')
  return (
    <li className="flex items-center gap-2 px-2 py-1">
      <span className={`tabular-nums font-medium ${isCurrent ? 'text-brand' : ''}`}>
        v{version.version_no}
      </span>
      <span className="text-ink-faint tabular-nums">{time(version.changed_at)}</span>
      <span className="flex-1 truncate" title={version.change_reason ?? undefined}>
        <span className="text-ink-muted">{CHANGE_LABELS[version.change_type] ?? version.change_type}</span>
        {changed && <span className="ml-1">· {changed}</span>}
        {version.restored_from_version != null && (
          <span className="ml-1 text-ink-faint">(v{version.restored_from_version} 에서)</span>
        )}
      </span>
      {previous != null && (
        <button className="btn btn-sm" onClick={() => onCompare(previous, version.version_no)}>
          비교
        </button>
      )}
      {canEdit && !isCurrent && (
        <button className="btn btn-sm" onClick={() => onRestore(version.version_no)}
                title="이 버전 내용으로 새 버전을 만듭니다">
          <RotateCcw size={11} /> 복원
        </button>
      )}
    </li>
  )
}

function DiffRow({ field }: { field: DiffField }) {
  return (
    <div className="grid grid-cols-[80px_1fr] gap-2 items-start border-t
                    border-surface-border/60 pt-1">
      <span className="text-ink-muted">{fieldLabel(field.field)}</span>
      {field.ops ? (
        <p className="whitespace-pre-wrap break-words leading-relaxed">
          {field.ops.map((op, i) => (
            <span key={i}
                  className={op.op === 'insert' ? 'bg-green-100 text-green-900'
                    : op.op === 'delete' ? 'bg-red-100 text-red-900 line-through' : ''}>
              {op.text}
            </span>
          ))}
        </p>
      ) : (
        <p className="break-words">
          <span className="line-through text-ink-faint">{render(field.before)}</span>
          <span className="mx-1">→</span>
          <span className="font-medium">{render(field.after)}</span>
        </p>
      )}
    </div>
  )
}

function render(value: unknown): string {
  if (value === null || value === undefined || value === '') return '(없음)'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(없음)'
  if (typeof value === 'boolean') return value ? '예' : '아니오'
  return String(value)
}

function time(iso: string): string {
  const at = new Date(iso)
  return `${String(at.getMonth() + 1).padStart(2, '0')}/${String(at.getDate()).padStart(2, '0')} `
    + at.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
}
