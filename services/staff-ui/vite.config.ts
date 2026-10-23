// Vite build for the staff UI. In development, API calls are proxied to the
// local backend so no CORS setup is needed.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/staff": "http://localhost:8000" },
  },
  build: { sourcemap: false },
});
