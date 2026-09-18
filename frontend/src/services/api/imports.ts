/** Excel Import / Export API. */
import { api, downloadUrl, upload } from '@/services/api/client'
import type { Page } from '@/types/api'
import type { SearchRequest } from '@/types/handover'

export type JobStatus =
  | 'UPLOADED' | 'ANALYZED' | 'MAPPED' | 'STAGED' | 'VALIDATED' | 'DEDUPED'
  | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'ROLLED_BACK'

export interface SheetInfo {
  name: string
  header_row: number | null
  headers: string[]
  estimated_rows: number
  samples: Record<string, unknown>[]
  recognized: number
  year_hint: number | null
}

export interface ImportJob {
  id: number
  job_code: string
  file_name: string
  status: JobStatus
  phase: 'STAGE' | 'PREPARE' | 'COMMIT' | 'ROLLBACK' | null
  progress: number
  total_rows: number
  success_rows: number
  duplicate_rows: number
  error_rows: number
  skipped_rows: number
  sheet_summary: { sheets: SheetInfo[]; headers: string[]; size_bytes: number; warnings: string[] } | null
  column_mapping: Record<string, string | null> | null
  options: {
    sheets?: string[]; default_status?: string; default_year?: number | null
    value_map?: { company?: Record<string, unknown>; status?: Record<string, unknown> }
  } | null
  report: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  finished_at: string | null
}

export interface ImportReport {
  job_code: string
  status: JobStatus
  total?: number
  valid?: number
  warning?: number
  error?: number
  duplicate?: number
  duplicate_existing?: number
  duplicate_batch?: number
  imported?: number
  will_import?: number
  blank?: number
  rollback?: { removed: number; kept_modified: number }
}

export interface ImportRow {
  id: number
  sheet_name: string
  source_row: number
  raw: Record<string, unknown>
  normalized: Record<string, unknown> | null
  warnings: { code: string; message: string }[] | null
  dup_type: 'NONE' | 'BATCH' | 'EXISTING'
  dup_handover_id: number | null
  decision: 'PENDING' | 'IMPORT' | 'SKIP'
  status: 'STAGED' | 'VALID' | 'WARNING' | 'ERROR' | 'IMPORTED'
  handover_id: number | null
  will_import: boolean
}

export interface ImportError {
  id: number
  sheet_name: string | null
  source_row: number | null
  column_name: string | null
  error_code: string
  message: string
  raw_value: string | null
}

export interface ValueStat {
  value: string
  /** 표기만 다른 원문들. 한 줄로 묶어 한 번에 매핑한다('A보안' / 'a보안'). */
  variants: string[]
  count: number
  target: number | string | null
  target_label: string | null
  matched: boolean
}

export type RowKind = 'all' | 'error' | 'warning' | 'duplicate' | 'import' | 'skip' | 'imported'

const J = '/import/jobs'

export const importApi = {
  targets: () => api.get<{ value: string; label: string }[]>('/import/targets'),
  list: () => api.get<ImportJob[]>(J),
  get: (id: number) => api.get<ImportJob>(`${J}/${id}`),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return upload<ImportJob>(J, form)
  },
  mapping: (id: number, body: {
    sheets: string[]; column_mapping: Record<string, string | null>
    default_status: string; default_year: number | null
  }) => api.post<ImportJob>(`${J}/${id}/mapping`, body),
  stage: (id: number) => api.post<ImportJob>(`${J}/${id}/stage`),
  /** 원본을 다시 읽지 않고 검증·중복검사만 다시 돌린다 */
  prepare: (id: number) => api.post<ImportJob>(`${J}/${id}/validate`),
  values: (id: number, field: 'company' | 'status') =>
    api.get<ValueStat[]>(`${J}/${id}/values?field=${field}`),
  valueMap: (id: number, field: 'company' | 'status', mapping: Record<string, unknown>) =>
    api.post<ImportJob>(`${J}/${id}/value-map`, { field, mapping }),
  rows: (id: number, kind: RowKind, page: number, size = 50) =>
    api.get<Page<ImportRow>>(`${J}/${id}/rows?kind=${kind}&page=${page}&size=${size}`),
  errors: (id: number, page: number) =>
    api.get<Page<ImportError>>(`${J}/${id}/errors?page=${page}`),
  decisions: (id: number, rowIds: number[], decision: 'IMPORT' | 'SKIP' | 'PENDING') =>
    api.patch<{ changed: number }>(`${J}/${id}/decisions`, { row_ids: rowIds, decision }),
  commit: (id: number) => api.post<ImportJob>(`${J}/${id}/commit`),
  report: (id: number) => api.get<ImportReport>(`${J}/${id}/report`),
  rollback: (id: number) => api.post<ImportJob>(`${J}/${id}/rollback`),
  downloadErrors: (id: number) => downloadUrl(`${J}/${id}/errors.xlsx`),
}

export interface ExportColumn { key: string; label: string; default: boolean }

export const exportApi = {
  columns: () => api.get<ExportColumn[]>('/export/columns'),
  create: (body: SearchRequest & { columns?: string[]; format: 'xlsx' | 'csv' }) =>
    api.post<{ download_token: string; file_name: string; rows: number; expires_at: string }>(
      '/export/handovers', body),
  download: (token: string) => downloadUrl(`/export/download/${token}`),
}
