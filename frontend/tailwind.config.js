/** @type {import('tailwindcss').Config} */
import colors from 'tailwindcss/colors'

// 색은 CSS 변수에서 온다 — 주간/야간 화면이 같은 클래스(bg-surface, text-ink …)를 그대로 쓴다.
// 값은 src/index.css 의 :root(주간) · [data-theme='dark'](야간)에 있다.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`

// 글자 크기는 --text-scale(작게 0.93 · 보통 1 · 크게 1.12)을 곱한다. 글자만 커지고
// 여백 · 줄 높이 칸 · 버튼 높이는 그대로라, 크게 해도 화면 배치가 흔들리지 않는다.
const fs = (size, line) => [`calc(${size}rem * var(--text-scale, 1))`, `calc(${line}rem * var(--text-scale, 1))`]

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // SOC 운영 화면: 밀도 우선, 저채도, 정보량 우선. 기본(보통)은 1.4.0 보다 1px 크다.
      fontSize: {
        xs: fs(0.75, 1.0625),      // 12 / 17
        sm: fs(0.8125, 1.1875),    // 13 / 19
        base: fs(0.875, 1.3125),   // 14 / 21
        md: fs(0.9375, 1.375),     // 15 / 22
        lg: fs(1.0625, 1.5625),    // 17 / 25
        xl: fs(1.25, 1.75),        // 20 / 28
        '2xl': fs(1.5, 2),         // 24 / 32
      },
      colors: {
        surface: {
          DEFAULT: v('surface'),
          sunken: v('surface-sunken'),
          raised: v('surface-raised'),
          border: v('surface-border'),
          nav: v('surface-nav'),
        },
        ink: {
          DEFAULT: v('ink'),
          muted: v('ink-muted'),
          faint: v('ink-faint'),
        },
        brand: {
          DEFAULT: v('brand'),
          soft: v('brand-soft'),
        },
        // 기준색 · 상태색으로 칠한 바탕 위의 글자(주간 흰색, 야간 짙은 색)
        'on-accent': v('on-accent'),
        state: {
          urgent: v('state-urgent'),
          'urgent-soft': v('state-urgent-soft'),
          high: v('state-high'),
          normal: v('state-normal'),
          low: v('state-low'),
          open: v('state-open'),
          progress: v('state-progress'),
          check: v('state-check'),
          wait: v('state-wait'),
          done: v('state-done'),
        },
        // 오류 · 경고 · 완료 상자에 쓰던 기본 팔레트 칸도 야간에 맞춰 바뀐다
        red: { ...colors.red, 50: v('red-50'), 100: v('red-100'), 200: v('red-200'), 900: v('red-900') },
        amber: {
          ...colors.amber, 50: v('amber-50'), 100: v('amber-100'), 200: v('amber-200'), 300: v('amber-300'),
          500: v('amber-500'), 800: v('amber-800'), 900: v('amber-900'),
        },
        green: { ...colors.green, 50: v('green-50'), 100: v('green-100'), 200: v('green-200'), 900: v('green-900') },
      },
      spacing: {
        // 목록 줄 높이 — 글자 크기를 '크게'로 해도 글이 잘리지 않게 rem 이 아니라 글자 배율을 따른다
        'row-compact': 'calc(1.75rem * max(1, var(--text-scale, 1)))',
        'row-normal': 'calc(2.125rem * max(1, var(--text-scale, 1)))',
        'row-comfortable': 'calc(2.625rem * max(1, var(--text-scale, 1)))',
      },
      fontFamily: {
        mono: ['D2Coding', 'Consolas', '"Cascadia Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
