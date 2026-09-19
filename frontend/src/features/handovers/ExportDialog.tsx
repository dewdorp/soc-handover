/**
 * 지금 화면의 조건 그대로 내보낸다(FR-F-07). 조건을 따로 고르는 화면이 아니다 —
 * 보고 있는 결과와 받은 파일이 다르면 그게 사고다.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, X } from 'lucide-react'
import { useEscape } from '@/hooks/useHotkeys'
import { ApiRequestError } from '@/services/api/client'
import { exportApi } from '@/services/api/imports'
import type { SearchRequest } from '@/types/handover'

interface Props {
  request: SearchRequest
  total: number
  onClose: () => void
}

export default function ExportDialog({ request, total, onClose }: Props) {
  useEscape(onClose)
  const { data: columns } = useQuery({ queryKey: ['export-columns'], queryFn: exportApi.columns })
  const [format, setFormat] = useState<'xlsx' | 'csv'>('xlsx')
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const chosen = picked ?? new Set((columns ?? []).filter((c) => c.default).map((c) => c.key))

  const run = useMutation({
    mutationFn: () => exportApi.create({
      ...request, page: 1, format,
      columns: (columns ?? []).filter((c) => chosen.has(c.key)).map((c) => c.key),
    }),
    onSuccess: (res) => { exportApi.download(res.download_token); onClose() },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '내보내지 못했습니다.'),
  })

  const toggle = (key: string) => {
    const next = new Set(chosen)
    next.has(key) ? next.delete(key) : next.add(key)
    setPicked(next)
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4"
         role="dialog" aria-modal="true" aria-labelledby="export-title">
      <div className="card w-[520px] max-w-full shadow-xl p-4 space-y-3">
        <div className="flex items-center">
          <h2 id="export-title" className="font-medium text-md flex-1">내보내기</h2>
          <button onClick={onClose} aria-label="닫기" className="text-ink-faint hover:text-ink"><X size={16} /></button>
        </div>

        <p>
          지금 화면의 조건 그대로 <b className="tabular-nums">{total.toLocaleString()}</b>건을 내보냅니다.
          <span className="text-ink-muted"> (페이지와 상관없이 조건에 맞는 전부)</span>
        </p>

        <fieldset className="flex gap-4">
          <legend className="text-ink-muted mb-1">형식</legend>
          {(['xlsx', 'csv'] as const).map((f) => (
            <label key={f} className="flex items-center gap-1.5 cursor-pointer">
              <input type="radio" name="format" checked={format === f} onChange={() => setFormat(f)} />
              {f === 'xlsx' ? 'Excel (.xlsx)' : 'CSV (.csv)'}
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend className="text-ink-muted mb-1">컬럼</legend>
          <div className="grid grid-cols-3 gap-x-3 gap-y-0.5">
            {(columns ?? []).map((c) => (
              <label key={c.key} className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" checked={chosen.has(c.key)} onChange={() => toggle(c.key)} />
                <span className="truncate">{c.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <p className="text-sm text-ink-faint">
          내보내기 기록(조건·건수)은 감사로그에 남습니다. 파일은 1시간 동안 본인만 내려받을 수 있습니다.
        </p>

        {error && (
          <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200
                                     rounded px-2 py-1">{error}</p>
        )}

        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onClose}>취소</button>
          <button className="btn btn-primary" disabled={run.isPending || chosen.size === 0 || total === 0}
                  onClick={() => run.mutate()}>
            <Download size={12} /> {run.isPending ? '만드는 중…' : '내려받기'}
          </button>
        </div>
      </div>
    </div>
  )
}
