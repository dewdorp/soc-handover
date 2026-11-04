/** 교대 인수인계 · 알림 API. */
import { api } from '@/services/api/client'
import type { HandoverListItem, SearchRequest } from '@/types/handover'

export interface ShiftWindow {
  shift_id: number | null
  code: string
  name: string
  shift_date: string
  start_at: string
  end_at: string
}

export interface CockpitArea {
  label: string
  total: number
  /** 건수를 상한(9,999)까지만 센 경우 — 화면에는 '9,999+' 로 */
  capped: boolean
  /** 지금 보고 있는 영역만 채워진다(나머지는 숫자만) */
  items: HandoverListItem[]
  request: SearchRequest
}

export interface Cockpit {
  window: ShiftWindow
  next_window: ShiftWindow
  /** 목록이 채워진 영역 */
  area: string
  areas: Record<string, CockpitArea>
  basket_handover_ids: number[]
}

export interface SessionItem {
  item_id: number
  handover_id: number
  title: string
  company: string | null
  status: string | null
  status_category: string | null
  priority: string | null
  priority_code: string | null
  is_deleted: boolean
  current_version_no: number | null
  version_no_at_transfer: number | null
  changed_since_transfer: boolean
  item_note: string | null
  display_order: number
  is_carry_forward: boolean
  carry_depth: number
  /** 인수자 전원 기준 — 한 명이라도 확인하지 않았으면 확인된 것이 아니다. */
  ack_state: 'PENDING' | 'ACKED' | 'REACK_REQUIRED' | null
  acked_version_no: number | null
  acked_at: string | null
  stale_reason: string[] | null
  ack_total: number
  ack_done: number
  acks: AckByUser[]
}

export interface AckByUser {
  user_id: number
  user: string | null
  state: 'PENDING' | 'ACKED' | 'REACK_REQUIRED' | null
  acked_version_no: number | null
  acked_at: string | null
  stale_reason: string[] | null
}

export interface ShiftSession {
  id: number
  status: 'DRAFT' | 'SENT' | 'CLOSED'
  shift_date: string
  shift_id: number | null
  to_shift_id: number | null
  from_user_id: number
  from_user: string | null
  to_user_ids: number[]
  to_users: string[]
  sent_at: string | null
  closed_at: string | null
  summary_note: string | null
  item_count: number
  acked_count: number
  items: SessionItem[]
}

export interface Basket extends ShiftSession {
  auto_added: number
  carry_candidates: number
}

export interface InboxItem {
  handover_id: number
  title: string
  company: string | null
  status: string | null
  priority_code: string | null
  current_version_no: number
  state: 'PENDING' | 'REACK_REQUIRED'
  acked_version_no: number | null
  stale_reason: string[] | null
  stale_since: string | null
  session_id: number | null
  sent_at: string | null
  from_user: string | null
  /** 같은 인계를 나 말고 또 받은 사람 */
  also_to: string[]
  summary_note: string | null
  version_no_at_transfer: number | null
  item_note: string | null
  carry_depth: number | null
}

export interface AckItem {
  handover_id: number
  expected_version: number | null
}

/** 그 사이에 내용이 바뀌어 확인을 보류한 건 */
export interface StaleAck {
  handover_id: number
  title: string | null
  shown_version_no: number | null
  current_version_no: number
  changed_fields: string[]
}

export interface BulkAckResult {
  acknowledged: number[]
  stale: StaleAck[]
  skipped: number[]
}

export interface AppNotification {
  id: number
  type: string
  title: string
  body: string | null
  link_type: 'HANDOVER' | 'SHIFT' | 'TASK' | 'SCHEDULE' | null
  link_id: number | null
  is_read: boolean
  created_at: string
}

const P = '/shift-handovers'

export const shiftApi = {
  cockpit: (area?: string) => api.get<Cockpit>(`${P}/cockpit${area ? `?area=${encodeURIComponent(area)}` : ''}`),
  basket: () => api.get<Basket>(`${P}/basket`),
  addItems: (handoverIds: number[], note?: string) =>
    api.post<{ added: number[]; skipped: number[] }>(`${P}/basket/items`,
      { handover_ids: handoverIds, item_note: note ?? null }),
  removeItem: (itemId: number) => api.delete<void>(`${P}/basket/items/${itemId}`),
  noteItem: (itemId: number, note: string | null) =>
    api.patch<SessionItem>(`${P}/basket/items/${itemId}`, { item_note: note }),
  updateBasket: (body: { to_user_ids?: number[]; summary_note?: string | null; order?: number[] }) =>
    api.patch<Basket>(`${P}/basket`, body),
  send: (body: { to_user_ids: number[]; summary_note?: string | null }) =>
    api.post<ShiftSession>(`${P}/basket/send`, body),
  inbox: () => api.get<InboxItem[]>(`${P}/inbox`),
  history: (direction: 'all' | 'sent' | 'received' | 'team') =>
    api.get<ShiftSession[]>(`${P}?direction=${direction}`),
  session: (id: number) => api.get<ShiftSession>(`${P}/${id}`),
  close: (id: number) => api.post<ShiftSession>(`${P}/${id}/close`),
  /** 건별로 '화면이 보여 준 버전'을 함께 보낸다 — 읽지 않은 버전이 확인 처리되지 않게 */
  bulkAck: (items: AckItem[]) =>
    api.post<BulkAckResult>('/acknowledgements/bulk', { items }),
}

export const notificationApi = {
  list: (unread = false) => api.get<AppNotification[]>(`/notifications?unread=${unread}`),
  unreadCount: () => api.get<{ unread: number }>('/notifications/unread-count'),
  read: (id: number) => api.post<void>(`/notifications/${id}/read`),
  readAll: () => api.post<{ read: number }>('/notifications/read-all'),
}
