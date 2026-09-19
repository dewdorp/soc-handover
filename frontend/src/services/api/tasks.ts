/** 할일 · 체크리스트 · 댓글 · 보드 · 내 업무 API (API.md §5). */
import { api } from '@/services/api/client'
import type { Company, Priority, UserBrief } from '@/types/api'

export type TaskStatus = 'TODO' | 'IN_PROGRESS' | 'WAITING' | 'DONE' | 'CANCELED'
export type BoardStatus = Exclude<TaskStatus, 'CANCELED'>

export interface ChecklistItem {
  id: number
  title: string
  is_done: boolean
  done_at: string | null
  done_by: number | null
  sort_order: number
}

export interface Task {
  id: number
  title: string
  description: string | null
  status: TaskStatus
  priority: Priority | null
  assignee: UserBrief | null
  creator: UserBrief | null
  company: Company | null
  handover: { id: number; title: string; is_deleted: boolean } | null
  start_date: string | null
  due_date: string | null
  completed_at: string | null
  board_order: number
  version_no: number
  is_overdue: boolean
  checklist_total: number
  checklist_done: number
  comment_count: number
  can_edit: boolean
  created_at: string
  updated_at: string
}

export interface TaskDetail extends Task {
  checklists: ChecklistItem[]
}

export interface TaskComment {
  id: number
  body: string
  author_id: number | null
  author: string | null
  created_at: string
  can_delete: boolean
}

export interface TaskInput {
  title: string
  description?: string | null
  status?: TaskStatus
  priority_code?: string
  assignee_id?: number | null
  company_id?: number | null
  handover_id?: number | null
  start_date?: string | null
  due_date?: string | null
  checklist?: string[]
}

export type TaskChanges = Partial<Omit<TaskInput, 'checklist' | 'handover_id'>>

export type Assignee = 'me' | 'all' | 'unassigned' | number

export interface TaskSearch {
  q?: string
  status?: TaskStatus[]
  include_closed?: boolean
  assignee?: Assignee
  company_id?: number | null
  handover_id?: number | null
  due?: 'overdue' | 'today' | 'this_week' | 'none' | null
  sort?: 'due_date' | 'updated_at' | 'priority' | 'created_at'
  page?: number
  size?: number
}

export interface TaskPage {
  items: Task[]
  total: number
  page: number
  size: number
}

export interface Board {
  columns: Record<BoardStatus, Task[]>
  counts: Record<BoardStatus, number>
  done_since: string
}

export type MyWorkBucket = 'all' | 'today' | 'overdue' | 'this_week' | 'upcoming'
  | 'need_ack' | 'waiting' | 'done'
export type MyWorkSource = 'all' | 'task' | 'handover' | 'ack'

export interface MyWorkItem {
  kind: 'TASK' | 'HANDOVER' | 'ACK'
  id: number
  title: string
  company: string | null
  due: string | null
  status: string | null
  status_code: string | null
  priority_code: string | null
  is_overdue: boolean
  handover_id: number | null
  ack_state: string | null
  from_user: string | null
  session_id: number | null
  checklist_total: number | null
  checklist_done: number | null
}

export interface MyWork {
  bucket: MyWorkBucket
  source: MyWorkSource
  today: string
  week_end: string
  counts: Record<MyWorkBucket, number>
  items: MyWorkItem[]
}

export const taskApi = {
  search: (body: TaskSearch) => api.post<TaskPage>('/tasks/search', body),
  board: (assignee: Assignee) => api.get<Board>(`/tasks/board?assignee=${assignee}`),
  get: (id: number) => api.get<TaskDetail>(`/tasks/${id}`),
  create: (body: TaskInput) => api.post<TaskDetail>('/tasks', body),
  update: (id: number, expected_version: number, changes: TaskChanges) =>
    api.patch<TaskDetail>(`/tasks/${id}`, { expected_version, ...changes }),
  move: (id: number, expected_version: number, status: BoardStatus, after_id: number | null) =>
    api.patch<Task>(`/tasks/${id}/move`, { expected_version, status, after_id }),
  remove: (id: number, reason?: string) => api.delete<void>(`/tasks/${id}`, reason ? { reason } : undefined),

  addChecklist: (taskId: number, title: string) =>
    api.post<ChecklistItem>(`/tasks/${taskId}/checklists`, { title }),
  updateChecklist: (id: number, body: { title?: string; is_done?: boolean }) =>
    api.patch<ChecklistItem>(`/checklists/${id}`, body),
  removeChecklist: (id: number) => api.delete<void>(`/checklists/${id}`),

  comments: (taskId: number) => api.get<TaskComment[]>(`/tasks/${taskId}/comments`),
  addComment: (taskId: number, body: string) => api.post<TaskComment>(`/tasks/${taskId}/comments`, { body }),
  removeComment: (id: number) => api.delete<void>(`/task-comments/${id}`),

  forHandover: (handoverId: number) => api.get<Task[]>(`/handovers/${handoverId}/tasks`),
  quickAdd: (handoverId: number, body: Partial<TaskInput>) =>
    api.post<TaskDetail>(`/handovers/${handoverId}/tasks`, body),

  myWork: (bucket: MyWorkBucket, source: MyWorkSource) =>
    api.get<MyWork>(`/my-work?bucket=${bucket}&source=${source}`),
}

export const STATUS_LABEL: Record<TaskStatus, string> = {
  TODO: '할일', IN_PROGRESS: '진행중', WAITING: '대기', DONE: '완료', CANCELED: '취소',
}

export const STATUS_TONE: Record<TaskStatus, string> = {
  TODO: 'text-state-open', IN_PROGRESS: 'text-state-progress', WAITING: 'text-state-wait',
  DONE: 'text-state-done', CANCELED: 'text-ink-faint',
}

export const BOARD_COLUMNS: BoardStatus[] = ['TODO', 'IN_PROGRESS', 'WAITING', 'DONE']

/** 여러 화면이 같은 할일을 보여준다 — 하나를 바꾸면 모두 새로 읽는다. */
export const TASK_QUERY_KEYS = ['tasks', 'task', 'task-board', 'my-work', 'handover-tasks', 'timeline', 'handover']
