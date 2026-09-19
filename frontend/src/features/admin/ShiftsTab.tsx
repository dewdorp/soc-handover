/**
 * 교대 시간 (ASSUMPTIONS B-01) — 운영 중인 교대를 한 번에 바꾼다(PUT /shifts).
 * 서버가 '하루 24시간을 빈틈 · 겹침 없이 덮는지' 검사한다. 저장 전에 막대로 미리 보여준다.
 * 목록에서 뺀 교대는 지우지 않고 비활성화된다(과거 인계가 그 교대를 가리킨다).
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { adminApi, type ShiftInput } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

const minutes = (t: string) => { const [h, m] = t.split(':').map(Number); return h * 60 + (m || 0) }
const BAR = ['bg-state-open', 'bg-state-progress', 'bg-state-check', 'bg-state-done']

/** 하루(0~1440분)를 교대마다 칠한 조각. 자정을 넘는 교대는 두 조각. */
function spans(rows: ShiftInput[]) {
  const out: { i: number; from: number; to: number }[] = []
  rows.forEach((r, i) => {
    if (!r.start_time || !r.end_time) return
    const s = minutes(r.start_time), e = minutes(r.end_time)
    if (e > s) out.push({ i, from: s, to: e })
    else { out.push({ i, from: s, to: 1440 }); if (e > 0) out.push({ i, from: 0, to: e }) }
  })
  return out
}

export default function ShiftsTab() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['admin-shifts'], queryFn: adminApi.shifts })
  const [rows, setRows] = useState<ShiftInput[]>([])
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)
  useEffect(() => {
    if (data) setRows(data.filter((s) => s.is_active).map((s) => ({ code: s.code, name: s.name,
      start_time: s.start_time.slice(0, 5), end_time: s.end_time.slice(0, 5), sort_order: s.sort_order })))
  }, [data])
  const save = useMutation({
    mutationFn: () => adminApi.replaceShifts(rows.map((r, i) => ({ ...r, code: r.code.trim().toUpperCase(), sort_order: (i + 1) * 10 }))),
    onSuccess: () => {
      setMessage({ text: '저장했습니다. 지금 교대 · Cockpit 이 새 시간으로 계산됩니다.', bad: false })
      for (const k of ['admin-shifts', 'cockpit', 'shifts']) qc.invalidateQueries({ queryKey: [k] })
    },
    onError: (err) => setMessage({ text: err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.', bad: true }),
  })
  const pieces = useMemo(() => spans(rows), [rows])
  const set = (i: number, k: keyof ShiftInput, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))

  return (
    <section className="card p-3 space-y-3 max-w-3xl">
      <h2 className="font-medium">교대 시간</h2>
      <p className="text-xs text-ink-muted">끝이 시작보다 이르면 자정을 넘는 교대입니다(예: 18:00 ~ 09:00). 교대들이 하루 24시간을 빈틈 · 겹침 없이 덮어야 저장됩니다.</p>
      <table className="w-full text-base">
        <thead className="text-sm text-ink-muted"><tr><th className="text-left font-medium">코드</th><th className="text-left font-medium">이름</th><th className="text-left font-medium">시작</th><th className="text-left font-medium">끝</th><th /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-surface-border/60">
              <td className="py-1 flex items-center gap-1.5"><span className={`w-2.5 h-2.5 rounded-sm ${BAR[i % BAR.length]}`} aria-hidden />
                <input className="input h-7 w-24 font-mono uppercase" value={r.code} aria-label="교대 코드" onChange={(e) => set(i, 'code', e.target.value)} /></td>
              <td><input className="input h-7 w-24" value={r.name} aria-label="교대 이름" onChange={(e) => set(i, 'name', e.target.value)} /></td>
              <td><input className="input h-7" type="time" value={r.start_time} aria-label="시작" onChange={(e) => set(i, 'start_time', e.target.value)} /></td>
              <td><input className="input h-7" type="time" value={r.end_time} aria-label="끝" onChange={(e) => set(i, 'end_time', e.target.value)} /></td>
              <td className="text-right"><button className="text-ink-faint hover:text-state-urgent" aria-label={`${r.name} 빼기`}
                                                 onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><X size={14} /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn btn-sm" onClick={() => setRows((rs) => [...rs, { code: '', name: '', start_time: '', end_time: '' }])}><Plus size={12} /> 교대 추가</button>

      <div aria-label="하루 24시간 미리보기">
        <div className="relative h-5 rounded bg-surface-sunken border border-surface-border overflow-hidden">
          {pieces.map((p, k) => (
            <div key={k} className={`absolute inset-y-0 ${BAR[p.i % BAR.length]} opacity-80 border-x-2 border-surface`}
                 style={{ left: `${(p.from / 1440) * 100}%`, width: `${((p.to - p.from) / 1440) * 100}%` }}
                 title={`${rows[p.i].name || rows[p.i].code} ${rows[p.i].start_time}~${rows[p.i].end_time}`} />
          ))}
        </div>
        <div className="flex justify-between text-xs text-ink-faint tabular-nums mt-0.5">
          {['00', '06', '12', '18', '24'].map((h) => <span key={h}>{h}:00</span>)}
        </div>
      </div>

      {message && <p role={message.bad ? 'alert' : 'status'} className={`text-sm ${message.bad ? 'text-state-urgent' : 'text-state-done'}`}>{message.text}</p>}
      <div className="flex gap-2">
        <button className="btn btn-primary" disabled={save.isPending || !rows.length} onClick={() => { setMessage(null); save.mutate() }}>저장</button>
        <button className="btn" onClick={() => data && setRows(data.filter((s) => s.is_active).map((s) => ({ code: s.code, name: s.name,
          start_time: s.start_time.slice(0, 5), end_time: s.end_time.slice(0, 5) })))}>되돌리기</button>
      </div>
      {data?.some((s) => !s.is_active) && (
        <p className="text-xs text-ink-faint">쓰지 않는 교대: {data.filter((s) => !s.is_active).map((s) => `${s.name}(${s.code})`).join(', ')} — 과거 기록 참조용으로 남아 있습니다. 같은 코드로 다시 추가하면 되살아납니다.</p>
      )}
    </section>
  )
}
