import { apiClient } from "./client";
import type { HistoryResponse } from "../types";

export async function getAnalysisHistory(
  limit = 20,
  offset = 0
): Promise<HistoryResponse> {
  const response = await apiClient.get<HistoryResponse>(
    "/history",
    { params: { limit, offset } }
  );
  return response.data;
}
