/**
 * 시스템 설정 (/settings) — 서버가 알려주는 입력 규칙(spec)대로 칸을 그리고, 저장 전 검사도 서버가 한다.
 * 모든 변경은 감사로그(설정 변경)에 남는다. 비밀 값은 가려서 보여주고 여기서 바꾸지 않는다.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import RowErrorBoundary from '@/components/RowErrorBoundary'
import { useCan } from '@/hooks/useAuth'
import { adminApi, type SystemSettingRow } from '@/services/api/admin'
import { ApiRequestError } from '@/services/api/client'

const CATEGORY_LABEL: Record<string, string> = {
  handover: '인수인계', shift: '교대 인계', attachment: '첨부', export: '내보내기', retention: '보존',
  import: 'Excel Import', roster: '근무표', audit: '감사로그', credential: '비밀번호',
}
/** 자주 바꾸는 것부터. 목록에 없는 분류는 뒤에 붙는다. */
const CATEGORY_ORDER = ['handover', 'shift', 'roster', 'credential', 'attachment', 'audit', 'export', 'import', 'retention']
const rank = (c: string) => { const i = CATEGORY_ORDER.indexOf(c); return i < 0 ? CATEGORY_ORDER.length : i }

export default function SettingsPage() {
  const can = useCan()
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ['settings'], queryFn: adminApi.settings, enabled: can('settings:manage') })
  if (!can('settings:manage')) return <p className="p-4 text-ink-muted">관리자만 볼 수 있는 화면입니다.</p>
  if (isLoading) return <p className="p-4 text-ink-faint">불러오는 중…</p>
  if (isError || !Array.isArray(data)) return <div role="alert" className="p-4 text-state-urgent">설정을 불러오지 못했습니다. <button className="btn btn-sm" onClick={() => refetch()}>다시 시도</button></div>
  const groups = [...new Set(data.map((r) => r.category))].sort((a, b) => rank(a) - rank(b))
  return (
    <div className="h-full overflow-auto">
      <div className="max-w-3xl p-3 space-y-3">
        <div>
          <h1 className="text-md font-medium">설정</h1>
          <p className="text-sm text-ink-muted">바꾼 값은 바로 적용되고 감사로그에 남습니다.</p>
        </div>
        {groups.map((g) => (
          <section key={g} className="card divide-y divide-surface-border/70">
            <h2 className="px-3 py-2 font-medium bg-surface-sunken/60">{CATEGORY_LABEL[g] ?? g}</h2>
            {data.filter((r) => r.category === g).map((r) => (
              <RowErrorBoundary key={r.key} label={r.spec?.label ?? r.key} raw={r.value}>
                <SettingRow row={r} />
              </RowErrorBoundary>
            ))}
          </section>
        ))}
      </div>
    </div>
  )
}

function SettingRow({ row }: { row: SystemSettingRow }) {
  const qc = useQueryClient()
  const [value, setValue] = useState<unknown>(row.value)
  // 되돌리기 · 저장 뒤 글상자(확장자 · 별칭)를 새 값으로 다시 그린다
  const [nonce, setNonce] = useState(0)
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)
  const save = useMutation({
    mutationFn: (v: unknown) => adminApi.updateSetting(row.key, v),
    onSuccess: (res) => {
      setValue(res.value); setNonce((n) => n + 1); setMessage({ text: '저장했습니다.', bad: false })
      qc.invalidateQueries({ queryKey: ['settings'] }); qc.invalidateQueries({ queryKey: ['features'] })
    },
    onError: (err) => {
      // 켜고 끄는 값은 실패하면 서버 값으로 되돌린다 — 화면만 바뀐 채 두면 켠 줄 안다.
      if (row.spec?.kind === 'bool') setValue(row.value)
      setMessage({ text: err instanceof ApiRequestError ? err.message : '저장하지 못했습니다.', bad: true })
    },
  })
  const spec = row.spec
  const dirty = JSON.stringify(value) !== JSON.stringify(row.value)

  return (
    <div className="px-3 py-2.5 space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium">{spec?.label ?? row.key}</span>
        <code className="text-xs text-ink-faint">{row.key}</code>
        <span className="flex-1" />
        <span className="text-xs text-ink-faint">{row.updated_at ? `${format(parseISO(row.updated_at), 'yyyy-MM-dd HH:mm')} 변경` : '기본값'}</span>
      </div>
      {row.description && <p className="text-sm text-ink-muted">{row.description}</p>}

      {row.is_secret || !spec ? (
        <pre className="bg-surface-sunken rounded p-2 text-xs whitespace-pre-wrap break-all">{row.is_secret ? '*** (비밀 값 — .env 에서 바꿉니다)' : JSON.stringify(row.value, null, 2)}</pre>
      ) : spec.kind === 'bool' ? (
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={Boolean(value)} disabled={save.isPending}
                 onChange={(e) => { setValue(e.target.checked); save.mutate(e.target.checked) }} />
          {value ? '켜짐' : '꺼짐'}
        </label>
      ) : spec.kind === 'int' ? (
        <div className="flex items-center gap-2">
          <input type="number" className="input w-36" min={spec.min} max={spec.max} value={String(value ?? '')}
                 onChange={(e) => setValue(e.target.value === '' ? '' : Number(e.target.value))} aria-label={spec.label} />
          <span className="text-sm text-ink-muted">{spec.unit} · {spec.min?.toLocaleString()} ~ {spec.max?.toLocaleString()}</span>
        </div>
      ) : spec.kind === 'date' ? (
        <input type="date" className="input w-44" value={typeof value === 'string' ? value : ''}
               onChange={(e) => setValue(e.target.value)} aria-label={spec.label} />
      ) : spec.kind === 'fields' ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {spec.choices?.map((c) => {
            const list = Array.isArray(value) ? value.map(String) : []
            return (
              <label key={c.value} className="inline-flex items-center gap-1 text-sm">
                <input type="checkbox" checked={list.includes(c.value)}
                       onChange={(e) => setValue(e.target.checked ? [...list, c.value] : list.filter((x) => x !== c.value))} />
                {c.label}
              </label>
            )
          })}
        </div>
      ) : spec.kind === 'ext_list' ? (
        <ExtEditor key={nonce} value={value} label={spec.label} onChange={setValue} />
       ) : spec.kind === 'aliases' ? (
        <AliasEditor key={nonce} value={value} onChange={setValue}
                     placeholder={row.key === 'import.status_aliases' ? 'DONE: 처리끝, 조치완료\nHOLD: 보류중' : 'content: 조치내역, 처리내용\nremark: 특이사항'} />
      ) : (
        <pre className="bg-surface-sunken p-2 text-xs whitespace-pre-wrap break-all">{JSON.stringify(value, null, 2)}</pre>
      )}

      {spec && spec.kind !== 'bool' && !row.is_secret && (
        <div className="flex items-center gap-2">
          <button className="btn btn-sm btn-primary" disabled={!dirty || save.isPending} onClick={() => { setMessage(null); save.mutate(value) }}>저장</button>
          {dirty && <button className="btn btn-sm" onClick={() => { setValue(row.value); setNonce((n) => n + 1); setMessage(null) }}>되돌리기</button>}
          {message?.bad && <button className="btn btn-sm" onClick={() => { setMessage(null); save.mutate(value) }} disabled={save.isPending}>재시도</button>}
        </div>
      )}
      {message && <p role={message.bad ? 'alert' : 'status'} className={`text-sm ${message.bad ? 'text-state-urgent' : 'text-state-done'}`}>{message.text}</p>}
    </div>
  )
}

/** 쉼표로 나눈 확장자 — 친 글자를 그대로 두고(쉼표 · 공백이 바로 지워지지 않게) 값만 목록으로 바꾼다. */
function ExtEditor({ value, label, onChange }: { value: unknown; label: string; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => (Array.isArray(value) ? value.map(String) : []).join(', '))
  return (
    <input className="input w-full font-mono" value={text} aria-label={label}
           onChange={(e) => {
             setText(e.target.value)
             onChange(e.target.value.split(/[,\s]+/).map((x) => x.trim().toLowerCase().replace(/^\./, '')).filter(Boolean))
           }} />
  )
}

/** '이름: 별칭, 별칭' 한 줄에 하나 — JSON 을 직접 고치지 않게. */
function AliasEditor({ value, onChange, placeholder }: { value: unknown; onChange: (v: unknown) => void; placeholder?: string }) {
  const toText = (v: unknown) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return ''
    return Object.entries(v as Record<string, unknown>)
      .map(([key, items]) => `${key}: ${(Array.isArray(items) ? items.map(String) : items == null ? [] : [String(items)]).join(', ')}`)
      .join('\n')
  }
  const [text, setText] = useState(() => toText(value))
  return (
    <textarea className="input w-full h-32 py-1 font-mono text-sm resize-y" value={text} aria-label="별칭" placeholder={placeholder}
              onChange={(e) => {
                setText(e.target.value)
                const obj: Record<string, string[]> = {}
                for (const line of e.target.value.split('\n')) {
                  const at = line.indexOf(':')
                  if (at > 0) obj[line.slice(0, at).trim()] = line.slice(at + 1).split(',').map((s) => s.trim()).filter(Boolean)
                }
                onChange(obj)
              }} />
  )
}
