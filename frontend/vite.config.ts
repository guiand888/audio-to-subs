import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import path from "path"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Bake the app version into the bundle at build time. Sourced from the
  // VITE_APP_VERSION build arg (compose passes APP_VERSION → see the frontend
  // Dockerfile). Falls back to "dev" for a plain `vite build`/`vite dev`.
  define: {
    __APP_VERSION__: JSON.stringify(process.env.VITE_APP_VERSION ?? "dev"),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: false,
      },
    },
  },
})
