export type JobStatus =
  | "uploading"
  | "analyzing"
  | "success"
  | "error";

export interface SceneSegment {
  start: number;
  end: number;
  scene: string;
  confidence: number | null;
}

export interface RawVlmSegment {
  start?: number;
  end?: number;
  start_s?: number;
  end_s?: number;
  scene?: string;
  scene_label?: string;
  confidence?: number | null;
}

export interface VlmResultBlock {
  provider?: string;
  synthetic?: boolean;
  segments?: unknown[];
}

export interface VideoRecord {
  video_id: string;
  name: string;
  status: string;
  size_bytes: number;
  duration_s: number | null;
  file_url: string;
  created_at?: string;
  segments?: unknown[];
  metadata?: {
    vlm_result?: VlmResultBlock;
    [key: string]: unknown;
  };
}

export interface JobError {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
}

export interface BackendJob {
  job_id: string;
  video_id: string;
  job_type?: string;
  status: string;
  progress?: number;
  error?: JobError | null;
  result?: VlmResultBlock | null;
}

export interface ApiErrorBody {
  error?:
    | string
    | {
        code?: string;
        message?: string;
        request_id?: string;
        retryable?: boolean;
      };
  message?: string;
  request_id?: string;
}

export interface ProgressState {
  uploadProgress: number;
  analysisProgress: number;
  progressText: string;
}

export interface VideoAnalysisState {
  status: JobStatus | null;
  video: VideoRecord | null;
  videoUrl: string | null;
  jobId: string | null;
  segments: SceneSegment[];
  error: string | null;
}

export interface UploadProgressCallback {
  (progress: number): void;
}

export interface MockJobRecord {
  id: string;
  videoId: string;
  createdAt: number;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  error: JobError | null;
  result: VlmResultBlock | null;
}
