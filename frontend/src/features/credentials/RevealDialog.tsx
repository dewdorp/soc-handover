/**
 * 비밀번호 열어 보기.
 *
 * 열 때마다 **본인 계정 비밀번호**를 다시 받는다 — 자리를 비운 사이 남이 열어 보는 것을 막는다.
 * 연 기록은 한 건씩 감사에 남고, 화면에서는 1분 뒤 저절로 닫힌다(모니터에 띄워 둔 채 자리를 뜨지 않게).
 */
import { useEffect, useRef, useState } from 'react'
import { Copy, Eye, KeyRound } from 'lucide-react'
import { ApiRequestError } from '@/services/api/client'
import { credentialApi, type Credential, type RevealResult } from '@/services/api/credentials'

const AUTO_CLOSE_SEC = 300
const MAX_CLOSE_SEC = 900

interface Props {
  credential: Credential
  /** 옛 비밀번호를 볼 때의 이력 번호(없으면 지금 값) */
  versionNo?: number
  onClose: () => void
}

export default function RevealDialog({ credential, versionNo, onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const latestClose = useRef(onClose)
  latestClose.current = onClose
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<RevealResult | null>(null)
  const [left, setLeft] = useState(AUTO_CLOSE_SEC)
  const expiresAt = useRef(0)
  const hardDeadline = useRef(0)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()          // 뒤에 열린 창까지 함께 닫히지 않게 먼저 받는다
      latestClose.current()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  useEffect(() => {
    if (!result) return
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.ceil((expiresAt.current - Date.now()) / 1000))
      setLeft(remaining)
      if (!remaining) latestClose.current()
    }, 1000)
    return () => window.clearInterval(timer)
  }, [result])

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(versionNo == null
        ? await credentialApi.reveal(credential.id, password)
        : await credentialApi.revealVersion(credential.id, versionNo, password))
      const at = Date.now()
      expiresAt.current = at + AUTO_CLOSE_SEC * 1000
      hardDeadline.current = at + MAX_CLOSE_SEC * 1000
      setLeft(AUTO_CLOSE_SEC)
      setPassword('')
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : '열지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const copy = () => {
    if (!result) return
    // 사내망을 http 로 쓰면 브라우저가 클립보드를 막는다 — 그때는 직접 고르게 안내한다
    navigator.clipboard?.writeText(result.secret)
      .then(() => setCopied(true))
      .catch(() => setError('이 브라우저에서는 자동 복사가 막혀 있습니다. 값을 직접 선택해 복사하십시오.'))
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" role="dialog"
         aria-modal="true" aria-labelledby="reveal-title" onClick={onClose}>
      <div className="card w-[440px] max-w-full shadow-xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-2">
          <KeyRound size={18} className="shrink-0 mt-0.5 text-state-check" />
          <div className="min-w-0">
            <h2 id="reveal-title" className="font-medium break-all">
              {credential.device_name}
              {versionNo != null && <span className="text-ink-muted"> · 이전 값 v{versionNo}</span>}
            </h2>
            <p className="text-ink-muted">
              {credential.company ?? '관계사 미지정'}
              {credential.username && ` · 계정 ${credential.username}`}
            </p>
          </div>
        </div>

        {!result ? (
          <>
            <label className="block space-y-0.5">
              <span className="text-ink-muted">본인 계정 비밀번호</span>
              <input ref={inputRef} type="password" className="input w-full" value={password}
                     autoComplete="current-password"
                     onChange={(e) => setPassword(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter' && password) submit() }} />
            </label>
            <p className="text-sm text-ink-faint">
              여는 기록은 누가 · 언제 · 어느 장비인지 감사로그에 남습니다.
            </p>
          </>
        ) : (
          <div className="space-y-1">
            <span className="text-ink-muted">비밀번호</span>
            <div className="flex gap-1">
              <input readOnly value={result.secret} aria-label="비밀번호 값"
                     className="input w-full font-mono select-all"
                     onFocus={(e) => e.currentTarget.select()} />
              <button className="btn shrink-0" onClick={copy}>
                <Copy size={13} /> {copied ? '복사됨' : '복사'}
              </button>
            </div>
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm text-ink-faint tabular-nums">{Math.floor(left / 60)}분 {String(left % 60).padStart(2, '0')}초 뒤 잠깁니다.</p>
              <button className="btn btn-sm" disabled={Date.now() >= hardDeadline.current - 1000}
                onClick={() => {
                  expiresAt.current = Math.min(hardDeadline.current, Math.max(Date.now(), expiresAt.current) + 5 * 60 * 1000)
                  setLeft(Math.max(0, Math.ceil((expiresAt.current - Date.now()) / 1000)))
                }}>5분 연장</button>
            </div>
          </div>
        )}

        {error && <p role="alert" className="text-sm text-state-urgent">{error}</p>}

        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onClose}>닫기</button>
          {!result && (
            <button className="btn btn-primary" disabled={busy || !password} onClick={submit}>
              <Eye size={13} /> 보기
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
