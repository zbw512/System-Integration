import type { SceneSegment } from "../types";

export const MOCK_VLM_SEGMENTS: SceneSegment[] = [
  {
    start: 10.5,
    end: 25.0,
    scene: "听讲",
    confidence: 0.95,
  },
  {
    start: 25.0,
    end: 48.0,
    scene: "小组讨论",
    confidence: 0.88,
  },
  {
    start: 48.0,
    end: 70.0,
    scene: "独立学习",
    confidence: 0.91,
  },
  {
    start: 70.0,
    end: 88.5,
    scene: "小组讨论",
    confidence: 0.86,
  },
  {
    start: 88.5,
    end: 105.0,
    scene: "听讲",
    confidence: 0.93,
  },
];

export const MOCK_VLM_RAW_SEGMENTS = MOCK_VLM_SEGMENTS.map(
  (segment) => ({
    start_s: segment.start,
    end_s: segment.end,
    scene_label: segment.scene,
    confidence: segment.confidence,
  })
);