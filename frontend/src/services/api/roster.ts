/** 근무표 API — 4조 2교대 주기 · 내 근무 · 대근 · 맞교환. */
import { api } from '@/services/api/client'

export interface TeamMember {
  user_id: number
  display_name: string
  username: string
  is_leader: boolean
}

export interface RosterTeam {
  id: number
  code: string
  name: string
  phase_days: number
  is_active: boolean
  sort_order: number
  members: TeamMember[]
}

export interface ShiftChange {
  id: number
  kind: 'SUB' | 'SWAP' | 'OFF'
  off_user_id: number
  off_user_name: string | null
  on_user_id: number | null
  on_user_name: string | null
  reason: string | null
}

export interface ShiftStaffing {
  work_date: string
  shift_code: 'DAY' | 'NIGHT'
  shift_label: string
  team_id: number | null
  team_code: string | null
  team_name: string | null
  planned_user_ids: number[]
  planned_names: string[]
  actual_user_ids: number[]
  actual_names: string[]
  changes: ShiftChange[]
  expected: number
  short_by: number
  is_short: boolean
  is_mine: boolean
  was_mine_planned: boolean
}

export interface RosterCalendar {
  start: string
  end: string
  days: { day: string; shifts: ShiftStaffing[]; off_team_codes: string[] }[]
  cycle_days: number
  pattern: string
  epoch: string
}

export interface MyShift {
  work_date: string
  shift_code: string
  shift_label: string
  team_code: string | null
  start_at: string
  end_at: string
  with_names: string[]
  is_short: boolean
  short_by: number
}

export interface NextShift {
  work_date: string
  shift_code: 'DAY' | 'NIGHT'
  shift_label: string
  team_code: string | null
  team_name: string | null
  user_ids: number[]
  names: string[]
  is_short: boolean
  short_by: number
  replaced: ShiftChange[]
}

export interface Override extends ShiftChange {
  work_date: string
  shift_code: string
  shift_label: string
  created_by: number | null
  created_at: string | null
  canceled_at: string | null
  cancel_reason: string | null
  pair_id: number | null
}

export interface Coverage {
  start: string
  days: number
  ok: boolean
  problems: { day: string; day_teams: string[]; night_teams: string[] }[]
}

export const rosterApi = {
  teams: (includeInactive = false) =>
    api.get<RosterTeam[]>(`/roster/teams?include_inactive=${includeInactive}`),
  updateTeam: (id: number, body: Partial<Pick<RosterTeam, 'name' | 'phase_days' | 'is_active'>>) =>
    api.patch<RosterTeam>(`/roster/teams/${id}`, body),
  setMembers: (id: number, userIds: number[], leaderId: number | null) =>
    api.put<RosterTeam>(`/roster/teams/${id}/members`, { user_ids: userIds, leader_id: leaderId }),
  calendar: (view: 'week' | 'month', start?: string, mine = false) => {
    const q = new URLSearchParams({ view, mine: String(mine) })
    if (start) q.set('start', start)
    return api.get<RosterCalendar>(`/roster/calendar?${q}`)
  },
  day: (workDate: string) => api.get<ShiftStaffing[]>(`/roster/day?work_date=${workDate}`),
  mine: (days = 14) => api.get<MyShift[]>(`/roster/mine?days=${days}`),
  nextShift: () => api.get<NextShift>('/roster/next-shift'),
  coverage: (start?: string, days = 32) => {
    const q = new URLSearchParams({ days: String(days) })
    if (start) q.set('start', start)
    return api.get<Coverage>(`/roster/coverage?${q}`)
  },
  overrides: (start?: string, end?: string) => {
    const q = new URLSearchParams()
    if (start) q.set('start', start)
    if (end) q.set('end', end)
    return api.get<Override[]>(`/roster/overrides?${q}`)
  },
  substitute: (body: {
    work_date: string; shift_code: 'DAY' | 'NIGHT'
    off_user_id: number; on_user_id?: number | null; reason?: string | null
  }) => api.post<Override>('/roster/overrides', body),
  swap: (body: {
    first: { work_date: string; shift_code: 'DAY' | 'NIGHT'; user_id: number }
    second: { work_date: string; shift_code: 'DAY' | 'NIGHT'; user_id: number }
    reason?: string | null
  }) => api.post<Override[]>('/roster/swaps', body),
  cancel: (id: number, reason?: string | null) =>
    api.post<Override[]>(`/roster/overrides/${id}/cancel`, { reason }),
}
