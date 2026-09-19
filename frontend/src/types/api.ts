/** 백엔드 스키마와 1:1 대응 타입. */

export interface ApiError {
  error: string
  message: string
  detail?: Record<string, unknown>
  request_id?: string
}

export interface Page<T> {
  items: T[]
  page: number
  size: number
  total: number
  total_all?: number | null
  has_next: boolean
  cursor?: string | null
}

export interface Me {
  id: number
  username: string
  display_name: string
  email: string | null
  role_code: 'ADMIN' | 'MANAGER' | 'ANALYST'
  team: string | null
  must_change_password: boolean
  last_login_at: string | null
  permissions: string[]
  pending_ack_count: number
  unread_notification_count: number
}

export interface Features {
  attachment: { allowed_ext: string[]; max_size_mb: number }
  ack: { reack_fields: string[] }
  export: { max_rows: number }
  page: { default_size: number; max_size: number }
  database: string
  database_warning: string | null
}

export interface Company {
  id: number
  code: string | null
  name: string
  short_name: string | null
  color: string | null
  is_active: boolean
  sort_order: number
}

export type StatusCategory = 'OPEN' | 'WAITING' | 'CLOSED'

export interface HandoverStatus {
  code: string
  name: string
  category: StatusCategory
  color: string | null
  icon: string | null
  sort_order: number
  is_active: boolean
  is_system: boolean
}

export interface Priority {
  code: 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW'
  name: string
  level: number
  color: string | null
  icon: string | null
  is_active: boolean
}

export interface Shift {
  id: number
  code: string
  name: string
  start_time: string
  end_time: string
  crosses_midnight: boolean
  sort_order: number
  is_active: boolean
}

export interface UserBrief {
  id: number
  username: string
  display_name: string
  role_code: string
  team: string | null
}
