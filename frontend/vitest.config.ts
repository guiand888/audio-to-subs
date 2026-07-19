import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import path from "path"

export default defineConfig({
  plugins: [react()],
  // Mirror vite.config's build-time constant so components referencing
  // __APP_VERSION__ compile under the test runner.
  define: {
    __APP_VERSION__: JSON.stringify(process.env.VITE_APP_VERSION ?? "dev"),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
})
