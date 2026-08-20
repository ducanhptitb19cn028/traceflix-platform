import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { SERVICE_PORTS } from './routes.js';

// Dev proxy mirrors the production host: one origin for the browser, routed to
// the service that owns each prefix. Longer prefixes are registered last so
// Vite matches /api/catalog before a shorter sibling could claim it.
const proxy = Object.fromEntries(
  Object.entries(SERVICE_PORTS)
    .sort(([a], [b]) => a.length - b.length)
    .map(([prefix, port]) => [prefix, { target: `http://127.0.0.1:${port}`, changeOrigin: true }])
);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5174, proxy },
  build: { outDir: 'dist', emptyOutDir: true },
});
