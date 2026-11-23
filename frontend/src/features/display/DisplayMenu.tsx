/**
 * 상단 바의 화면 설정 — 밝기와 글자 크기. 고르는 즉시 바뀌고 내 계정 · 이 PC 에 남는다.
 */
import { useEffect, useRef, useState } from 'react'
import { Moon, Sun, SunMoon } from 'lucide-react'
import { useEscape } from '@/hooks/useHotkeys'
import { describeWindows, type SizePref, type ThemePref } from '@/features/display/display'
import type { DisplayState } from '@/features/display/useDisplay'

const THEMES: { value: ThemePref; label: string }[] = [
  { value: 'shift', label: '근무에 맞춤' },
  { value: 'light', label: '밝게' },
  { value: 'dark', label: '어둡게' },
]
const SIZES: { value: SizePref; label: string }[] = [
  { value: 'small', label: '작게' },
  { value: 'normal', label: '보통' },
  { value: 'large', label: '크게' },
]

export default function DisplayMenu({ display }: { display: DisplayState }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const { prefs, theme, windows, setPrefs } = display
  useEscape(() => setOpen(false), open)

  useEffect(() => {
    if (!open) return
    box.current?.querySelector<HTMLInputElement>('input:checked')?.focus()
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const Icon = prefs.theme === 'shift' ? SunMoon : theme === 'dark' ? Moon : Sun
  const night = describeWindows(windows)

  return (
    <div className="relative" ref={box}>
      <button className="btn btn-sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              aria-haspopup="dialog" aria-label="화면 설정" title="화면 설정 — 밝기 · 글자 크기">
        <Icon size={15} />
      </button>
      {open && (
        <div role="dialog" aria-label="화면 설정"
             className="absolute right-0 top-full mt-1.5 z-40 w-72 card p-3 space-y-3 shadow-lg">
          <fieldset className="space-y-1">
            <legend className="text-sm font-semibold mb-1">밝기</legend>
            {THEMES.map((t) => (
              <label key={t.value} className="flex items-start gap-2 rounded px-1.5 py-1 hover:bg-surface-sunken cursor-pointer">
                <input type="radio" name="display-theme" className="mt-1 accent-brand" value={t.value}
                       checked={prefs.theme === t.value}
                       onChange={() => setPrefs({ ...prefs, theme: t.value })} />
                <span className="min-w-0">
                  <span className="block">{t.label}</span>
                  {t.value === 'shift' && (
                    <span className="block text-sm text-ink-muted">야간 근무({night})에는 어둡게</span>
                  )}
                </span>
              </label>
            ))}
          </fieldset>

          <fieldset>
            <legend className="text-sm font-semibold mb-1.5">글자 크기</legend>
            <div className="grid grid-cols-3 rounded-md border border-surface-border overflow-hidden">
              {SIZES.map((s, i) => (
                <label key={s.value}
                       className={`relative flex items-center justify-center h-8 cursor-pointer select-none
                                   ${i ? 'border-l border-surface-border' : ''}
                                   ${prefs.size === s.value ? 'bg-brand text-on-accent font-semibold' : 'hover:bg-surface-sunken'}
                                   has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand has-[:focus-visible]:ring-inset`}>
                  <input type="radio" name="display-size" value={s.value} className="sr-only"
                         checked={prefs.size === s.value}
                         onChange={() => setPrefs({ ...prefs, size: s.value })} />
                  <span className={s.value === 'small' ? 'text-sm' : s.value === 'large' ? 'text-md' : ''}>{s.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <p className="text-sm text-ink-muted border-t border-surface-border pt-2" aria-live="polite">
            {prefs.theme === 'shift'
              ? (theme === 'dark' ? '지금은 야간 근무 시간이라 어둡게 보입니다.' : '지금은 주간 근무 시간이라 밝게 보입니다.')
              : '근무 시간과 관계없이 이 밝기로 봅니다.'}
            <span className="block text-xs text-ink-faint mt-0.5">이 PC 의 내 계정에만 적용됩니다.</span>
          </p>
        </div>
      )}
    </div>
  )
}
