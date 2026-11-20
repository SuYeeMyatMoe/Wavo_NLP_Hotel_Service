import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../../hotel/vintage_build",
    emptyOutDir: true,
    minify: "esbuild",
    lib: {
      entry: "src/streamlit.tsx",
      formats: ["es"],
      fileName: () => "room.js",
      cssFileName: "room",
    },
  },
});
