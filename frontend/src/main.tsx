import React from 'react'
import ReactDOM from 'react-dom/client'
import App from '@/app/App'
import { bootDisplay } from '@/features/display/display'
import '@/index.css'

// 첫 화면을 그리기 전에 밝기 · 글자 크기를 정한다 — 야간에 흰 화면이 번쩍이지 않게.
bootDisplay()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
