/**
 * 컬럼 헤더 필터 팝오버 3종 (UI_STRUCTURE §3.1).
 *   값 선택형 — 관계사·상태·중요도·담당자·태그·확인상태
 *   텍스트형 — 제목·내용·비고
 *   날짜형   — 등록일·수행일
 *
 * 값 목록의 건수는 서버가 **현재 적용된 다른 필터 기준**으로 준다. Excel 자동필터와
 * 같은 체감이 나오는 지점이라 클라이언트에서 세지 않는다.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import { handoverApi } from '@/services/api/handovers'
import type { FieldInfo, Filter, SearchRequest } from '@/types/handover'

interface Props {
  field: FieldInfo
  request: SearchRequest
  current: Filter[]
  onApply: (filters: Filter[]) => void
  onClose: () => void
}

const TEXT_OPS: { op: Filter['op']; label: string }[] = [
  { op: 'contains', label: '포함' },
  { op: 'not_contains', label: '포함하지 않음' },
  { op: 'eq', label: '정확히 일치' },
  { op: 'starts_with', label: '시작' },
  { op: 'ends_with', label: '끝' },
  { op: 'is_null', label: '비어있음' },
  { op: 'is_not_null', label: '비어있지 않음' },
]

const DATE_TOKENS = [
  ['TODAY', '오늘'], ['YESTERDAY', '어제'],
  ['THIS_WEEK', '이번주'], ['LAST_WEEK', '지난주'],
  ['THIS_MONTH', '이번달'], ['LAST_MONTH', '지난달'],
  ['LAST_7_DAYS', '최근7일'], ['LAST_30_DAYS', '최근30일'],
  ['THIS_YEAR', '올해'], ['LAST_YEAR', '작년'],
]

export default function ColumnFilter(props: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && props.onClose()
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) props.onClose()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [props])

  const kind = props.field.kind
  return (
    <div ref={ref}
         className="absolute z-30 top-full left-0 mt-1 w-[260px] card shadow-lg p-2 space-y-2
                    text-base font-normal text-ink cursor-default"
         role="dialog" aria-label={`${props.field.label} 필터`}>
      <div className="flex items-center justify-between">
        <span className="font-medium">{props.field.label}</span>
        <button className="text-ink-faint hover:text-ink" onClick={props.onClose}
                aria-label="닫기"><X size={14} /></button>
      </div>
      {kind === 'text' ? <TextFilter {...props} />
        : kind === 'date' || kind === 'datetime' ? <DateFilter {...props} />
          : <ValueFilter {...props} />}
    </div>
  )
}

function Footer({ onReset, onApply }: { onReset: () => void; onApply: () => void }) {
  return (
    <div className="flex justify-between pt-1 border-t border-surface-border">
      <button className="btn btn-sm" onClick={onReset}>초기화</button>
      <button className="btn btn-sm btn-primary" onClick={onApply}>적용</button>
    </div>
  )
}

// --------------------------------------------------------------------- 값 선택형

function ValueFilter({ field, request, current, onApply, onClose }: Props) {
  const [search, setSearch] = useState('')
  const isTags = field.kind === 'tags'

  const selectedInitial = useMemo(() => {
    const flt = current.find((f) => f.op === 'in' || f.op === 'any_of_tags')
    return new Set((flt?.value as unknown[] | undefined)?.map(String) ?? [])
  }, [current])
  const [selected, setSelected] = useState<Set<string>>(selectedInitial)

  // 값 목록은 현재 필터를 반영해야 하므로 서버에 묻는다(클라이언트 집계 금지).
  const { data, isLoading } = useQuery({
    queryKey: ['facet', field.name, request, search],
    queryFn: () => handoverApi.facets(field.name, request, search),
    staleTime: 10_000,
  })

  const rows = data ?? []
  const allChecked = rows.length > 0 && rows.every((r) => selected.has(String(r.value)))

  const toggle = (value: string) => {
    const next = new Set(selected)
    next.has(value) ? next.delete(value) : next.add(value)
    setSelected(next)
  }

  const apply = () => {
    if (selected.size === 0) {
      onApply([])
    } else {
      const values = [...selected].map((v) =>
        field.kind === 'enum' && /^\d+$/.test(v) && field.facet_source !== 'status'
          ? Number(v) : v)
      onApply([{ field: field.name, op: isTags ? 'any_of_tags' : 'in', value: values }])
    }
    onClose()
  }

  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Search size={12} className="absolute left-2 top-2 text-ink-faint" />
        <input className="input w-full pl-6 text-sm" placeholder="검색…"
               value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
      </div>

      <label className="flex items-center gap-1.5 px-1 py-0.5 cursor-pointer hover:bg-surface-sunken">
        <input type="checkbox" checked={allChecked}
               onChange={() => setSelected(allChecked ? new Set()
                 : new Set(rows.map((r) => String(r.value))))} />
        <span className="text-ink-muted">전체 ({rows.reduce((a, r) => a + r.count, 0)})</span>
      </label>

      <div className="max-h-[220px] overflow-auto border-y border-surface-border py-0.5">
        {isLoading && <div className="px-1 py-2 text-ink-faint">불러오는 중…</div>}
        {!isLoading && rows.length === 0 && (
          <div className="px-1 py-2 text-ink-faint">해당하는 값이 없습니다.</div>
        )}
        {rows.map((row) => {
          const key = String(row.value)
          return (
            <label key={key}
                   className="flex items-center gap-1.5 px-1 py-0.5 cursor-pointer
                              hover:bg-surface-sunken">
              <input type="checkbox" checked={selected.has(key)} onChange={() => toggle(key)} />
              <span className="flex-1 truncate">{row.label}</span>
              <span className="text-ink-faint tabular-nums">{row.count.toLocaleString()}</span>
            </label>
          )
        })}
      </div>

      <Footer onReset={() => setSelected(new Set())} onApply={apply} />
    </div>
  )
}

// --------------------------------------------------------------------- 텍스트형

function TextFilter({ field, current, onApply, onClose }: Props) {
  const existing = current[0]
  const [op, setOp] = useState<Filter['op']>(existing?.op ?? 'contains')
  const [value, setValue] = useState(String(existing?.value ?? ''))

  const needsValue = op !== 'is_null' && op !== 'is_not_null'
  const allowed = TEXT_OPS.filter((t) => field.ops.includes(t.op))

  const apply = () => {
    if (needsValue && !value.trim()) onApply([])
    else onApply([{ field: field.name, op, ...(needsValue ? { value } : {}) }])
    onClose()
  }

  return (
    <div className="space-y-1.5">
      <select className="input w-full text-sm" value={op}
              onChange={(e) => setOp(e.target.value as Filter['op'])}>
        {allowed.map((t) => <option key={t.op} value={t.op}>{t.label}</option>)}
      </select>
      {needsValue && (
        <input className="input w-full" value={value} autoFocus
               placeholder="검색어" onChange={(e) => setValue(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && apply()} />
      )}
      <Footer onReset={() => { setValue(''); setOp('contains') }} onApply={apply} />
    </div>
  )
}

// --------------------------------------------------------------------- 날짜형

function DateFilter({ field, current, onApply, onClose }: Props) {
  const existing = current.find((f) => f.op === 'between')
  const initialToken = typeof existing?.value === 'string' ? existing.value : ''
  const initialRange = Array.isArray(existing?.value)
    ? (existing!.value as string[]) : ['', '']

  const [token, setToken] = useState(initialToken)
  const [from, setFrom] = useState(initialRange[0] ?? '')
  const [to, setTo] = useState(initialRange[1] ?? '')

  const apply = () => {
    if (token) onApply([{ field: field.name, op: 'between', value: token }])
    else if (from && to) onApply([{ field: field.name, op: 'between', value: [from, to] }])
    else if (from) onApply([{ field: field.name, op: 'gte', value: from }])
    else if (to) onApply([{ field: field.name, op: 'lte', value: to }])
    else onApply([])
    onClose()
  }

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
        {DATE_TOKENS.map(([value, label]) => (
          <label key={value} className="flex items-center gap-1.5 cursor-pointer">
            <input type="radio" name={`date-${field.name}`} checked={token === value}
                   onChange={() => { setToken(value); setFrom(''); setTo('') }} />
            <span>{label}</span>
          </label>
        ))}
        <label className="flex items-center gap-1.5 cursor-pointer col-span-2">
          <input type="radio" name={`date-${field.name}`} checked={!token}
                 onChange={() => setToken('')} />
          <span>직접 선택</span>
        </label>
      </div>
      <div className="flex items-center gap-1">
        <input type="date" className="input flex-1 text-sm" value={from}
               onChange={(e) => { setFrom(e.target.value); setToken('') }} />
        <span className="text-ink-faint">~</span>
        <input type="date" className="input flex-1 text-sm" value={to}
               onChange={(e) => { setTo(e.target.value); setToken('') }} />
      </div>
      <Footer onReset={() => { setToken(''); setFrom(''); setTo('') }} onApply={apply} />
    </div>
  )
}
