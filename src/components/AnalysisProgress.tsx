import {
  Alert,
  Button,
  Card,
  Progress,
  Space,
  Typography,
} from "antd";
import { useAppStore } from "../store/useAppStore";

interface AnalysisProgressProps {
  onAnalyze: () => void;
}

export function AnalysisProgress({
  onAnalyze,
}: AnalysisProgressProps) {
  const status = useAppStore((state) => state.status);
  const uploadProgress = useAppStore(
    (state) => state.uploadProgress
  );
  const analysisProgress = useAppStore(
    (state) => state.analysisProgress
  );
  const progressText = useAppStore(
    (state) => state.progressText
  );
  const error = useAppStore((state) => state.error);
  const video = useAppStore((state) => state.video);
  const jobId = useAppStore((state) => state.jobId);

  const uploadCompleted =
    Boolean(video) && uploadProgress >= 100;
  const isUploading =
    status === "uploading" && !uploadCompleted;
  const isAnalyzing = status === "analyzing";
  const isSuccess = status === "success";
  const isError = status === "error";

  const percent = isUploading
    ? uploadProgress
    : isSuccess
      ? 100
      : analysisProgress;

  const progressStatus = isError
    ? "exception"
    : isSuccess
      ? "success"
      : isUploading || isAnalyzing
        ? "active"
        : "normal";

  const canAnalyze =
    Boolean(video) &&
    uploadCompleted &&
    !isUploading &&
    !isAnalyzing;

  const alertType = isError
    ? "error"
    : isSuccess
      ? "success"
      : isAnalyzing
        ? "info"
        : isUploading
          ? "info"
          : "warning";

  const alertMessage = isError
    ? "分析失败"
    : isSuccess
      ? "分析完成"
      : isAnalyzing
        ? "VLM 正在分析视频"
        : isUploading
          ? "正在上传本地视频"
          : "等待上传视频";

  const alertDescription = isError
    ? error || progressText
    : progressText;

  return (
    <Card
      title="上传与分析进度"
      size="small"
      extra={
        jobId ? (
          <Typography.Text
            type="secondary"
            style={{
              fontFamily:
                'Consolas, "Cascadia Mono", monospace',
              fontSize: 11,
            }}
          >
            任务：{jobId}
          </Typography.Text>
        ) : null
      }
    >
      <Space
        direction="vertical"
        size={14}
        style={{ width: "100%" }}
      >
        <Progress
          percent={percent}
          status={progressStatus}
          strokeColor={
            isError
              ? "#ff4d4f"
              : isSuccess
                ? "#52c41a"
                : undefined
          }
        />

        <Alert
          type={alertType}
          showIcon
          message={alertMessage}
          description={alertDescription}
        />

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <Typography.Text type="secondary">
            {video
              ? `${video.name} · 上传完成`
              : "选择视频并上传后可启动分析"}
          </Typography.Text>

          <Button
            type="primary"
            size="middle"
            onClick={onAnalyze}
            disabled={!canAnalyze}
            loading={isAnalyzing}
          >
            {isSuccess
              ? "重新分析"
              : isAnalyzing
                ? "分析中"
                : "开始分析"}
          </Button>
        </div>
      </Space>
    </Card>
  );
}