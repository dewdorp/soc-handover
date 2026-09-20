import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// 개발 모드에서는 Vite(5173)가 UI를, FastAPI(8080)가 API를 담당하고 프록시로 연결한다.
// 운영 모드에서는 FastAPI가 dist/ 를 직접 서빙하므로 프록시가 필요 없다.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8080',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    // 사내 PC 의 브라우저가 최신이 아닐 수 있어 기본값(아주 최신 기준)보다 넓게 잡는다.
    // Windows 10 LTSC 2019 에서 쓰는 Edge · Chrome 은 물론, 몇 해 묵은 버전에서도 열린다.
    target: ['es2019', 'chrome80', 'edge85', 'firefox78'],
  },
})
