import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { MouseEvent } from "react";
import {
  Alert,
  Card,
  Empty,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { SceneSegment, VideoRecord } from "../types";
import { formatPercent, formatTime } from "../utils/format";
import { getSceneColor } from "../utils/sceneColors";

interface TimelineViewerProps {
  videoUrl: string | null;
  segments: SceneSegment[];
  video: VideoRecord | null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function TimelineViewer({
  videoUrl,
  segments,
  video,
}: TimelineViewerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [videoError, setVideoError] = useState<string | null>(
    null
  );

  useEffect(() => {
    setCurrentTime(0);
    setDuration(0);
    setVideoError(null);
  }, [videoUrl]);

  const activeSegment = useMemo(() => {
    return (
      segments.find(
        (segment) =>
          currentTime >= segment.start &&
          currentTime < segment.end
      ) ?? null
    );
  }, [currentTime, segments]);

  const getPercent = (seconds: number): number => {
    if (duration <= 0) {
      return 0;
    }

    return clamp((seconds / duration) * 100, 0, 100);
  };

  const handleTimeUpdate = () => {
    const video = videoRef.current;

    if (!video) {
      return;
    }

    setCurrentTime(video.currentTime);
  };

  const handleSeek = (
    event: MouseEvent<HTMLButtonElement>,
    segment: SceneSegment
  ) => {
    event.preventDefault();
    event.stopPropagation();

    const video = videoRef.current;

    if (!video) {
      return;
    }

    const maximumSeekTime =
      Number.isFinite(video.duration) && video.duration > 0
        ? video.duration
        : segment.start;

    const targetTime = clamp(
      segment.start,
      0,
      maximumSeekTime
    );

    video.currentTime = targetTime;
    setCurrentTime(targetTime);

    void video.play().catch(() => {
      // 浏览器可能阻止自动播放，保留 seek 结果即可。
    });
  };

  if (!videoUrl) {
    return (
      <Card
        className="timeline-panel timeline-panel-empty"
        title={
          <span className="panel-title">
            <span className="panel-step">03</span>
            视频与场景时间轴
          </span>
        }
        size="small"
      >
        <div className="timeline-empty">
          <div className="timeline-empty-art" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span>
                上传视频并完成分析后
                <br />
                在这里复核视频与学习场景时间轴
              </span>
            }
          />
        </div>
      </Card>
    );
  }

  const activeColors = activeSegment
    ? getSceneColor(activeSegment.scene)
    : null;

  return (
    <Card
      className="timeline-panel"
      title={
        <span className="panel-title">
          <span className="panel-step">03</span>
          视频与场景时间轴
        </span>
      }
      size="small"
      extra={
        activeSegment ? (
          <Tag
            style={{
              marginInlineEnd: 0,
              color: activeColors?.text,
              background: activeColors?.background,
              borderColor: activeColors?.border,
            }}
          >
            当前场景：{activeSegment.scene}
          </Tag>
        ) : (
          <Tag style={{ marginInlineEnd: 0 }}>
            当前时间无场景结果
          </Tag>
        )
      }
    >
      <Space
        direction="vertical"
        size={16}
        style={{ width: "100%" }}
      >
        {videoError && (
          <Alert
            type="error"
            showIcon
            message="视频无法播放"
            description={videoError}
          />
        )}

        <div className="analysis-source">
          <span>
            <strong>分析来源</strong>
            {video?.prediction_source === "mock"
              ? "模拟适配器"
              : video?.provider || "视觉模型"}
          </span>
          <span>
            {video?.model?.name
              ? `${video.model.name}${
                  video.model.version ? ` ${video.model.version}` : ""
                }`
              : "模型版本未提供"}
          </span>
          {video?.prediction_source === "mock" && (
            <Tag bordered={false} color="warning">
              Mock 结果，不用于模型评价
            </Tag>
          )}
        </div>

        <div
          className="video-frame"
          style={{
            overflow: "hidden",
            borderRadius: 14,
            background: "#000",
          }}
        >
          <video
            ref={videoRef}
            src={videoUrl}
            controls
            playsInline
            preload="metadata"
            aria-label="视频播放器"
            onLoadedMetadata={(event) => {
              const media = event.currentTarget;
              const mediaDuration = media.duration;

              setDuration(
                Number.isFinite(mediaDuration) &&
                  mediaDuration > 0
                  ? mediaDuration
                  : 0
              );

              setCurrentTime(media.currentTime);
              setVideoError(null);
            }}
            onTimeUpdate={handleTimeUpdate}
            onSeeked={handleTimeUpdate}
            onPlay={() => {
              setVideoError(null);
            }}
            onError={(event) => {
              const errorCode = event.currentTarget.error?.code;

              if (errorCode === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
                setVideoError(
                  "浏览器不支持该视频格式，请让后端转码为 H.264 MP4 或 WebM。"
                );
                return;
              }

              if (errorCode === MediaError.MEDIA_ERR_DECODE) {
                setVideoError(
                  "视频解码失败，请检查视频文件或后端转码结果。"
                );
                return;
              }

              setVideoError(
                "视频加载失败，请确认本地文件接口正常并支持 HTTP Range。"
              );
            }}
            style={{
              display: "block",
              width: "100%",
              maxHeight: "65vh",
              background: "#000",
              objectFit: "contain",
            }}
          />
        </div>

        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              marginBottom: 8,
            }}
          >
            <Typography.Text strong>
              VLM 场景时间轴
            </Typography.Text>

            <Typography.Text
              type="secondary"
              style={{
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {formatTime(currentTime)} /{" "}
              {formatTime(duration)}
            </Typography.Text>
          </div>

          <div
            aria-label="视频场景时间轴"
            className="timeline-track"
            style={{
              position: "relative",
              width: "100%",
              minHeight: 86,
              overflow: "hidden",
              borderRadius: 12,
              border: "1px solid #e5e5e7",
              background: "#ffffff",
            }}
          >
            {[0, 25, 50, 75, 100].map((percent) => (
              <div
                key={percent}
                aria-hidden="true"
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: `${percent}%`,
                  width: 1,
                  background:
                    percent === 100
                      ? "transparent"
                      : "#f0f0f0",
                }}
              />
            ))}

            {[0, 25, 50, 75, 100].map((percent) => (
              <span
                key={`label-${percent}`}
                aria-hidden="true"
                style={{
                  position: "absolute",
                  top: 3,
                  left: `${percent}%`,
                  color: "#8c8c8c",
                  fontSize: 10,
                  fontVariantNumeric: "tabular-nums",
                  transform:
                    percent === 0
                      ? "translateX(4px)"
                      : percent === 100
                        ? "translateX(calc(-100% - 4px))"
                        : "translateX(-50%)",
                  whiteSpace: "nowrap",
                }}
              >
                {formatTime(duration * (percent / 100))}
              </span>
            ))}

            <div
              style={{
                position: "absolute",
                top: 20,
                right: 0,
                bottom: 0,
                left: 0,
              }}
            >
              {segments.map((segment, index) => {
                const left = getPercent(segment.start);
                const right = getPercent(segment.end);
                const width = Math.max(0.4, right - left);
                const colors = getSceneColor(segment.scene);
                const active =
                  activeSegment?.start === segment.start &&
                  activeSegment?.end === segment.end &&
                  activeSegment?.scene === segment.scene;

                const tooltipContent = (
                  <div>
                    <div>
                      <strong>{segment.scene}</strong>
                    </div>
                    <div>
                      {formatTime(segment.start)} —{" "}
                      {formatTime(segment.end)}
                    </div>
                    <div>
                      置信度：{formatPercent(segment.confidence)}
                    </div>
                    <div>点击跳转到该场景</div>
                  </div>
                );

                return (
                  <Tooltip
                    key={`${segment.start}-${segment.end}-${segment.scene}-${index}`}
                    title={tooltipContent}
                  >
                    <button
                      type="button"
                      aria-label={`跳转到 ${segment.scene}，时间 ${formatTime(
                        segment.start
                      )}`}
                      onClick={(event) =>
                        handleSeek(event, segment)
                      }
                      style={{
                        position: "absolute",
                        top: active ? 2 : 6,
                        left: `${left}%`,
                        width: `max(${width}%, 4px)`,
                        height: active ? 54 : 46,
                        padding: "4px 6px",
                        overflow: "hidden",
                        color: colors.text,
                        textAlign: "left",
                        whiteSpace: "nowrap",
                        textOverflow: "ellipsis",
                        cursor: "pointer",
                        background: colors.background,
                        border: `2px solid ${colors.border}`,
                        borderRadius: 6,
                        boxShadow: active
                          ? `0 0 0 3px ${colors.border}33, 0 0 12px ${colors.border}55`
                          : "none",
                        transform: "translateY(0)",
                        transition:
                          "top 120ms ease, height 120ms ease, box-shadow 120ms ease",
                        zIndex: active ? 2 : 1,
                      }}
                    >
                      <span
                        style={{
                          display: "block",
                          overflow: "hidden",
                          fontSize: 11,
                          fontWeight: active ? 700 : 500,
                          textOverflow: "ellipsis",
                        }}
                      >
                        {segment.scene}
                      </span>

                      <span
                        style={{
                          display: "block",
                          marginTop: 4,
                          overflow: "hidden",
                          fontSize: 10,
                          opacity: 0.78,
                          textOverflow: "ellipsis",
                        }}
                      >
                        {formatTime(segment.start)} ·{" "}
                        {formatPercent(segment.confidence)}
                      </span>
                    </button>
                  </Tooltip>
                );
              })}

              {segments.length === 0 && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "grid",
                    color: "#8c8c8c",
                    fontSize: 12,
                    placeItems: "center",
                    pointerEvents: "none",
                  }}
                >
                  分析完成后显示 VLM 场景片段
                </div>
              )}
            </div>

            {duration > 0 && (
              <div
                aria-hidden="true"
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: `${getPercent(currentTime)}%`,
                  width: 2,
                  background: "#ff4d4f",
                  boxShadow:
                    "0 0 6px rgba(255, 77, 79, 0.65)",
                  transform: "translateX(-1px)",
                  pointerEvents: "none",
                  zIndex: 3,
                }}
              />
            )}
          </div>
        </div>

        <Typography.Text type="secondary">
          视频播放时会自动高亮当前场景；点击时间轴色块可跳转到对应片段开始时间。
        </Typography.Text>
      </Space>
    </Card>
  );
}
