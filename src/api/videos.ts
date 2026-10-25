import type { AxiosProgressEvent } from "axios";
import {
  apiClient,
  isMockMode,
} from "./client";
import {
  getMockJob,
  getMockVideo,
  startMockVideoAnalysis,
  uploadMockVideo,
} from "./mock";
import type {
  BackendJob,
  ProcessVideoResponse,
  SceneSegment,
  VideoRecord,
} from "../types";

function normalizeConfidence(value: unknown): number {
  const confidence = Number(value);

  if (!Number.isFinite(confidence)) {
    return 0;
  }

  return Math.max(0, Math.min(1, confidence));
}

export function normalizeSegments(
  rawSegments: unknown
): SceneSegment[] {
  if (!Array.isArray(rawSegments)) {
    return [];
  }

  return rawSegments
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }

      const record = item as Record<string, unknown>;
      const start = Number(record.start ?? record.start_s);
      const end = Number(record.end ?? record.end_s);
      const scene = String(
        record.scene ??
          record.scene_label ??
          "其他"
      ).trim();

      if (
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        end <= start
      ) {
        return null;
      }

      return {
        start: Math.max(0, start),
        end,
        scene: scene || "其他",
        confidence: normalizeConfidence(record.confidence),
      };
    })
    .filter((segment): segment is SceneSegment => segment !== null)
    .sort((left, right) => left.start - right.start);
}

export async function uploadVideo(
  file: File,
  onUploadProgress: (progress: number) => void
): Promise<VideoRecord> {
  if (isMockMode) {
    return uploadMockVideo(file, onUploadProgress);
  }

  const formData = new FormData();
  formData.append("file", file);

  const response = await apiClient.post<VideoRecord>(
    "/videos/upload",
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
      onUploadProgress: (event: AxiosProgressEvent) => {
        if (!event.total) {
          onUploadProgress(0);
          return;
        }

        const progress = Math.round(
          (event.loaded / event.total) * 100
        );

        onUploadProgress(
          Math.max(0, Math.min(100, progress))
        );
      },
    }
  );

  return response.data;
}

export async function startVideoAnalysis(
  videoId: string
): Promise<ProcessVideoResponse> {
  if (isMockMode) {
    return startMockVideoAnalysis(videoId);
  }

  const response = await apiClient.post<ProcessVideoResponse>(
    `/videos/${encodeURIComponent(videoId)}/process`,
    {}
  );

  return response.data;
}

export async function getJob(
  jobId: string
): Promise<BackendJob> {
  if (isMockMode) {
    return getMockJob(jobId);
  }

  const response = await apiClient.get<BackendJob>(
    `/jobs/${encodeURIComponent(jobId)}`
  );

  return response.data;
}

export async function getVideo(
  videoId: string
): Promise<VideoRecord> {
  if (isMockMode) {
    return getMockVideo(videoId);
  }

  const response = await apiClient.get<VideoRecord>(
    `/videos/${encodeURIComponent(videoId)}`
  );

  return response.data;
}

export function getJobId(job: BackendJob): string {
  const jobId = job.id ?? job.job_id;

  if (!jobId) {
    throw new Error(
      "后端任务响应中缺少 job.id 或 job.job_id。"
    );
  }

  return jobId;
}

export function extractVlmSegments(
  job: BackendJob,
  video: VideoRecord
): SceneSegment[] {
  const jobSegments = job.result?.segments;
  const videoSegments =
    video.metadata?.vlm_result?.segments;

  return normalizeSegments(
    jobSegments ?? videoSegments
  );
}