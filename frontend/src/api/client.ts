import axios from "axios";
import type { AxiosError } from "axios";
import type { ApiErrorBody } from "../types";

const configuredTimeout = Number(
  import.meta.env.VITE_REQUEST_TIMEOUT_MS ?? "30000"
);

const timeout =
  Number.isFinite(configuredTimeout) && configuredTimeout > 0
    ? configuredTimeout
    : 30000;

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  timeout,
  headers: {
    Accept: "application/json",
  },
});

export const isMockMode =
  import.meta.env.VITE_USE_MOCK === "true";

function getPayloadMessage(
  payload: ApiErrorBody | undefined
): string | null {
  if (!payload) {
    return null;
  }

  if (typeof payload.error === "string") {
    return payload.error;
  }

  if (
    payload.error &&
    typeof payload.error === "object" &&
    typeof payload.error.message === "string"
  ) {
    return payload.error.message;
  }

  if (typeof payload.message === "string") {
    return payload.message;
  }

  return null;
}

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiErrorBody>;
    const payloadMessage = getPayloadMessage(
      axiosError.response?.data
    );

    if (payloadMessage) {
      return payloadMessage;
    }

    if (axiosError.code === "ECONNABORTED") {
      return "请求超时，请检查本地分析服务是否正常运行。";
    }

    if (axiosError.code === "ERR_NETWORK") {
      return "无法连接本地分析服务，请确认后端已经启动。";
    }

    if (!axiosError.response) {
      return "网络请求失败，请检查本地服务连接。";
    }

    return `请求失败：HTTP ${axiosError.response.status}`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "发生未知错误，请稍后重试。";
}

export function getRequestId(error: unknown): string | null {
  if (!axios.isAxiosError(error)) {
    return null;
  }

  const axiosError = error as AxiosError<ApiErrorBody>;
  const payload = axiosError.response?.data;

  if (payload?.request_id) {
    return payload.request_id;
  }

  if (
    payload?.error &&
    typeof payload.error === "object" &&
    payload.error.request_id
  ) {
    return payload.error.request_id;
  }

  const responseRequestId =
    axiosError.response?.headers["x-request-id"];

  return typeof responseRequestId === "string"
    ? responseRequestId
    : null;
}