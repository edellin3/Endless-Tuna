import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
// Only a local port is read here; credentials never use VITE_* or reach browser code.
const apiPort = loadEnv("development", ".", "TUNA_API_PORT").TUNA_API_PORT || "8000";
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", proxy: { "/api": `http://127.0.0.1:${apiPort}` } },
});
