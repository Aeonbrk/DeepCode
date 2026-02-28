import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/');
          if (!normalizedId.includes('/node_modules/')) {
            return;
          }

          if (normalizedId.includes('/node_modules/@tanstack/')) {
            return 'tanstack';
          }

          if (
            normalizedId.includes('/node_modules/@radix-ui/') ||
            normalizedId.includes('/node_modules/framer-motion/') ||
            normalizedId.includes('/node_modules/lucide-react/')
          ) {
            return 'ui-vendor';
          }

          if (
            normalizedId.includes('/node_modules/@monaco-editor/') ||
            normalizedId.includes('/node_modules/monaco-editor/')
          ) {
            return 'monaco-vendor';
          }
          return;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
