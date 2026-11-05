import { rejectStaleSession } from '@/services/sessionChanges'
import { ApiRequestError, request, type RequestOptions } from '@/services/api/client'

export interface NoteText {
  title: string
  body: string
}

export interface PersonalNote extends NoteText {
  id: number
  version_no: number
  created_at: string
  updated_at: string
}

async function send<T>(userId: number, path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await request<T>(`/me/notes${path}`, {
      ...options, headers: { 'X-Expected-User-ID': String(userId) },
    })
  } catch (e) {
    if (e instanceof ApiRequestError && (e.status === 401 || e.code === 'session_changed')) {
      rejectStaleSession(userId)
    }
    throw e
  }
}

export const notesApi = {
  list: (userId: number, signal: AbortSignal) => send<PersonalNote[]>(userId, '', { signal }),
  get: (userId: number, id: number) => send<PersonalNote>(userId, `/${id}`),
  create: (userId: number, text: NoteText) => send<PersonalNote>(userId, '', { method: 'POST', body: text }),
  update: (userId: number, note: PersonalNote, text: NoteText) => send<PersonalNote>(userId, `/${note.id}`, {
    method: 'PATCH', body: { ...text, expected_version: note.version_no },
  }),
  remove: (userId: number, note: PersonalNote) => send<void>(userId, `/${note.id}?expected_version=${note.version_no}`, { method: 'DELETE' }),
}
