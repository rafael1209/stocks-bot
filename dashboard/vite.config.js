import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev server proxies the bot's API (py dashboard_api.py on :8787)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8787", "/charts": "http://127.0.0.1:8787" },
  },
});
