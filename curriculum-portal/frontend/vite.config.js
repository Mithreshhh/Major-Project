import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// TODO: adjust dev server port / proxy target once backend API URL is finalized
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:4000',
        changeOrigin: true,
      },
    },
  },
});
