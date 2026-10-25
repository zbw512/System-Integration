import { MOCK_VLM_SEGMENTS } from "../mock/vlmSegments";
import type {
  BackendJob,
  MockJobRecord,
  VideoRecord,
  VlmResultBlock,
} from "../types";

const MOCK_JOB_QUEUE_MS = 1500;
const MOCK_JOB_RUNNING_MS = 5000;

const mockJobs = new Map<string, MockJobRecord>();
const mockVideos = new Map<string, VideoRecord>();
const mockObjectUrls = new Set<string>();

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function createJobId(): string {
  return `mock-job-${Date.now()}-${Math.random()
    .toString(16)
    .slice(2, 8)}`;
}

function createMockResult(): VlmResultBlock {
  return {
    provider: "mock_vlm",
    synthetic: true,
    segments: MOCK_VLM_SEGMENTS.map((segment) => ({
      start_s: segment.start,
      end_s: segment.end,
      scene_label: segment.scene,
      confidence: segment.confidence,
    })),
  };
}

function toBackendJob(job: MockJobRecord): BackendJob {
  return {
    id: job.id,
    job_type: "video_process",
    status: job.status,
    progress: job.progress,
    result: job.result,
    error: job.error,
  };
}

export async function uploadMockVideo(
  file: File,
  onUploadProgress: (progress: number) => void
): Promise<VideoRecord> {
  const steps = 10;

  for (let index = 1; index <= steps; index += 1) {
    await wait(120);
    onUploadProgress(Math.round((index / steps) * 100));
  }

  const objectUrl = URL.createObjectURL(file);
  mockObjectUrls.add(objectUrl);

  const video: VideoRecord = {
    id: `mock-video-${Date.now()}`,
    name: file.name,
    status: "registered",
    size_bytes: file.size,
    duration_s: null,
    file_url: objectUrl,
    created_at: new Date().toISOString(),
    metadata: {
      mock: true,
    },
  };

  mockVideos.set(video.id, video);
  return video;
}

export async function startMockVideoAnalysis(
  videoId: string
): Promise<{ video_id: string; job: BackendJob }> {
  if (!mockVideos.has(videoId)) {
    throw new Error(`Mock 视频不存在：${videoId}`);
  }

  const job: MockJobRecord = {
    id: createJobId(),
    videoId,
    createdAt: Date.now(),
    status: "queued",
    progress: 0,
    error: null,
    result: null,
  };

  mockJobs.set(job.id, job);

  return {
    video_id: videoId,
    job: toBackendJob(job),
  };
}

export async function getMockJob(
  jobId: string
): Promise<BackendJob> {
  const job = mockJobs.get(jobId);

  if (!job) {
    throw new Error(`Mock 任务不存在：${jobId}`);
  }

  const elapsed = Date.now() - job.createdAt;

  if (elapsed < MOCK_JOB_QUEUE_MS) {
    job.status = "queued";
    job.progress = 0;
  } else if (elapsed < MOCK_JOB_RUNNING_MS) {
    job.status = "running";
    job.progress = Math.min(
      0.9,
      0.1 + ((elapsed - MOCK_JOB_QUEUE_MS) / MOCK_JOB_RUNNING_MS) * 0.8
    );
  } else {
    job.status = "completed";
    job.progress = 1;
    job.result = createMockResult();

    const video = mockVideos.get(job.videoId);

    if (video) {
      mockVideos.set(job.videoId, {
        ...video,
        status: "processed",
        metadata: {
          ...video.metadata,
          vlm_result: job.result,
        },
      });
    }
  }

  return toBackendJob(job);
}

export async function getMockVideo(
  videoId: string
): Promise<VideoRecord> {
  const video = mockVideos.get(videoId);

  if (!video) {
    throw new Error(`Mock 视频不存在：${videoId}`);
  }

  return video;
}

export function resetMockState(): void {
  mockJobs.clear();
  mockVideos.clear();

  mockObjectUrls.forEach((url) => {
    URL.revokeObjectURL(url);
  });

  mockObjectUrls.clear();
}