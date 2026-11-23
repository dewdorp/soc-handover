/**
 * 화면 설정 — 밝기(근무에 맞춤 · 밝게 · 어둡게)와 글자 크기(작게 · 보통 · 크게).
 *
 * '근무에 맞춤'은 근무 설정의 **자정을 넘는 교대**(기본: 야간 18:00~09:00) 동안 야간 화면을
 * 쓴다. 어두운 관제실에서 새벽에 흰 화면을 마주하지 않게 하려는 것이 이 설정의 전부다.
 *
 * 설정은 이 PC 의 브라우저에 **사람마다** 따로 둔다(공용 PC 에서 앞사람 설정이 넘어오지 않게).
 * 로그인 화면은 마지막으로 쓴 설정을 따른다. 저장소를 못 쓰면 기본값으로 동작한다.
 */
import type { Shift } from '@/types/api'

export type ThemePref = 'shift' | 'light' | 'dark'
export type SizePref = 'small' | 'normal' | 'large'
export type Theme = 'light' | 'dark'
export interface DisplayPrefs { theme: ThemePref; size: SizePref }

/** 분 단위 [시작, 끝). 끝이 시작보다 작으면 자정을 넘는다. */
export type NightWindow = [number, number]

export const DEFAULT_PREFS: DisplayPrefs = { theme: 'shift', size: 'normal' }
/** 근무 설정을 아직 못 읽었을 때(로그인 전 · 첫 실행)의 야간 — 기본 교대 설정과 같다. */
export const FALLBACK_NIGHT: NightWindow[] = [[18 * 60, 9 * 60]]

const KEY = 'soc.display.v1'
export const LAST_KEY = `${KEY}:last`
const NIGHT_KEY = `${KEY}:night`
export const userKey = (userId: number) => `${KEY}:u${userId}`

const THEMES: ThemePref[] = ['shift', 'light', 'dark']
const SIZES: SizePref[] = ['small', 'normal', 'large']

export function readPrefs(key: string): DisplayPrefs | null {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    const v = JSON.parse(raw) as Partial<DisplayPrefs>
    return {
      theme: THEMES.includes(v.theme as ThemePref) ? (v.theme as ThemePref) : DEFAULT_PREFS.theme,
      size: SIZES.includes(v.size as SizePref) ? (v.size as SizePref) : DEFAULT_PREFS.size,
    }
  } catch {
    return null
  }
}

export function writePrefs(key: string, prefs: DisplayPrefs): void {
  try { window.localStorage.setItem(key, JSON.stringify(prefs)) } catch { /* 저장 못 해도 지금 화면엔 적용된다 */ }
}

function minutes(hhmm: string): number | null {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm)
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}

/** 운영 중인 교대 가운데 자정을 넘는 것 = 야간. 하나도 없으면 기본값을 쓴다. */
export function nightWindows(shifts: Shift[] | undefined): NightWindow[] {
  const found: NightWindow[] = []
  for (const s of shifts ?? []) {
    if (!s.is_active || !s.crosses_midnight) continue
    const a = minutes(s.start_time)
    const b = minutes(s.end_time)
    if (a !== null && b !== null && a !== b) found.push([a, b])
  }
  return found.length ? found : FALLBACK_NIGHT
}

export function inWindow(min: number, [start, end]: NightWindow): boolean {
  return start <= end ? min >= start && min < end : min >= start || min < end
}

export function isNight(now: Date, windows: NightWindow[]): boolean {
  const min = now.getHours() * 60 + now.getMinutes()
  return windows.some((w) => inWindow(min, w))
}

export function effectiveTheme(prefs: DisplayPrefs, now: Date, windows: NightWindow[]): Theme {
  if (prefs.theme === 'shift') return isNight(now, windows) ? 'dark' : 'light'
  return prefs.theme
}

export function readNightCache(): NightWindow[] {
  try {
    const raw = window.localStorage.getItem(NIGHT_KEY)
    const v = raw ? (JSON.parse(raw) as unknown) : null
    if (Array.isArray(v) && v.every((w) => Array.isArray(w) && w.length === 2 && w.every(Number.isFinite))) {
      return v as NightWindow[]
    }
  } catch { /* 기본값 */ }
  return FALLBACK_NIGHT
}

export function writeNightCache(windows: NightWindow[]): void {
  try { window.localStorage.setItem(NIGHT_KEY, JSON.stringify(windows)) } catch { /* 무시 */ }
}

export function applyDisplay(theme: Theme, size: SizePref): void {
  const root = document.documentElement
  if (root.dataset.theme !== theme) root.dataset.theme = theme
  if (root.dataset.textSize !== size) root.dataset.textSize = size
}

/** 첫 화면을 그리기 전에 부른다 — 야간에 흰 화면이 번쩍이지 않게. */
export function bootDisplay(now = new Date()): void {
  const prefs = readPrefs(LAST_KEY) ?? DEFAULT_PREFS
  applyDisplay(effectiveTheme(prefs, now, readNightCache()), prefs.size)
}

const pad = (n: number) => String(n).padStart(2, '0')
export const clock = (min: number) => `${pad(Math.floor(min / 60) % 24)}:${pad(min % 60)}`
export const describeWindows = (windows: NightWindow[]) =>
  windows.map(([a, b]) => `${clock(a)}~${clock(b)}`).join(', ')
