import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the API is Django's runserver; in production Caddy serves the built
// files and proxies /api to gunicorn on the same origin, so the app only ever
// uses relative URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
