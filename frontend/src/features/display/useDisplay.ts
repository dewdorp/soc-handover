/**
 * 화면 설정을 지금 로그인한 사람에 맞춰 읽고, 근무 시간이 바뀌면 화면을 바꾼다.
 * 메뉴에서 고르면 바로 적용되고 그 사람 설정으로 저장된다(로그인 화면은 마지막 설정을 따른다).
 */
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { referenceApi } from '@/services/api/reference'
import {
  DEFAULT_PREFS, LAST_KEY, applyDisplay, effectiveTheme, nightWindows, readNightCache, readPrefs,
  userKey, writeNightCache, writePrefs, type DisplayPrefs, type NightWindow, type Theme,
} from '@/features/display/display'

let current: DisplayPrefs = readPrefs(LAST_KEY) ?? DEFAULT_PREFS
let owner: string | null = null
const listeners = new Set<() => void>()
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } }
const snapshot = () => current

export function setDisplayPrefs(next: DisplayPrefs): void {
  current = next
  if (owner) writePrefs(owner, next)
  writePrefs(LAST_KEY, next)
  listeners.forEach((fn) => fn())
}

export interface DisplayState {
  prefs: DisplayPrefs
  theme: Theme
  windows: NightWindow[]
  setPrefs: (next: DisplayPrefs) => void
}

export function useDisplaySync(userId: number | undefined): DisplayState {
  // 사람이 바뀌면(공용 PC) 그 사람 설정으로 — 없으면 기본값. 앞사람 설정을 물려받지 않는다.
  useEffect(() => {
    if (!userId) return
    owner = userKey(userId)
    current = readPrefs(owner) ?? DEFAULT_PREFS
    writePrefs(LAST_KEY, current)
    listeners.forEach((fn) => fn())
  }, [userId])
  const prefs = useSyncExternalStore(subscribe, snapshot)

  const { data: shifts } = useQuery({
    queryKey: ['shifts', 'active'], queryFn: referenceApi.shifts,
    staleTime: 10 * 60_000, enabled: Boolean(userId),
  })
  const windows = useMemo(() => (shifts ? nightWindows(shifts) : readNightCache()), [shifts])
  useEffect(() => { if (shifts) writeNightCache(windows) }, [shifts, windows])

  // '근무에 맞춤'이면 1분마다 시각을 다시 본다 — 교대 시각에 맞춰 바뀐다.
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    if (prefs.theme !== 'shift') return
    setNow(new Date())
    const timer = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [prefs.theme])

  const theme = effectiveTheme(prefs, now, windows)
  useEffect(() => { applyDisplay(theme, prefs.size) }, [theme, prefs.size])

  return { prefs, theme, windows, setPrefs: setDisplayPrefs }
}
