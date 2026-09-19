/**
 * API 클라이언트.
 * · 인증은 HttpOnly 쿠키를 사용하므로 토큰을 JS에 보관하지 않는다.
 * · 상태 변경 요청에는 CSRF 쿠키 값을 헤더로 되돌려준다(더블 서브밋).
 * · 401 이면 refresh 를 1회만 시도하고 실패 시 로그인으로 보낸다.
 */
import type { ApiError } from '@/types/api'

const BASE = '/api/v1'
const CSRF_COOKIE = 'soc_csrf'
const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export class ApiRequestError extends Error {
  status: number
  code: string
  detail: Record<string, unknown>
  requestId?: string

  constructor(status: number, body: ApiError) {
    super(body.message || '요청을 처리하지 못했습니다.')
    this.name = 'ApiRequestError'
    this.status = status
    this.code = body.error ?? 'unknown'
    this.detail = body.detail ?? {}
    this.requestId = body.request_id
  }
}

function readCookie(name: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith(`${name}=`))
    ?.split('=')
    .slice(1)
    .join('=')
}

let refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'same-origin' })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => {
          refreshing = null
        }, 0)
      })
  }
  return refreshing
}

interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
  /** 파일 다운로드 등 JSON이 아닌 응답 */
  raw?: boolean
  /** 401 시 refresh 재시도 여부(로그인/리프레시 자체는 false) */
  retryOnUnauthorized?: boolean
}

/**
 * 상태 변경 요청의 CSRF 헤더는 **보낼 때마다** 쿠키에서 새로 읽는다.
 * 401 → refresh 는 CSRF 쿠키도 새로 발급하므로, 처음 만든 헤더로 다시 보내면 403 이 난다
 * (15분 넘게 쉬었다가 처음 저장할 때마다 '보안 토큰이 유효하지 않습니다'가 뜨던 원인).
 */
function csrfHeader(headers: Record<string, string>): Record<string, string> {
  const csrf = readCookie(CSRF_COOKIE)
  return csrf ? { ...headers, [CSRF_HEADER]: decodeURIComponent(csrf) } : headers
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const base: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) base['Content-Type'] = 'application/json'

  const send = () =>
    fetch(`${BASE}${path}`, {
      method,
      headers: SAFE_METHODS.has(method) ? base : csrfHeader(base),
      credentials: 'same-origin',
      signal: options.signal,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })

  let response = await send()

  if (response.status === 401 && (options.retryOnUnauthorized ?? true)) {
    if (await tryRefresh()) response = await send()
  }

  if (response.status === 204) return undefined as T
  if (options.raw) {
    if (!response.ok) throw new ApiRequestError(response.status, await safeJson(response))
    return response as unknown as T
  }

  const payload = await safeJson(response)
  if (!response.ok) throw new ApiRequestError(response.status, payload)
  return payload as T
}

async function safeJson(response: Response): Promise<ApiError & Record<string, unknown>> {
  try {
    return (await response.json()) as ApiError & Record<string, unknown>
  } catch {
    return {
      error: 'invalid_response',
      message: `서버 응답을 해석하지 못했습니다. (HTTP ${response.status})`,
    } as ApiError & Record<string, unknown>
  }
}

/**
 * 파일 업로드(multipart). Content-Type 은 브라우저가 boundary 와 함께 정하게 비워 둔다.
 * CSRF 헤더는 JSON 요청과 똑같이 붙인다.
 */
export async function upload<T>(path: string, form: FormData): Promise<T> {
  const send = () => fetch(`${BASE}${path}`, {
    method: 'POST', headers: csrfHeader({ Accept: 'application/json' }), credentials: 'same-origin', body: form,
  })
  let response = await send()
  if (response.status === 401 && (await tryRefresh())) response = await send()

  const payload = await safeJson(response)
  if (!response.ok) throw new ApiRequestError(response.status, payload)
  return payload as T
}

/** 서버가 만든 파일을 내려받는다. 같은 출처라 쿠키가 따라가므로 링크 클릭으로 충분하다. */
export function downloadUrl(path: string): void {
  const a = document.createElement('a')
  a.href = `${BASE}${path}`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: 'GET', signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  // 삭제는 사유가 필수인 경우가 있어 본문을 받는다(DELETE /handovers/{id} 등)
  delete: <T>(path: string, body?: unknown) => request<T>(path, { method: 'DELETE', body }),
}
