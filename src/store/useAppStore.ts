import { create } from "zustand";
import type {
  JobStatus,
  SceneSegment,
  VideoRecord,
} from "../types";

interface AppStore {
  status: JobStatus | null;
  uploadProgress: number;
  analysisProgress: number;
  progressText: string;
  video: VideoRecord | null;
  videoUrl: string | null;
  jobId: string | null;
  segments: SceneSegment[];
  error: string | null;

  startUpload: () => void;
  setUploadProgress: (
    progress: number,
    text?: string
  ) => void;
  setUploadedVideo: (video: VideoRecord) => void;
  beginAnalysis: () => void;
  setJobId: (jobId: string) => void;
  setAnalysisProgress: (
    progress: number,
    text: string
  ) => void;
  completeAnalysis: (
    video: VideoRecord,
    segments: SceneSegment[]
  ) => void;
  failAnalysis: (message: string) => void;
  resetAnalysis: () => void;
}

const initialState = {
  status: null as JobStatus | null,
  uploadProgress: 0,
  analysisProgress: 0,
  progressText: "请选择并上传一个本地视频文件。",
  video: null as VideoRecord | null,
  videoUrl: null as string | null,
  jobId: null as string | null,
  segments: [] as SceneSegment[],
  error: null as string | null,
};

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.min(100, Math.round(value)));
}

export const useAppStore = create<AppStore>((set) => ({
  ...initialState,

  startUpload: () =>
    set({
      ...initialState,
      status: "uploading",
      progressText: "正在上传视频文件...",
    }),

  setUploadProgress: (progress, text) =>
    set((state) => ({
      uploadProgress: clampPercent(progress),
      progressText:
        text ??
        (state.status === "uploading"
          ? "正在上传视频文件..."
          : state.progressText),
    })),

  setUploadedVideo: (video) =>
    set({
      status: "uploading",
      uploadProgress: 100,
      analysisProgress: 0,
      progressText: "视频上传完成，可以开始分析。",
      video,
      videoUrl: video.file_url,
      jobId: null,
      segments: [],
      error: null,
    }),

  beginAnalysis: () =>
    set({
      status: "analyzing",
      analysisProgress: 0,
      progressText: "正在创建视频分析任务...",
      jobId: null,
      segments: [],
      error: null,
    }),

  setJobId: (jobId) =>
    set({
      jobId,
    }),

  setAnalysisProgress: (progress, text) =>
    set({
      analysisProgress: clampPercent(progress),
      progressText: text,
      status: "analyzing",
      error: null,
    }),

  completeAnalysis: (video, segments) =>
    set({
      status: "success",
      uploadProgress: 100,
      analysisProgress: 100,
      progressText: `分析完成，共识别 ${segments.length} 个场景片段。`,
      video,
      videoUrl: video.file_url,
      segments,
      error: null,
    }),

  failAnalysis: (message) =>
    set({
      status: "error",
      progressText: message,
      error: message,
    }),

  resetAnalysis: () =>
    set({
      ...initialState,
    }),
}));