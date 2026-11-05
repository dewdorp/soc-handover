/** 복수 담당 · 전파 · 분석 의뢰 API (§5). */
import { api } from '@/services/api/client'

export type ParticipantRole = 'OWNER' | 'CO_OWNER' | 'REQUIRED' | 'FYI'

export const ROLE_LABEL: Record<ParticipantRole, string> = {
  OWNER: '대표 담당',
  CO_OWNER: '공동 담당',
  REQUIRED: '필수 인수자',
  FYI: '참고',
}

/** 역할이 무엇을 뜻하는지 — 고르는 자리에 그대로 보여 준다. */
export const ROLE_HINT: Record<ParticipantRole, string> = {
  OWNER: '실제로 손대는 사람. 한 건에 한 명이며 목록의 담당자와 같다',
  CO_OWNER: '함께 손대는 사람. 확인해야 한다',
  REQUIRED: '손대지 않지만 확인해야 끝난다',
  FYI: '알고만 있으면 된다. 확인 대기로 잡히지 않는다',
}

export interface Participant {
  user_id: number
  display_name: string
  username: string
  role: ParticipantRole
  role_label: string
  must_ack: boolean
  note: string | null
}

export interface ParticipantCounts {
  owner: number
  co_owner: number
  required: number
  fyi: number
  total: number
  must_ack: number
}

export interface ParticipantsResult {
  participants: Participant[]
  counts: ParticipantCounts
}

export interface PropagatePreview {
  groups: { id: number; name: string; member_count: number }[]
  role: ParticipantRole
  role_label: string
  add_count: number
  add_user_ids: number[]
  excluded_count: number
  excluded_by_hand: string[]
  excluded_already_stronger: string[]
  after: ParticipantCounts
  visibility_note: string
  applied?: boolean
  participants?: Participant[]
}

export type RequestState = 'NONE' | 'REQUESTED' | 'ACCEPTED' | 'ANSWERED'

export interface AnalysisRequest {
  state: RequestState
  state_label: string
  requested_at: string | null
  requested_by: number | null
  accepted_at: string | null
  accepted_by: number | null
  answered_at: string | null
  answered_by: number | null
  request_note: string | null
  answer_note: string | null
  next_actions: RequestState[]
}

interface PropagateBody {
  group_ids: number[]
  role: ParticipantRole
  exclude_user_ids?: number[]
  note?: string | null
}

export const participantApi = {
  list: (handoverId: number) =>
    api.get<ParticipantsResult>(`/handovers/${handoverId}/participants`),
  set: (handoverId: number, participants: { user_id: number; role: ParticipantRole }[],
       note?: string | null) =>
    api.put<ParticipantsResult>(`/handovers/${handoverId}/participants`,
      { participants, note: note ?? null }),
  preview: (handoverId: number, body: PropagateBody) =>
    api.post<PropagatePreview>(`/handovers/${handoverId}/propagate/preview`, body),
  propagate: (handoverId: number, body: PropagateBody) =>
    api.post<PropagatePreview>(`/handovers/${handoverId}/propagate`, body),
}

export const requestApi = {
  get: (handoverId: number) => api.get<AnalysisRequest>(`/handovers/${handoverId}/request`),
  ask: (handoverId: number, toUserIds: number[], note: string) =>
    api.post<AnalysisRequest>(`/handovers/${handoverId}/request`,
      { to_user_ids: toUserIds, note }),
  accept: (handoverId: number, note?: string | null) =>
    api.post<AnalysisRequest>(`/handovers/${handoverId}/request/accept`, { note: note ?? null }),
  answer: (handoverId: number, note: string) =>
    api.post<AnalysisRequest>(`/handovers/${handoverId}/request/answer`, { note }),
}
