import { defineConfig } from 'vite'

// Container-friendly dev server: bind every interface and, when running inside
// Docker against a bind-mounted source tree, poll for file changes so hot module
// reload fires across the Windows/Docker boundary (set VITE_USE_POLLING=true).
export default defineConfig({
  server: {
    host: true,
    watch: process.env.VITE_USE_POLLING
      ? { usePolling: true, interval: 120 }
      : undefined,
  },
})
