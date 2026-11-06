/** 장비 비밀번호: 본인 인증 후 허용된 현재 비밀번호를 단기간 함께 열람.
 * 평문은 컴포넌트 메모리에만 저장하고 계정 변경·숨김·만료 때 즉시 비운다.
 * 개인 범위는 기존 서버 권한을 그대로 적용한다.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { Copy, Eye, EyeOff, KeyRound, Lock, Plus, Search, Users } from 'lucide-react'
import CredentialDialog from '@/features/credentials/CredentialDialog'
import RevealDialog from '@/features/credentials/RevealDialog'
import { ApiRequestError } from '@/services/api/client'
import { credentialApi, type Credential, type CredentialScope } from '@/services/api/credentials'

const SCOPES: { key: CredentialScope | ''; label: string }[] = [
  { key: '', label: '전체' }, { key: 'SHARED', label: '공용' }, { key: 'PERSONAL', label: '개인' },
]
const friendlyError = (err: unknown) => err instanceof ApiRequestError ? err.message : '요청을 처리하지 못했습니다.'

export default function CredentialsPage() {
  const [q, setQ] = useState('')
  const [applied, setApplied] = useState('')
  const [scope, setScope] = useState<CredentialScope | ''>('')
  const [revealing, setRevealing] = useState<Credential | null>(null)
  const [editing, setEditing] = useState<Credential | null>(null)
  const [creating, setCreating] = useState(false)
  const [unlockPassword, setUnlockPassword] = useState('')
  const [vaultToken, setVaultToken] = useState<string | null>(null)
  const tokenRef = useRef<string | null>(null)
  const [expiresAt, setExpiresAt] = useState(0)
  const [absoluteAt, setAbsoluteAt] = useState(0)
  const [nowTime, setNowTime] = useState(Date.now())
  const [secrets, setSecrets] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [active, setActive] = useState(true)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['credentials', applied, scope],
    queryFn: () => credentialApi.list({ q: applied, scope }),
  })

  const clearLocal = () => {
    tokenRef.current = null
    setVaultToken(null)
    setSecrets({})
    setUnlockPassword('')
    setExpiresAt(0)
    setAbsoluteAt(0)
    setCopiedId(null)
  }

  const lockVault = () => {
    const token = tokenRef.current
    clearLocal()
    if (token) void credentialApi.lockVault(token).catch(() => {})
  }

  useEffect(() => {
    const timer = window.setInterval(() => setNowTime(Date.now()), 1000)
    const onHide = () => {
      if (document.hidden) { setActive(false); setSecrets({}) }
      else setActive(true)
    }
    document.addEventListener('visibilitychange', onHide)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onHide)
      const token = tokenRef.current
      tokenRef.current = null
      if (token) void credentialApi.lockVault(token).catch(() => {})
    }
  }, [])

  useEffect(() => {
    if (!vaultToken || nowTime < expiresAt) return
    const token = tokenRef.current
    clearLocal()
    if (token) void credentialApi.lockVault(token).catch(() => {})
    setMessage('안전을 위해 열람 시간이 끝나 자동으로 잠갔습니다.')
  }, [nowTime, expiresAt, vaultToken])

  useEffect(() => {
    if (!vaultToken || !data || !active || !expiresAt || Date.now() >= expiresAt) return
    let cancelled = false
    const token = vaultToken
    setSecrets({})
    const ids = data.map(x => x.id)
    if (!ids.length) return
    credentialApi.vaultSecrets(token, ids)
      .then(rows => {
        if (!cancelled && tokenRef.current === token && Date.now() < expiresAt) {
          setSecrets(Object.fromEntries(rows.map(x => [x.credential_id, x.secret])))
        }
      })
      .catch(err => {
        if (!cancelled) {
          setMessage(friendlyError(err))
          lockVault()
        }
      })
    return () => { cancelled = true }
  }, [data, vaultToken, active, expiresAt])

  const unlockVault = async () => {
    if (!unlockPassword || busy) return
    setBusy(true); setMessage(null)
    try {
      const session = await credentialApi.unlockVault(unlockPassword)
      tokenRef.current = session.token
      setVaultToken(session.token)
      const now = Date.now()
      setExpiresAt(now + session.expires_in_seconds*1000)
      setAbsoluteAt(now + session.remaining_absolute_seconds*1000)
      setUnlockPassword('')
      setMessage('현재 계정이 열람 가능한 비밀번호를 잠시 표시합니다.')
    } catch(err) { setMessage(friendlyError(err)); setSecrets({}) }
    finally { setBusy(false) }
  }
  const extend = async () => {
    const token = tokenRef.current
    if (!token || busy) return
    setBusy(true);setMessage(null)
    try {
      const x = await credentialApi.extendVault(token)
      const now = Date.now()
      setExpiresAt(now + x.expires_in_seconds*1000)
      setAbsoluteAt(now + x.remaining_absolute_seconds*1000)
      setMessage('열람 시간을 연장했습니다.')
    } catch(err) { setMessage(friendlyError(err)); lockVault() }
    finally { setBusy(false) }
  }
  const copy = async (id: number) => {
    const value = secrets[id]
    if (!value || !vaultToken) return
    try {
      await navigator.clipboard.writeText(value)
      setCopiedId(id)
    } catch { setMessage('자동 복사가 제한된 브라우저입니다. 값을 선택하여 복사해 주세요.') }
  }
  const remaining = Math.max(0, Math.ceil((expiresAt-nowTime)/1000))
  const hardRemaining = Math.max(0, Math.ceil((absoluteAt-nowTime)/1000))

  return (
    <div className="p-3 sm:p-4 space-y-3 min-h-0 flex flex-col">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
          <KeyRound size={17} className="box-content rounded-md bg-brand-soft p-1.5 text-brand" /> 비밀번호
        </h1>
        <button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={13} /> 등록</button>
      </div>
      <div className="card p-3 space-y-2">
        {vaultToken ? (
          <div className="flex flex-wrap items-center gap-2">
            <Eye size={16} className="text-state-check"/>
            <span className="font-medium">일시 열람 중 · 남은 시간 {Math.floor(remaining/60)}분 {String(remaining%60).padStart(2,'0')}초</span>
            <button className="btn btn-sm" disabled={busy || hardRemaining < 15} onClick={extend}>5분 연장</button>
            <button className="btn btn-sm" onClick={lockVault}><EyeOff size={13}/> 지금 잠그기</button>
            <span className="text-sm text-ink-muted">최대 유지 {Math.ceil(hardRemaining/60)}분 · 화면을 떠나면 잠시 가려집니다.</span>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Lock size={16} className="text-ink-muted"/>
            <span className="text-sm font-medium">전체 비밀번호 일시 보기</span>
            <input type="password" className="input w-44" aria-label="본인 계정 비밀번호"
                   placeholder="본인 계정 비밀번호" autoComplete="current-password" value={unlockPassword}
                   onChange={e=>setUnlockPassword(e.target.value)}
                   onKeyDown={e=>{if(e.key==='Enter')unlockVault()}}/>
            <button className="btn btn-primary btn-sm" disabled={busy||!unlockPassword} onClick={unlockVault}><Eye size={13}/> 인증하고 보기</button>
            <span className="text-sm text-ink-muted">기본 5분 · 서버에서 만료 검증 · 개인 항목은 본인 것만</span>
          </div>
        )}
        {message && <p role="status" className="text-sm text-ink-muted">{message}</p>}
        <p className="text-xs text-ink-faint">비밀번호는 암호화 보관하며, 금고 잠금 해제·일괄 열람·인증 실패·연장 기록은 감사로그에 남습니다. 사용 후 지금 잠그기를 누르십시오.</p>
      </div>
      <div className="card flex flex-wrap items-center gap-3 p-3">
        <div className="relative flex-1 min-w-[12rem] max-w-xl">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input className="input w-full h-8 pl-7" placeholder="장비명 · 계정 · 접속 방법으로 찾기"
                 value={q} onChange={e=>setQ(e.target.value)}
                 onKeyDown={e=>{if(e.key==='Enter')setApplied(q.trim())}}/>
        </div>
        <div className="flex gap-1">
          {SCOPES.map(s=> <button key={s.key||'all'} className={`btn btn-sm ${scope===s.key?'btn-primary':''}`} onClick={()=>setScope(s.key)}>{s.label}</button>)}
        </div>
      </div>
      <div className="card flex-1 overflow-auto">
        <table className="w-full text-base">
          <thead className="bg-surface-sunken text-ink-muted whitespace-nowrap">
            <tr>
              <th className="text-left font-semibold px-3 py-2">관계사</th>
              <th className="text-left font-semibold px-3 py-2">장비명</th>
              <th className="text-left font-semibold px-3 py-2">접속 방법</th>
              <th className="text-left font-semibold px-3 py-2">계정</th>
              <th className="text-left font-semibold px-3 py-2">범위</th>
              <th className="text-left font-semibold px-3 py-2">비밀번호</th>
              <th className="text-left font-semibold px-3 py-2">마지막 변경</th>
              <th className="px-3 py-1.5"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={8} className="py-8 text-center text-ink-faint">불러오는 중…</td></tr>}
            {isError && <tr><td colSpan={8} className="py-8 text-center text-state-urgent">조회 오류 <button className="btn btn-sm" onClick={()=>refetch()}>재시도</button></td></tr>}
            {!isLoading&&!isError&&(data??[]).length===0 && <tr><td colSpan={8} className="py-8 text-center text-ink-faint">등록된 항목이 없습니다.</td></tr>}
            {(data??[]).map(row=>(
              <tr key={row.id} className="border-t border-surface-border/60 hover:bg-surface-sunken">
                <td className="px-3 py-1.5">{row.company??'미지정'}</td>
                <td className="px-3 py-1.5"><button className="font-medium text-brand hover:underline text-left" onClick={()=>setEditing(row)}>{row.device_name}</button>
                  {row.note&&<div className="text-xs text-ink-faint truncate max-w-[200px]">{row.note}</div>}</td>
                <td className="px-3 py-1.5 text-ink-muted">{row.access_method??'-'}</td>
                <td className="px-3 py-1.5 font-mono">{row.username??'-'}</td>
                <td className="px-3 py-1.5">{row.scope==='SHARED'?<span className="chip"><Users size={11}/> 공용</span>:<span className="chip"><Lock size={11}/> 개인</span>}</td>
                <td className="px-3 py-1.5">
                  {vaultToken&&active&&secrets[row.id]!==undefined ? <div className="flex gap-1 items-center">
                    <input readOnly className="input w-36 font-mono" aria-label={`${row.device_name} 비밀번호`} value={secrets[row.id]}
                           onFocus={e=>e.currentTarget.select()}/>
                    <button className="btn btn-sm" aria-label={`${row.device_name} 복사`} onClick={()=>copy(row.id)}><Copy size={12}/>{copiedId===row.id?'복사됨':''}</button>
                  </div> : <span className="text-ink-faint">••••••••</span>}
                </td>
                <td className="px-3 py-1.5 text-ink-muted whitespace-nowrap">
                  {row.rotated_at?format(parseISO(row.rotated_at),'yyyy-MM-dd HH:mm'):'-'}
                </td>
                <td className="px-3 py-1.5 text-right">
                  {!vaultToken&&<button className="btn btn-sm" onClick={()=>setRevealing(row)}><Eye size={12}/> 개별 보기</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {revealing&&<RevealDialog credential={revealing} onClose={()=>setRevealing(null)}/>}
      {(creating||editing)&&<CredentialDialog credential={editing}
        onClose={()=>{setCreating(false);setEditing(null); if(vaultToken)lockVault()}}/>}
    </div>
  )
}
