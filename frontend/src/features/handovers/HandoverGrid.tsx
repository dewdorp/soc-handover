/**
 * 인수인계 Data Grid (UI_STRUCTURE §3).
 *
 * 게시판이 아니라 Excel 에 가까운 밀도를 목표로 한다. 기본 Compact.
 * 중요도·상태·확인상태는 **색상만으로 뜻을 전달하지 않는다**(NFR-10). 아이콘+텍스트 병행.
 *
 * 필터/정렬/페이징은 전부 서버가 한다. 이 컴포넌트는 한 페이지만 그린다.
 */
import { useState } from 'react'
import { ArrowDown, ArrowUp, Filter as FilterIcon, Pin, Star } from 'lucide-react'
import ColumnFilter from '@/features/handovers/ColumnFilter'
import type { Density } from '@/hooks/useGridState'
import type {
  FieldInfo, Filter, HandoverListItem, SearchRequest, Sort,
} from '@/types/handover'

export interface ColumnDef {
  key: string
  label: string
  /** 필터·정렬에 쓰는 서버 필드명(없으면 필터 불가) */
  field?: string
  width: string
  align?: 'left' | 'center' | 'right'
  pinned?: boolean
}

export const COLUMNS: ColumnDef[] = [
  { key: 'star', label: '★', width: '32px', align: 'center', pinned: true },
  { key: 'company', label: '관계사', field: 'company_id', width: '110px', pinned: true },
  { key: 'registered_date', label: '등록일', field: 'registered_date', width: '86px' },
  { key: 'work_date', label: '수행일', field: 'work_date', width: '86px' },
  { key: 'status', label: '상태', field: 'status_code', width: '92px' },
  { key: 'priority', label: '중요도', field: 'priority_code', width: '80px' },
  { key: 'title', label: '제목', field: 'title', width: 'auto' },
  { key: 'sender', label: '전달자', field: 'sender_id', width: '90px' },
  { key: 'assignee', label: '담당자', field: 'assignee_id', width: '90px' },
  { key: 'ack', label: '확인', field: 'my_ack_state', width: '92px' },
  { key: 'tags', label: '태그', field: 'tags', width: '130px' },
  { key: 'updated_at', label: '최근수정', field: 'updated_at', width: '96px' },
]

const ROW_HEIGHT: Record<Density, string> = {
  compact: 'h-row-compact', normal: 'h-row-normal', comfortable: 'h-row-comfortable',
}

const PRIORITY_MARK: Record<string, { icon: string; className: string }> = {
  URGENT: { icon: '⛔', className: 'text-state-urgent font-medium' },
  HIGH: { icon: '▲', className: 'text-state-high' },
  NORMAL: { icon: '·', className: 'text-state-normal' },
  LOW: { icon: '▽', className: 'text-state-low' },
}

const STATUS_MARK: Record<string, string> = {
  OPEN: '◐', WAITING: '❚❚', CLOSED: '✔',
}

interface Props {
  rows: HandoverListItem[]
  fields: Map<string, FieldInfo>
  state: { sort: Sort[]; filters: Filter[]; density: Density; hidden: string[] }
  request: SearchRequest
  selectedId: number | null
  /** j/k 로 고른 행(상세는 아직 안 연 상태) */
  cursorId?: number | null
  isLoading: boolean
  onSelect: (id: number) => void
  onToggleStar: (row: HandoverListItem) => void
  onSort: (field: string, additive: boolean) => void
  onSetFilter: (field: string, filters: Filter[]) => void
}

export default function HandoverGrid(props: Props) {
  const [openFilter, setOpenFilter] = useState<string | null>(null)
  const columns = COLUMNS.filter((c) => !props.state.hidden.includes(c.key))

  return (
    <div className="flex-1 min-h-0 overflow-auto border-t border-surface-border">
      <table className="w-full border-collapse text-base">
        <thead className="sticky top-0 z-20 bg-surface-sunken">
          <tr>
            {columns.map((col) => (
              <HeaderCell key={col.key} col={col} {...props}
                          left={pinnedLeft(columns, col.key)}
                          open={openFilter === col.key}
                          onOpen={(v) => setOpenFilter(v ? col.key : null)} />
            ))}
          </tr>
        </thead>
        <tbody>
          {props.isLoading && (
            <tr><td colSpan={columns.length}
                    className="py-6 text-center text-ink-faint">불러오는 중…</td></tr>
          )}
          {!props.isLoading && props.rows.length === 0 && (
            <tr><td colSpan={columns.length} className="py-8 text-center text-ink-faint">
              조건에 맞는 인수인계가 없습니다.
            </td></tr>
          )}
          {props.rows.map((row) => (
            <Row key={row.id} row={row} columns={columns}
                 density={props.state.density}
                 selected={row.id === props.selectedId} cursor={row.id === props.cursorId}
                 onSelect={props.onSelect} onToggleStar={props.onToggleStar} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 좌측 고정 컬럼의 left 오프셋. 앞선 고정 컬럼들의 폭 합. */
function pinnedLeft(columns: ColumnDef[], key: string): number | undefined {
  let offset = 0
  for (const col of columns) {
    if (!col.pinned) return undefined
    if (col.key === key) return offset
    offset += parseInt(col.width, 10) || 0
  }
  return undefined
}

function HeaderCell({ col, state, request, fields, onSort, onSetFilter, open, onOpen, left }:
Props & {
  col: ColumnDef; open: boolean; onOpen: (v: boolean) => void; left?: number
}) {
  const field = col.field ? fields.get(col.field) : undefined
  const sortIndex = state.sort.findIndex((s) => s.field === col.field)
  const sort = sortIndex >= 0 ? state.sort[sortIndex] : null
  const active = state.filters.some((f) => f.field === col.field)
  const canFilter = Boolean(field && field.name !== 'is_starred')

  return (
    <th style={{ width: col.width, left: col.pinned ? left : undefined }}
        className={`relative px-1.5 py-1 font-medium text-ink-muted text-left border-b
                    border-surface-border select-none whitespace-nowrap
                    ${col.pinned ? 'sticky z-10 bg-surface-sunken' : ''}`}>
      <div className="flex items-center gap-0.5">
        <button
          className={`flex-1 text-left truncate ${field?.sortable ? 'hover:text-ink' : 'cursor-default'}`}
          onClick={(e) => field?.sortable && col.field && onSort(col.field, e.shiftKey)}
          title={field?.sortable ? '클릭 정렬 · Shift+클릭 다중 정렬' : undefined}>
          {col.label}
        </button>
        {sort && (
          <span className="flex items-center text-brand" aria-label={`정렬 ${sort.dir}`}>
            {sort.dir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />}
            {state.sort.length > 1 && <sup className="text-xs">{sortIndex + 1}</sup>}
          </span>
        )}
        {canFilter && (
          <button onClick={() => onOpen(!open)}
                  className={active ? 'text-brand' : 'text-ink-faint hover:text-ink'}
                  aria-label={`${col.label} 필터`} aria-expanded={open}>
            <FilterIcon size={11} fill={active ? 'currentColor' : 'none'} />
          </button>
        )}
      </div>
      {open && field && (
        <ColumnFilter field={field} request={request}
                      current={state.filters.filter((f) => f.field === field.name)}
                      onApply={(filters) => onSetFilter(field.name, filters)}
                      onClose={() => onOpen(false)} />
      )}
    </th>
  )
}

function Row({ row, columns, density, selected, cursor, onSelect, onToggleStar }: {
  row: HandoverListItem; columns: ColumnDef[]; density: Density; selected: boolean; cursor: boolean
  onSelect: (id: number) => void; onToggleStar: (row: HandoverListItem) => void
}) {
  return (
    <tr onClick={() => onSelect(row.id)} data-row-id={row.id} aria-current={cursor || selected || undefined}
        className={`${ROW_HEIGHT[density]} cursor-pointer border-b border-surface-border/70
                    ${selected ? 'bg-brand-soft' : 'hover:bg-surface-sunken'}
                    ${cursor && !selected ? 'outline outline-2 -outline-offset-2 outline-brand/60' : ''}
                    ${row.is_deleted ? 'opacity-50 line-through' : ''}`}>
      {columns.map((col) => (
        <td key={col.key}
            className={`px-1.5 truncate ${col.align === 'center' ? 'text-center' : ''}
                        ${col.pinned ? `sticky z-[1] ${selected ? 'bg-brand-soft' : 'bg-surface'}` : ''}`}
            style={{ width: col.width, left: col.pinned ? pinnedLeft(columns, col.key) : undefined }}>
          <Cell col={col} row={row} onToggleStar={onToggleStar} />
        </td>
      ))}
    </tr>
  )
}

function Cell({ col, row, onToggleStar }: {
  col: ColumnDef; row: HandoverListItem; onToggleStar: (row: HandoverListItem) => void
}) {
  switch (col.key) {
    case 'star':
      return (
        <button onClick={(e) => { e.stopPropagation(); onToggleStar(row) }}
                aria-label={row.is_starred ? '즐겨찾기 해제' : '즐겨찾기'}
                className={row.is_starred ? 'text-amber-500' : 'text-ink-faint/50 hover:text-amber-500'}>
          <Star size={12} fill={row.is_starred ? 'currentColor' : 'none'} />
        </button>
      )
    case 'company':
      return <span className="truncate">{row.company?.short_name ?? row.company?.name ?? '-'}</span>
    case 'registered_date':
      return <span className="tabular-nums">{shortDate(row.registered_date)}</span>
    case 'work_date':
      return <span className="tabular-nums">{shortDate(row.work_date)}</span>
    case 'status':
      return row.status ? (
        <span className="inline-flex items-center gap-1">
          <span aria-hidden>{STATUS_MARK[row.status.category] ?? '·'}</span>
          <span className="truncate">{row.status.name}</span>
        </span>
      ) : <>-</>
    case 'priority': {
      const mark = PRIORITY_MARK[row.priority?.code ?? 'NORMAL'] ?? PRIORITY_MARK.NORMAL
      return (
        <span className={`inline-flex items-center gap-1 ${mark.className}`}>
          <span aria-hidden>{mark.icon}</span>{row.priority?.name ?? '-'}
        </span>
      )
    }
    case 'title':
      return (
        <span className="flex items-center gap-1 min-w-0">
          {row.is_pinned && <Pin size={11} className="text-brand shrink-0" aria-label="상단고정" />}
          {row.carry_count > 1 && (
            <span className="chip h-4 px-1 text-xs shrink-0 text-state-check"
                  title={`${row.carry_count}교대째 이어서 인계 중`}>↻{row.carry_count}</span>
          )}
          <span className="truncate">{row.title}</span>
        </span>
      )
    case 'sender':
      return <>{row.sender?.display_name ?? row.sender_name_raw ?? '-'}</>
    case 'assignee':
      return <>{row.assignee?.display_name ?? row.assignee_name_raw ?? '-'}</>
    case 'ack':
      return <AckCell row={row} />
    case 'tags':
      return (
        <span className="flex gap-0.5 overflow-hidden">
          {row.tags.slice(0, 2).map((t) => (
            <span key={t} className="chip h-4 px-1 text-xs shrink-0">#{t}</span>
          ))}
          {row.tags.length > 2 && <span className="text-ink-faint">+{row.tags.length - 2}</span>}
        </span>
      )
    case 'updated_at':
      return <span className="tabular-nums text-ink-muted">{timeOrDate(row.updated_at)}</span>
    default:
      return null
  }
}

/** 확인 셀은 "내 확인상태" 기준이다. 전체 집계(ack_state_cache)와 섞으면 화면이 거짓말한다. */
function AckCell({ row }: { row: HandoverListItem }) {
  const mine = row.my_ack_state
  if (mine === 'ACKED') {
    return <span className="text-state-done">✔ v{row.current_version_no}</span>
  }
  if (mine === 'REACK_REQUIRED') {
    return <span className="text-state-check font-medium" title="확인 이후 내용이 변경되었습니다">
      ⚠ 재확인
    </span>
  }
  if (mine === 'PENDING') return <span className="text-state-wait">○ 대기</span>
  return <span className="text-ink-faint">-</span>
}

function shortDate(value: string | null): string {
  if (!value) return '-'
  return value.slice(5).replace('-', '/')
}

function timeOrDate(iso: string): string {
  const at = new Date(iso)
  const today = new Date()
  const sameDay = at.toDateString() === today.toDateString()
  return sameDay
    ? at.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
    : `${at.getMonth() + 1}/${at.getDate()}`
}
