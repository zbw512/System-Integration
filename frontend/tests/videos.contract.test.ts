import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../src/api/client";
import {
  extractVlmSegments,
  normalizeSegments,
  uploadVideo,
} from "../src/api/videos";
import type { BackendJob, VideoRecord } from "../src/types";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("frontend video analysis contract", () => {
  it("normalizes, sorts and preserves null confidence", () => {
    const segments = normalizeSegments([
      {
        start_s: 3,
        end_s: 6,
        scene_label: "小组讨论",
        confidence: null,
      },
      {
        start_s: 0,
        end_s: 3,
        scene_label: "未分类",
        confidence: null,
      },
    ]);

    expect(segments).toEqual([
      {
        start: 0,
        end: 3,
        scene: "未分类",
        confidence: null,
      },
      {
        start: 3,
        end: 6,
        scene: "小组讨论",
        confidence: null,
      },
    ]);
  });

  it("prefers segments from the completed Job result", () => {
    const job: BackendJob = {
      job_id: "job-1",
      video_id: "video-1",
      status: "completed",
      result: {
        segments: [
          {
            start_s: 0,
            end_s: 3,
            scene_label: "独立学习",
            confidence: null,
          },
        ],
      },
    };
    const video: VideoRecord = {
      video_id: "video-1",
      name: "clip.mp4",
      status: "processed",
      size_bytes: 1,
      duration_s: 3,
      file_url: "/videos/video-1/file",
      segments: [
        {
          start_s: 0,
          end_s: 3,
          scene_label: "其他",
          confidence: null,
        },
      ],
    };

    expect(extractVlmSegments(job, video)).toEqual([
      {
        start: 0,
        end: 3,
        scene: "独立学习",
        confidence: null,
      },
    ]);
  });

  it("uploads a video with progress without exposing the cloud token", async () => {
    const progress: number[] = [];
    const file = new File(["video"], "class.mp4", {
      type: "video/mp4",
    });
    const responseVideo: VideoRecord = {
      video_id: "video-1",
      name: "class.mp4",
      status: "registered",
      size_bytes: file.size,
      duration_s: 3,
      file_url: "/videos/video-1/file",
    };

    const post = vi
      .spyOn(apiClient, "post")
      .mockImplementation(async (_url, data, config) => {
        expect(data).toBeInstanceOf(FormData);
        expect((data as FormData).get("file")).toBe(file);
        config?.onUploadProgress?.({
          loaded: 5,
          total: 10,
          bytes: 5,
          progress: 0.5,
          upload: true,
        });
        return { data: responseVideo } as never;
      });

    const result = await uploadVideo(file, (value) =>
      progress.push(value),
    );

    expect(result.video_id).toBe("video-1");
    expect(progress).toEqual([50]);
    expect(post).toHaveBeenCalledOnce();
    const headers = post.mock.calls[0][2]?.headers as
      | Record<string, string>
      | undefined;
    expect(JSON.stringify(headers ?? {})).not.toContain("Bearer");
  });
});
