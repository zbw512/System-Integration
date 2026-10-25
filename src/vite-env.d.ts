/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_USE_MOCK?: "true" | "false";
  readonly VITE_REQUEST_TIMEOUT_MS?: string;
  readonly VITE_BACKEND_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}