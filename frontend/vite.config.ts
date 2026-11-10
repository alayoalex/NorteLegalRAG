import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En desarrollo, Vite hace de proxy igual que nginx en docker-compose: mismo origen, sin CORS.
const API_URL = "http://localhost:8000";
// Sin `changeOrigin` (que la forma corta activa): la API compara `Origin` con `Host` para
// rechazar peticiones de otro origen, así que `Host` debe llegar como lo envió el navegador.
const api = { target: API_URL, changeOrigin: false };

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": api,
      "/readyz": api,
    },
  },
});
