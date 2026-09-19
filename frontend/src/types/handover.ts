/** 인수인계 · 검색 DSL 타입. 백엔드 스키마와 1:1 대응. */
import type { Company, HandoverStatus, Priority, UserBrief } from '@/types/api'

export type AckState = 'NONE' | 'PENDING' | 'ACKED' | 'REACK_REQUIRED'

export interface HandoverListItem {
  id: number
  company: Company | null
  title: string
  status: HandoverStatus | null
  priority: Priority | null
  registered_date: string
  work_date: string | null
  completed_at: string | null
  sender: UserBrief | null
  sender_name_raw: string | null
  assignee: UserBrief | null
  assignee_name_raw: string | null
  checker: UserBrief | null
  checker_name_raw: string | null
  is_important: boolean
  is_pinned: boolean
  is_recurring: boolean
  current_version_no: number
  /** 전체 집계. 필터의 1차 축소용이며 "내 확인상태"가 아니다. */
  ack_state_cache: AckState
  my_ack_state: AckState | null
  is_starred: boolean
  tags: string[]
  carry_count: number
  updated_at: string
  is_deleted: boolean
}

export interface Acknowledgement {
  user_id: number
  user: { id: number; display_name: string } | null
  state: AckState
  acked_version_no: number | null
  acked_at: string | null
  stale_since: string | null
  stale_reason: string[] | null
  note: string | null
}

export interface HandoverDetail extends HandoverListItem {
  task_count: number
  schedule_count: number
  content: string
  remark: string | null
  created_by: number | null
  updated_by: number | null
  created_at: string
  deleted_at: string | null
  deleted_by: number | null
  delete_reason: string | null
  source_file: string | null
  source_sheet: string | null
  source_row: number | null
  acknowledgements: Acknowledgement[]
}

export interface VersionSummary {
  version_no: number
  change_type: 'CREATE' | 'UPDATE' | 'RESTORE' | 'DELETE' | 'UNDELETE' | 'IMPORT'
  changed_fields: string[]
  change_reason: string | null
  restored_from_version: number | null
  changed_by: number | null
  changed_at: string
}

export interface VersionDetail extends VersionSummary {
  before_data: Record<string, unknown> | null
  after_data: Record<string, unknown>
  client_ip: string | null
  user_agent: string | null
}

export interface DiffOp {
  op: 'equal' | 'insert' | 'delete'
  text: string
}

export interface DiffField {
  field: string
  before: unknown
  after: unknown
  ops?: DiffOp[]
}

export interface VersionDiff {
  handover_id: number
  from_version: number
  to_version: number
  changed_fields: string[]
  fields: DiffField[]
}

export interface TimelineEvent {
  kind: 'VERSION' | 'ACK' | 'REACK_REQUIRED' | 'COMMENT'
  at: string
  actor_id: number | null
  title: string
  detail: Record<string, unknown>
}

/** 낙관적 잠금 충돌(409)의 detail. */
export interface VersionConflictDetail {
  current_version_no: number
  expected_version: number
  changed_since: string[]
  conflicting_fields: string[]
  current: Record<string, unknown>
}

// --------------------------------------------------------------------- 검색 DSL

export type FilterOp =
  | 'eq' | 'ne' | 'in' | 'not_in' | 'contains' | 'not_contains'
  | 'starts_with' | 'ends_with' | 'between' | 'gte' | 'lte'
  | 'is_null' | 'is_not_null' | 'any_of_tags'

export interface Filter {
  field: string
  op: FilterOp
  value?: unknown
}

export interface Sort {
  field: string
  dir: 'asc' | 'desc'
}

export interface SearchRequest {
  q?: string | null
  filters?: Filter[]
  sort?: Sort[]
  quick?: string[]
  page?: number
  size?: number
  include_deleted?: boolean
}

export interface FacetValue {
  value: unknown
  label: string
  count: number
}

export type FieldKind =
  | 'text' | 'enum' | 'int' | 'date' | 'datetime' | 'bool' | 'tags' | 'user_state'

export interface FieldInfo {
  name: string
  label: string
  kind: FieldKind
  ops: FilterOp[]
  sortable: boolean
  facetable: boolean
  facet_source: string | null
}

export interface SearchCapabilities {
  fields: FieldInfo[]
  quick_filters: { token: string; label: string }[]
  operators: FilterOp[]
  backend: string
  max_filters: number
  max_page_size: number
}

export interface SavedView {
  id: number
  name: string
  description: string | null
  scope: 'PERSONAL' | 'SHARED'
  owner_id: number | null
  target: string
  state: Record<string, unknown>
  is_default: boolean
  sort_order: number
  created_by: number | null
  updated_at: string
}
