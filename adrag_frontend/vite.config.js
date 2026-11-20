import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'dist',
  },
  server: {
    port: 3001,
    open: true, // 개발 서버 시작 시 브라우저 자동 열기
    proxy: {
      '/api': {
        // 2026.10.26(sooyeon.choi) 수정 - 백엔드 포트 8000 → 8081 변경
        target: 'http://localhost:8081',  // 로컬 backend 직접 연결
        // target: 'http://10.10.10.109',  // 아파치 프록시 경유 (80포트)
        changeOrigin: true,
      },
    },
  },
});
