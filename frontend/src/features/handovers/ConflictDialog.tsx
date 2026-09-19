/**
 * 버전 충돌 다이얼로그 (UI_STRUCTURE §4.2).
 *
 * 자동 덮어쓰기도, 자동 병합도 하지 않는다. 무엇이 어떻게 달라졌는지 보여주고
 * 사용자가 직접 결정하게 한다. "저장했는데 내 수정이 사라졌다"를 막는 마지막 지점이다.
 */
import { AlertTriangle } from 'lucide-react'
import { fieldLabel } from '@/features/handovers/VersionHistory'
import { useEscape } from '@/hooks/useHotkeys'
import type { VersionConflictDetail } from '@/types/handover'

interface Props {
  detail: VersionConflictDetail
  /** 내가 저장하려던 값 */
  mine: Record<string, unknown>
  onReload: () => void
  onCancel: () => void
}

export default function ConflictDialog({ detail, mine, onReload, onCancel }: Props) {
  useEscape(onCancel)
  const conflicting = detail.conflicting_fields ?? []
  const changedSince = detail.changed_since ?? []

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4"
         role="dialog" aria-modal="true" aria-labelledby="conflict-title">
      <div className="card w-[560px] max-w-full shadow-xl p-4 space-y-3">
        <div className="flex items-start gap-2">
          <AlertTriangle size={18} className="text-state-check shrink-0 mt-0.5" />
          <div>
            <h2 id="conflict-title" className="font-medium">
              다른 사용자가 이 인수인계를 수정했습니다.
            </h2>
            <p className="text-ink-muted">
              내 기준 v{detail.expected_version} · 현재 v{detail.current_version_no}
            </p>
          </div>
        </div>

        <div className="text-base space-y-1">
          <p>
            <span className="text-ink-muted">그동안 바뀐 필드: </span>
            {changedSince.length ? changedSince.map(fieldLabel).join(', ') : '(없음)'}
          </p>
          <p className={conflicting.length ? 'text-state-urgent font-medium' : ''}>
            <span className="text-ink-muted font-normal">내 변경과 겹치는 필드: </span>
            {conflicting.length ? conflicting.map(fieldLabel).join(', ') : '겹치지 않음'}
          </p>
        </div>

        {conflicting.length > 0 && (
          <div className="border border-surface-border rounded overflow-hidden">
            <table className="w-full text-base">
              <thead className="bg-surface-sunken text-ink-muted">
                <tr>
                  <th className="px-2 py-1 text-left font-medium w-24">필드</th>
                  <th className="px-2 py-1 text-left font-medium">현재 서버 값</th>
                  <th className="px-2 py-1 text-left font-medium">내가 쓰려던 값</th>
                </tr>
              </thead>
              <tbody>
                {conflicting.map((name) => (
                  <tr key={name} className="border-t border-surface-border align-top">
                    <td className="px-2 py-1 text-ink-muted">{fieldLabel(name)}</td>
                    <td className="px-2 py-1 break-words">{show(detail.current?.[name])}</td>
                    <td className="px-2 py-1 break-words font-medium">{show(mine[name])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-sm text-ink-muted">
          자동으로 합치지 않습니다. 최신 내용을 확인한 뒤 다시 저장하십시오.
        </p>

        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onCancel}>취소</button>
          <button className="btn btn-primary" onClick={onReload} autoFocus>
            최신 내용 불러오기
          </button>
        </div>
      </div>
    </div>
  )
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '(없음)'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(없음)'
  if (typeof value === 'boolean') return value ? '예' : '아니오'
  const text = String(value)
  return text.length > 200 ? `${text.slice(0, 200)}…` : text
}
