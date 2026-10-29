import { apiClient } from "./client";
import type { AuthResponse } from "../types";

interface RegisterPayload {
  username: string;
  password: string;
  display_name?: string;
}

export async function registerAccount(
  payload: RegisterPayload
): Promise<AuthResponse> {
  const response = await apiClient.post<AuthResponse>(
    "/auth/register",
    payload
  );
  return response.data;
}

export async function loginAccount(
  username: string,
  password: string
): Promise<AuthResponse> {
  const response = await apiClient.post<AuthResponse>(
    "/auth/login",
    { username, password }
  );
  return response.data;
}

export async function logoutAccount(): Promise<void> {
  await apiClient.post("/auth/logout");
}

export async function getCurrentAccount(): Promise<AuthResponse> {
  const response = await apiClient.get<AuthResponse>("/auth/me");
  return response.data;
}
