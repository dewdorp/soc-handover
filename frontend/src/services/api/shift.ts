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
  items: HandoverListItem[]
  request: SearchRequest
}

export interface Cockpit {
  window: ShiftWindow
  next_window: ShiftWindow
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
  ack_state: 'PENDING' | 'ACKED' | 'REACK_REQUIRED' | null
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
  to_user_id: number | null
  to_user: string | null
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
  summary_note: string | null
  version_no_at_transfer: number | null
  item_note: string | null
  carry_depth: number | null
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
  cockpit: () => api.get<Cockpit>(`${P}/cockpit`),
  basket: () => api.get<Basket>(`${P}/basket`),
  addItems: (handoverIds: number[], note?: string) =>
    api.post<{ added: number[]; skipped: number[] }>(`${P}/basket/items`,
      { handover_ids: handoverIds, item_note: note ?? null }),
  removeItem: (itemId: number) => api.delete<void>(`${P}/basket/items/${itemId}`),
  noteItem: (itemId: number, note: string | null) =>
    api.patch<SessionItem>(`${P}/basket/items/${itemId}`, { item_note: note }),
  updateBasket: (body: { to_user_id?: number | null; summary_note?: string | null; order?: number[] }) =>
    api.patch<Basket>(`${P}/basket`, body),
  send: (body: { to_user_id: number; summary_note?: string | null }) =>
    api.post<ShiftSession>(`${P}/basket/send`, body),
  inbox: () => api.get<InboxItem[]>(`${P}/inbox`),
  history: (direction: 'all' | 'sent' | 'received' | 'team') =>
    api.get<ShiftSession[]>(`${P}?direction=${direction}`),
  session: (id: number) => api.get<ShiftSession>(`${P}/${id}`),
  close: (id: number) => api.post<ShiftSession>(`${P}/${id}/close`),
  bulkAck: (handoverIds: number[]) =>
    api.post<{ acknowledged: number[]; skipped: number[] }>('/acknowledgements/bulk',
      { handover_ids: handoverIds }),
}

export const notificationApi = {
  list: (unread = false) => api.get<AppNotification[]>(`/notifications?unread=${unread}`),
  unreadCount: () => api.get<{ unread: number }>('/notifications/unread-count'),
  read: (id: number) => api.post<void>(`/notifications/${id}/read`),
  readAll: () => api.post<{ read: number }>('/notifications/read-all'),
}
