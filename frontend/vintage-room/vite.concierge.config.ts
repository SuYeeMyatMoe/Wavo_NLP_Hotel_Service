import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "../../hotel/vintage_build",
    emptyOutDir: false,
    lib: {
      entry: "src/concierge.ts",
      name: "WavoMascot",
      formats: ["iife"],
      fileName: () => "concierge.js",
    },
  },
});
