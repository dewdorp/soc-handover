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
          sunken: '#f2f6f6',
          raised: '#ffffff',
          border: '#d8e2e4',
          nav: '#19343e',
        },
        ink: {
          DEFAULT: '#18323a',
          muted: '#50646c',
          faint: '#5c7077',
        },
        brand: {
          DEFAULT: '#08685e',
          soft: '#e3f3ef',
        },
        state: {
          urgent: '#b52637',
          high: '#a3450b',
          normal: '#475569',
          low: '#5d7079',
          open: '#2563eb',
          progress: '#09697b',
          check: '#89560d',
          wait: '#64748b',
          done: '#11724b',
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
