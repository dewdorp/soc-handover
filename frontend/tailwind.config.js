/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // SOC 운영 화면: 밀도 우선, 저채도, 정보량 우선
      fontSize: {
        xs: ['11px', '15px'],
        sm: ['12px', '17px'],
        base: ['13px', '19px'],
        md: ['14px', '20px'],
        lg: ['16px', '23px'],
      },
      colors: {
        surface: {
          DEFAULT: '#ffffff',
          sunken: '#f6f7f9',
          raised: '#ffffff',
          border: '#e2e5ea',
        },
        ink: {
          DEFAULT: '#1a1f2b',
          muted: '#5b6472',
          faint: '#8b94a3',
        },
        brand: {
          DEFAULT: '#1d4ed8',
          soft: '#eff4ff',
        },
        state: {
          urgent: '#dc2626',
          high: '#ea580c',
          normal: '#475569',
          low: '#94a3b8',
          open: '#2563eb',
          progress: '#0891b2',
          check: '#d97706',
          wait: '#64748b',
          done: '#16a34a',
        },
      },
      spacing: {
        'row-compact': '28px',
        'row-normal': '34px',
        'row-comfortable': '42px',
      },
    },
  },
  plugins: [],
}
