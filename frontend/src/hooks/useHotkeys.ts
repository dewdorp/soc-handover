/**
 * 키보드 단축키 (UI_STRUCTURE §10).
 *
 * 글자가 아니라 **키 위치(e.code)** 로 판별한다. 한글 입력 상태에서 j 를 누르면 e.key 는 'ㅓ' 라서
 * 글자로 비교하면 한/영 상태에 따라 단축키가 먹었다 안 먹었다 한다.
 * 한 글자 단축키는 입력 칸에 쓰는 중이거나 대화상자(aria-modal)가 열려 있으면 무시한다.
 */
import { useEffect, useRef } from 'react'

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}

/** 두벌식 자판에서 같은 자리의 영문 키 — code 가 비어 오는 입력(원격 조작·가상 키보드)용. */
const HANGUL_KEY: Record<string, string> = {
  'ㅓ': 'j', 'ㅏ': 'k', 'ㄷ': 'e', 'ㅁ': 'a', 'ㅠ': 'b', 'ㅜ': 'n', 'ㅅ': 't',
}

/** 키 위치. 보통은 e.code 이고, 비어 있으면 입력된 글자로 대신 맞춘다. */
export function keyCode(e: KeyboardEvent): string {
  if (e.code) return e.code
  if (e.key === '/' || e.key === '?') return 'Slash'
  if (e.key === 'Enter') return 'Enter'
  const k = HANGUL_KEY[e.key] ?? e.key
  return /^[a-z]$/i.test(k) ? `Key${k.toUpperCase()}` : e.key
}

export function modalOpen(): boolean {
  return document.querySelector('[aria-modal="true"]') != null
}

/**
 * 창(대화상자)의 Esc 닫기. 창이 먼저 받아서 멈춘다(capture) — 뒤에 열린 상세 패널까지 닫히지 않게.
 * 창 안에 또 창을 띄우면 바깥 창은 enabled=false 로 둔다.
 */
export function useEscape(onClose: () => void, enabled = true): void {
  const latest = useRef(onClose)
  latest.current = onClose
  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      latest.current()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [enabled])
}

/** 수식키 없는 한 글자 단축키. map 의 키는 e.code(KeyJ, Enter …). */
export function useHotkeys(map: Record<string, (e: KeyboardEvent) => void>, enabled = true): void {
  const latest = useRef(map)
  latest.current = map
  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || e.isComposing) return
      if (isTyping(e.target) || modalOpen()) return
      // 버튼·링크에 포커스가 있을 때 Enter 는 그것을 누르는 키다 — 가로채지 않는다
      if (e.code === 'Enter' && (e.target as HTMLElement | null)?.closest?.('button, a, [role="button"], summary')) return
      const handler = latest.current[keyCode(e)]
      if (!handler) return
      e.preventDefault()
      handler(e)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}

export interface ShortcutDoc { keys: string; action: string }

/** 도움말(?)에 보이는 목록 — 실제로 동작하는 것만 적는다. */
export const SHORTCUTS: { group: string; items: ShortcutDoc[] }[] = [
  {
    group: '어디서나',
    items: [
      { keys: 'Ctrl + K', action: '통합검색 (맥은 Cmd + K)' },
      { keys: '/', action: '목록 화면이면 그 화면 검색창, 아니면 통합검색' },
      { keys: 'Alt + N', action: '새 인수인계' },
      { keys: 'Alt + T', action: '새 할일' },
      { keys: '?', action: '이 도움말' },
      { keys: 'Esc', action: '창 · 상세 닫기' },
    ],
  },
  {
    group: '인수인계 목록',
    items: [
      { keys: 'j / k', action: '다음 / 이전 행 (상세가 열려 있으면 상세도 따라감)' },
      { keys: 'Enter', action: '고른 행 상세 열기' },
      { keys: 'e', action: '고른 행 수정' },
      { keys: 'a', action: '고른 행 확인(Ack)' },
      { keys: 'b', action: '고른 행을 교대 인계 Basket 에 담기' },
    ],
  },
]
