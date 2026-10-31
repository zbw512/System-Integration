import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendTarget =
    env.VITE_BACKEND_PROXY_TARGET || "http://127.0.0.1:8010";
  const proxy = {
    "/api": {
      target: backendTarget,
      changeOrigin: true,
    },
    "/health": {
      target: backendTarget,
      changeOrigin: true,
    },
  };

  return {
    base: "/",
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy,
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      strictPort: true,
      proxy,
    },
    build: {
      outDir: "dist",
      sourcemap: false,
      target: "es2020",
      reportCompressedSize: true,
      chunkSizeWarningLimit: 800,
      rollupOptions: {
        output: {
          manualChunks: {
            "react-vendor": ["react", "react-dom"],
            "antd-vendor": ["antd"],
            "data-vendor": ["axios", "zustand"],
          },
        },
      },
    },
  };
});
