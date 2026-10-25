import { useEffect } from "react";
import {
  extractVlmSegments,
  getJob,
  getVideo,
} from "../api/videos";
import { getErrorMessage } from "../api/client";
import { useAppStore } from "../store/useAppStore";

export const JOB_POLL_INTERVAL_MS = 2000;

function getProgressText(
  status: string,
  progress: number
): string {
  if (status === "queued") {
    return "任务已提交，等待后端处理...";
  }

  if (status === "running") {
    return progress > 0
      ? `正在抽帧分析中... ${progress}%`
      : "正在抽帧分析中...";
  }

  return "正在读取分析结果...";
}

export function usePollingJob(
  videoId: string | null,
  jobId: string | null,
  enabled: boolean
): void {
  useEffect(() => {
    if (!videoId || !jobId || !enabled) {
      return;
    }

    let disposed = false;
    let timer: number | undefined;

    const scheduleNextPoll = () => {
      if (disposed) {
        return;
      }

      timer = window.setTimeout(
        poll,
        JOB_POLL_INTERVAL_MS
      );
    };

    const poll = async () => {
      if (disposed) {
        return;
      }

      try {
        const job = await getJob(jobId);

        if (disposed) {
          return;
        }

        const store = useAppStore.getState();
        const rawProgress = Number(job.progress ?? 0);

        const progress = Number.isFinite(rawProgress)
          ? Math.max(
              0,
              Math.min(
                99,
                Math.round(rawProgress * 100)
              )
            )
          : 0;

        store.setAnalysisProgress(
          progress,
          getProgressText(job.status, progress)
        );

        if (job.status === "completed") {
          store.setAnalysisProgress(
            95,
            "正在读取 VLM 分析结果..."
          );

          const video = await getVideo(videoId);

          if (disposed) {
            return;
          }

          const segments = extractVlmSegments(
            job,
            video
          );

          if (segments.length === 0) {
            throw new Error(
              "分析任务已完成，但后端没有返回可用的场景片段。"
            );
          }

          store.completeAnalysis(video, segments);
          return;
        }

        if (job.status === "failed") {
          throw new Error(
            job.error || "视频分析任务失败。"
          );
        }

        if (job.status === "canceled") {
          throw new Error("视频分析任务已取消。");
        }

        if (
          job.status !== "queued" &&
          job.status !== "running"
        ) {
          throw new Error(
            `后端返回了未知任务状态：${job.status}`
          );
        }

        scheduleNextPoll();
      } catch (error) {
        if (disposed) {
          return;
        }

        useAppStore
          .getState()
          .failAnalysis(getErrorMessage(error));
      }
    };

    scheduleNextPoll();

    return () => {
      disposed = true;

      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [videoId, jobId, enabled]);
}