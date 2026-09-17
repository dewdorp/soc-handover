import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { authApi } from '@/services/api/auth'
import { ApiRequestError } from '@/services/api/client'
import { useMe } from '@/hooks/useAuth'

export default function ChangePasswordPage() {
  const { data: me } = useMe()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const navigate = useNavigate()
  const qc = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => authApi.changePassword(current, next),
    onSuccess: () => {
      qc.clear()
      navigate('/login', { replace: true })
    },
    onError: (err) => {
      if (err instanceof ApiRequestError) {
        const list = (err.detail.problems as string[] | undefined) ?? [err.message]
        setProblems(list)
      } else {
        setProblems(['비밀번호를 변경하지 못했습니다.'])
      }
    },
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setProblems([])
    if (next !== confirm) {
      setProblems(['새 비밀번호가 서로 일치하지 않습니다.'])
      return
    }
    mutation.mutate()
  }

  return (
    <div className="h-full grid place-items-center bg-surface-sunken">
      <form onSubmit={onSubmit} className="card w-[400px] p-6 space-y-4 shadow-sm">
        <div className="flex items-center gap-2">
          <KeyRound size={18} className="text-brand" />
          <h1 className="text-lg font-semibold">비밀번호 변경</h1>
        </div>

        {me?.must_change_password && (
          <p className="text-sm bg-amber-50 border border-amber-200 text-amber-800 rounded px-2 py-1.5">
            초기 비밀번호를 사용 중입니다. 변경해야 시스템을 사용할 수 있습니다.
          </p>
        )}

        <p className="text-sm text-ink-muted">
          12자 이상, 영문 대/소문자·숫자·특수문자 중 3종 이상, 계정명 미포함
        </p>

        {[
          { label: '현재 비밀번호', value: current, set: setCurrent, auto: 'current-password' },
          { label: '새 비밀번호', value: next, set: setNext, auto: 'new-password' },
          { label: '새 비밀번호 확인', value: confirm, set: setConfirm, auto: 'new-password' },
        ].map((f) => (
          <label key={f.label} className="block space-y-1">
            <span className="text-sm text-ink-muted">{f.label}</span>
            <input
              className="input w-full h-8"
              type="password"
              autoComplete={f.auto}
              value={f.value}
              onChange={(e) => f.set(e.target.value)}
              required
            />
          </label>
        ))}

        {problems.length > 0 && (
          <ul role="alert" className="text-sm text-state-urgent bg-red-50 border
                                      border-red-200 rounded px-2 py-1.5 space-y-0.5">
            {problems.map((p) => <li key={p}>· {p}</li>)}
          </ul>
        )}

        <button className="btn btn-primary w-full h-8" disabled={mutation.isPending}>
          변경하고 다시 로그인
        </button>
      </form>
    </div>
  )
}
