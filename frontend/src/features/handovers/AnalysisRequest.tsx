/**
 * 분석 의뢰 — 의뢰 → 접수 → 회신.
 *
 * 인계와 모양이 다르다. 인계는 '다음 근무자에게 넘김'이고 의뢰는 '다른 조직에 맡기고
 * **답을 기다림**'이다. 상태 코드(진행중 · 완료)로는 "맡겼는데 아직 접수도 안 됐다"를
 * 표현할 수 없어서 따로 둔다.
 *
 * 되돌리기 단추는 없다. 잘못 눌렀으면 다시 의뢰한다 — 상태 이력이 지워지면 '언제 맡겼고
 * 언제 답이 왔는가'를 따질 근거가 사라진다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Clock, MessageSquareReply, Send } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import { requestApi, type AnalysisRequest as Req } from '@/services/api/participants'
import { referenceApi } from '@/services/api/reference'

const TONE: Record<string, string> = {
  NONE: 'text-ink-faint',
  REQUESTED: 'text-state-check',
  ACCEPTED: 'text-state-waiting',
  ANSWERED: 'text-state-done',
}

function when(value: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

export default function AnalysisRequest({ handoverId }: { handoverId: number }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'ask' | 'answer' | null>(null)
  const [note, setNote] = useState('')
  const [to, setTo] = useState<number[]>([])

  const { data } = useQuery({
    queryKey: ['request', handoverId], queryFn: () => requestApi.get(handoverId),
  })
  const users = useQuery({
    queryKey: ['user-lookup'], queryFn: () => referenceApi.userLookup(), staleTime: 60_000,
  })

  const done = () => {
    setError(null); setMode(null); setNote(''); setTo([])
    qc.invalidateQueries({ queryKey: ['request', handoverId] })
    qc.invalidateQueries({ queryKey: ['participants', handoverId] })
    qc.invalidateQueries({ queryKey: ['handover', handoverId] })
  }
  const fail = (e: unknown) => setError(e instanceof ApiRequestError ? e.message : '처리하지 못했습니다.')

  const ask = useMutation({ mutationFn: () => requestApi.ask(handoverId, to, note.trim()), onSuccess: done, onError: fail })
  const accept = useMutation({ mutationFn: () => requestApi.accept(handoverId), onSuccess: done, onError: fail })
  const answer = useMutation({ mutationFn: () => requestApi.answer(handoverId, note.trim()), onSuccess: done, onError: fail })

  const state = data?.state ?? 'NONE'
  const next = (data?.next_actions ?? []) as Req['next_actions']

  return (
    <section className="space-y-1.5" aria-label="분석 의뢰">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-ink-muted">분석 의뢰</h3>
        <span className={`font-medium ${TONE[state]}`}>{data?.state_label ?? '—'}</span>
        <span className="flex-1" />
        {next.includes('REQUESTED') && (
          <button className="btn btn-sm" onClick={() => { setMode('ask'); setNote('') }}>
            <Send size={11} /> {state === 'NONE' ? '의뢰하기' : '추가 의뢰'}
          </button>
        )}
        {next.includes('ACCEPTED') && (
          <button className="btn btn-sm" disabled={accept.isPending} onClick={() => accept.mutate()}>
            <CheckCircle2 size={11} /> 접수하기
          </button>
        )}
        {next.includes('ANSWERED') && (
          <button className="btn btn-sm btn-primary" onClick={() => { setMode('answer'); setNote('') }}>
            <MessageSquareReply size={11} /> 회신하기
          </button>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}

      {state !== 'NONE' && data && (
        <dl className="grid grid-cols-[72px_1fr] gap-x-2 gap-y-0.5 text-sm">
          <dt className="text-ink-muted">의뢰</dt>
          <dd className="tabular-nums">{when(data.requested_at)}</dd>
          {data.request_note && (
            <>
              <dt className="text-ink-muted">내용</dt>
              <dd className="whitespace-pre-wrap break-words">{data.request_note}</dd>
            </>
          )}
          <dt className="text-ink-muted">접수</dt>
          <dd className="tabular-nums">
            {data.accepted_at ? when(data.accepted_at)
              : <span className="text-state-check inline-flex items-center gap-1"><Clock size={11} /> 아직</span>}
          </dd>
          <dt className="text-ink-muted">회신</dt>
          <dd className="tabular-nums">
            {data.answered_at ? when(data.answered_at)
              : <span className="text-state-check inline-flex items-center gap-1"><Clock size={11} /> 아직</span>}
          </dd>
          {data.answer_note && (
            <>
              <dt className="text-ink-muted">회신 내용</dt>
              <dd className="whitespace-pre-wrap break-words">{data.answer_note}</dd>
            </>
          )}
        </dl>
      )}

      {mode === 'ask' && (
        <div className="rounded border border-surface-border p-2 space-y-1.5">
          <label className="block text-sm">
            누구에게 (필수 인수자로 걸립니다 — 접수를 추적할 사람)
            <select multiple className="input w-full h-24 mt-0.5" value={to.map(String)}
                    aria-label="의뢰받을 사람"
                    onChange={(e) => setTo(Array.from(e.target.selectedOptions, (o) => Number(o.value)))}>
              {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            무엇을 봐 달라는 것인지 *
            <textarea className="input w-full h-20 py-1 mt-0.5 resize-y" value={note} maxLength={5000}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="C2 통신 로그 분석 부탁드립니다. 대상 PC: 10.20.1.33" />
          </label>
          <div className="flex justify-end gap-1">
            <button className="btn btn-sm" onClick={() => setMode(null)}>취소</button>
            <button className="btn btn-sm btn-primary" disabled={!to.length || !note.trim() || ask.isPending}
                    onClick={() => ask.mutate()}>의뢰</button>
          </div>
        </div>
      )}

      {mode === 'answer' && (
        <div className="rounded border border-surface-border p-2 space-y-1.5">
          <label className="block text-sm">
            회신 내용 * <span className="text-ink-faint">(내용 없는 '회신함'은 증적이 아닙니다)</span>
            <textarea className="input w-full h-24 py-1 mt-0.5 resize-y" value={note} maxLength={20000}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="확인 결과와 조치 내용" />
          </label>
          <div className="flex justify-end gap-1">
            <button className="btn btn-sm" onClick={() => setMode(null)}>취소</button>
            <button className="btn btn-sm btn-primary" disabled={!note.trim() || answer.isPending}
                    onClick={() => answer.mutate()}>회신</button>
          </div>
        </div>
      )}
    </section>
  )
}
