import { FormEvent, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { useLogin, useMe } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const login = useLogin()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: string } }
  const { data: me, isLoading } = useMe()

  if (!isLoading && me) return <Navigate to="/" replace />

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    login.mutate(
      { username, password },
      {
        onSuccess: (user) => {
          navigate(user.must_change_password ? '/change-password' : (location.state?.from ?? '/'),
            { replace: true })
        },
        onError: (err) => {
          setError(err instanceof ApiRequestError
            ? err.message
            : '로그인 중 오류가 발생했습니다.')
        },
      },
    )
  }

  return (
    <div className="h-full grid place-items-center bg-surface-sunken">
      <form onSubmit={onSubmit} className="card w-[360px] p-6 space-y-4 shadow-sm">
        <div className="flex items-center gap-2">
          <ShieldCheck size={20} className="text-brand" />
          <div>
            <h1 className="text-lg font-semibold leading-tight">SOC 인수인계</h1>
            <p className="text-sm text-ink-faint">교대근무 업무 연속성 플랫폼</p>
          </div>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-ink-muted">계정</span>
          <input
            className="input w-full h-8"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-ink-muted">비밀번호</span>
          <input
            className="input w-full h-8"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && (
          <div role="alert" className="text-sm text-state-urgent bg-red-50 border
                                       border-red-200 rounded px-2 py-1.5">
            {error}
          </div>
        )}

        <button className="btn btn-primary w-full h-8" disabled={login.isPending}>
          {login.isPending ? '확인 중…' : '로그인'}
        </button>
      </form>
    </div>
  )
}
