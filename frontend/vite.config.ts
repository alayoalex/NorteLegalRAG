import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En desarrollo, Vite hace de proxy igual que nginx en docker-compose: mismo origen, sin CORS.
const API_URL = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": API_URL,
      "/readyz": API_URL,
    },
  },
});
