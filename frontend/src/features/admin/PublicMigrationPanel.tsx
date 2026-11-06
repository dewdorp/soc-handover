/**
 * 과거 '그룹 미지정' 자료를 전체 공개로 바꾸는 화면.
 *
 * 왜 버튼 하나로 끝내지 않는가
 *   이 작업은 되돌릴 수는 있어도 **읽힌 것은 되돌릴 수 없다**. 누르는 순간
 *   로그인한 모든 사람 — 외주 · 협력사 계정을 포함해 — 이 과거 인계를 읽는다.
 *   과거 인계 본문에는 계정 · 장비 · 고객 정보가 적혀 있을 수 있다. 그래서
 *   건수와 목록을 먼저 보여 주고, 경고를 읽히고, 확인 문구를 직접 입력받고,
 *   백업을 받았는지 확인한 뒤에야 보낸다(§3).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Globe, RotateCcw } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import { groupsApi } from '@/services/api/groups'

export default function PublicMigrationPanel() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [backup, setBackup] = useState(false)
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)

  const preview = useQuery({
    queryKey: ['public-migration-preview'],
    queryFn: () => groupsApi.publicMigration.preview(50),
  })
  const batches = useQuery({
    queryKey: ['public-migration-batches'],
    queryFn: () => groupsApi.publicMigration.batches(),
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['public-migration-preview'] })
    qc.invalidateQueries({ queryKey: ['public-migration-batches'] })
    qc.invalidateQueries({ queryKey: ['groups'] })
    qc.invalidateQueries({ queryKey: ['groups-unclassified'] })
  }
  const fail = (err: unknown) => setMessage({
    text: err instanceof ApiRequestError ? err.message : '처리하지 못했습니다.', bad: true })

  const apply = useMutation({
    mutationFn: () => groupsApi.publicMigration.apply(confirm, backup),
    onSuccess: (r) => {
      setConfirm(''); setBackup(false); setOpen(false)
      setMessage({ text: `${r.converted}건을 전체 공개로 바꿨습니다. 아래 이력에서 되돌릴 수 있습니다.`, bad: false })
      refresh()
    },
    onError: fail,
  })
  const revert = useMutation({
    mutationFn: (batchId: string) => groupsApi.publicMigration.revert(batchId),
    onSuccess: (r) => {
      setMessage({
        text: `${r.restored}건을 되돌렸습니다.` +
          (r.skipped ? ` ${r.skipped}건은 그 뒤 범위를 직접 바꾼 자료라 그대로 두었습니다.` : ''),
        bad: false,
      })
      refresh()
    },
    onError: fail,
  })

  const data = preview.data
  const history = batches.data ?? []
  if (preview.isLoading) return null
  if (!data?.eligible && history.length === 0) return null

  return (
    <section className="card p-3 space-y-2">
      <h2 className="font-medium flex items-center gap-1.5">
        <Globe size={15} className="text-state-urgent" /> 과거 ‘그룹 미지정’ 자료 전체 공개 전환
      </h2>

      {data && data.eligible > 0 ? (
        <>
          <p className="text-sm">
            그룹을 지정하지 않은 채 쌓인 자료가 <strong>{data.eligible.toLocaleString()}건</strong> 있습니다.
            전환하면 그중 <strong>{data.visible_after.toLocaleString()}건</strong>을 로그인한 모든 사용자
            ({data.reader_count.toLocaleString()}명)가 읽게 됩니다.
            {data.deleted_included > 0 && ` (삭제된 ${data.deleted_included.toLocaleString()}건은 복구할 때를 대비해 함께 바꿉니다.)`}
          </p>
          <ul className="text-sm space-y-1 rounded bg-state-urgent-soft/30 p-2">
            {data.warnings.map((w) => (
              <li key={w} className="flex gap-1.5">
                <AlertTriangle size={14} className="shrink-0 mt-0.5 text-state-urgent" />
                <span>{w}</span>
              </li>
            ))}
          </ul>

          <details className="text-sm">
            <summary className="cursor-pointer">공개될 자료 미리 보기 ({data.items.length}건{data.truncated && ' · 일부'})</summary>
            <table className="w-full mt-2">
              <thead className="text-ink-muted">
                <tr><th className="text-left py-1">번호</th><th className="text-left">제목</th>
                    <th className="text-left">관계사</th><th className="text-left">작성자</th></tr>
              </thead>
              <tbody>
                {data.items.map((x) => (
                  <tr key={x.id} className="border-t border-surface-border/60">
                    <td className="py-1">{x.id}</td>
                    <td className="break-words">{x.is_important && <span className="text-state-urgent">[중요] </span>}{x.title}</td>
                    <td>{x.company ?? '-'}</td>
                    <td>{x.author ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.truncated && <p className="text-xs text-ink-faint mt-1">목록이 길어 일부만 보여 줍니다. 전체 건수는 위에 적힌 수입니다.</p>}
          </details>

          {!open ? (
            <button className="btn btn-sm" onClick={() => { setOpen(true); setMessage(null) }}>
              전환 준비
            </button>
          ) : (
            <div className="space-y-2 rounded border border-state-urgent/40 p-2">
              <label className="block text-sm">
                확인 문구를 그대로 입력하십시오: <code className="font-mono">{data.confirm_phrase}</code>
                <input className="input w-full mt-1" aria-label="확인 문구"
                       value={confirm} onChange={(e) => setConfirm(e.target.value)} />
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={backup} onChange={(e) => setBackup(e.target.checked)} />
                전환 전에 데이터베이스 백업을 받았습니다.
              </label>
              <div className="flex gap-2">
                <button className="btn btn-sm btn-primary"
                        disabled={apply.isPending || confirm.trim() !== data.confirm_phrase || !backup}
                        onClick={() => apply.mutate()}>
                  {data.eligible.toLocaleString()}건 전체 공개로 전환
                </button>
                <button className="btn btn-sm" onClick={() => { setOpen(false); setConfirm(''); setBackup(false) }}>취소</button>
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-ink-muted">전환할 ‘그룹 미지정’ 자료가 없습니다.</p>
      )}

      {history.length > 0 && (
        <div className="pt-2 border-t border-surface-border">
          <h3 className="text-sm font-medium mb-1">전환 이력</h3>
          <table className="w-full text-sm">
            <thead className="text-ink-muted">
              <tr><th className="text-left py-1">시각</th><th className="text-left">승인자</th>
                  <th className="text-right">건수</th><th className="text-right">되돌림</th><th /></tr>
            </thead>
            <tbody>
              {history.map((b) => (
                <tr key={b.batch_id} className="border-t border-surface-border/60">
                  <td className="py-1 whitespace-nowrap">{b.converted_at?.slice(0, 16).replace('T', ' ') ?? '-'}</td>
                  <td>{b.converted_by_name ?? '-'}</td>
                  <td className="text-right">{b.count.toLocaleString()}</td>
                  <td className="text-right">{b.reverted.toLocaleString()}</td>
                  <td className="text-right">
                    {b.revertable && (
                      <button className="btn btn-sm" disabled={revert.isPending}
                              onClick={() => { if (window.confirm('이 전환을 되돌리시겠습니까? 다시 그룹 제한으로 돌아갑니다.')) revert.mutate(b.batch_id) }}>
                        <RotateCcw size={12} /> 되돌리기
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {message && (
        <p role={message.bad ? 'alert' : 'status'}
           className={`text-sm ${message.bad ? 'text-state-urgent' : 'text-state-done'}`}>{message.text}</p>
      )}
    </section>
  )
}
