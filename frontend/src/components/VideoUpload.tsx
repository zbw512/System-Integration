import { useState } from "react";
import {
  Button,
  Card,
  Progress,
  Space,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadFile } from "antd";
import { getErrorMessage } from "../api/client";
import { uploadVideo } from "../api/videos";
import { useAppStore } from "../store/useAppStore";
import { formatFileSize } from "../utils/format";

const { Dragger } = Upload;

const VIDEO_EXTENSIONS = [
  ".mp4",
  ".mov",
  ".m4v",
];

function isSupportedVideoFile(file: File): boolean {
  const normalizedName = file.name.toLowerCase();

  return VIDEO_EXTENSIONS.some((extension) =>
    normalizedName.endsWith(extension)
  );
}

export function VideoUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [localUploading, setLocalUploading] =
    useState(false);

  const status = useAppStore((state) => state.status);
  const uploadProgress = useAppStore(
    (state) => state.uploadProgress
  );
  const uploadedVideo = useAppStore(
    (state) => state.video
  );
  const startUpload = useAppStore(
    (state) => state.startUpload
  );
  const setUploadProgress = useAppStore(
    (state) => state.setUploadProgress
  );
  const setUploadedVideo = useAppStore(
    (state) => state.setUploadedVideo
  );
  const failAnalysis = useAppStore(
    (state) => state.failAnalysis
  );
  const resetAnalysis = useAppStore(
    (state) => state.resetAnalysis
  );

  const isAnalyzing = status === "analyzing";
  const isUploading =
    localUploading ||
    (status === "uploading" &&
      !uploadedVideo &&
      uploadProgress > 0);

  const isBusy = localUploading || isAnalyzing;

  const fileList: UploadFile[] = file
    ? [
        {
          uid: `${file.name}-${file.lastModified}-${file.size}`,
          name: file.name,
          status: uploadedVideo ? "done" : undefined,
          size: file.size,
          type: file.type,
        },
      ]
    : [];

  const handleUpload = async () => {
    if (!file) {
      message.warning("请先选择一个视频文件。");
      return;
    }

    if (isBusy) {
      return;
    }

    setLocalUploading(true);
    startUpload();

    try {
      const video = await uploadVideo(
        file,
        (progress) => {
          setUploadProgress(
            progress,
            `正在上传视频文件... ${progress}%`
          );
        }
      );

      setUploadedVideo(video);
      message.success("视频上传完成，可以开始 VLM 分析。");
    } catch (error) {
      const errorMessage = getErrorMessage(error);
      failAnalysis(errorMessage);
      message.error(errorMessage);
    } finally {
      setLocalUploading(false);
    }
  };

  return (
    <Card
      className="panel-card upload-panel"
      title={
        <span className="panel-title">
          <span className="panel-step">01</span>
          选择课堂视频
        </span>
      }
      size="small"
      extra={
        <Typography.Text type="secondary" className="panel-extra">
          本地服务
        </Typography.Text>
      }
    >
      <Space
        direction="vertical"
        size={14}
        style={{ width: "100%" }}
      >
        <p className="upload-note">
          支持 MP4、M4V、MOV。文件只发送到当前本地分析服务。
        </p>

        <Dragger
          accept=".mp4,.m4v,.mov,video/mp4,video/x-m4v,video/quicktime"
          maxCount={1}
          multiple={false}
          fileList={fileList}
          disabled={isBusy}
          beforeUpload={(candidate) => {
            if (!isSupportedVideoFile(candidate)) {
              message.error(
                "请选择 MP4、M4V 或 MOV 视频文件。"
              );
              return Upload.LIST_IGNORE;
            }

            resetAnalysis();
            setFile(candidate);
            return false;
          }}
          onRemove={() => {
            if (isBusy) {
              return false;
            }

            setFile(null);
            resetAnalysis();
            return true;
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 15,
              fontWeight: 600,
            }}
          >
            将课堂视频拖到这里
          </p>

          <p
            style={{
              margin: "8px 0 0",
              color: "#7a8594",
              fontSize: 13,
            }}
          >
            或点击选择文件 · 支持 MP4、M4V 和 MOV
          </p>

          <p
            style={{
              margin: "4px 0 0",
              color: "#a0a8b3",
              fontSize: 12,
            }}
          >
            是否能直接播放取决于视频内部编码
          </p>
        </Dragger>

        {file && (
          <div
            className="selected-file"
            style={{
              padding: "10px 12px",
              border: "1px solid #ececef",
              borderRadius: 10,
              background: "#fafafa",
            }}
          >
            <Typography.Text strong ellipsis>
              {file.name}
            </Typography.Text>

            <Typography.Text
              type="secondary"
              style={{
                display: "block",
                marginTop: 4,
                fontSize: 12,
              }}
            >
              大小：{formatFileSize(file.size)}
              {file.type ? ` · 类型：${file.type}` : ""}
            </Typography.Text>
          </div>
        )}

        {(isUploading || uploadProgress > 0) && (
          <Progress
            percent={uploadProgress}
            status={
              uploadProgress >= 100 && uploadedVideo
                ? "success"
                : "active"
            }
            strokeColor={
              uploadProgress >= 100 && uploadedVideo
                ? "#52c41a"
                : "#1677ff"
            }
          />
        )}

        <div
          className="panel-actions"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <Typography.Text type="secondary">
            {uploadedVideo
              ? `上传完成：${uploadedVideo.name}`
              : file
                ? "视频尚未上传"
                : "尚未选择视频"}
          </Typography.Text>

          <Button
            type="primary"
            loading={localUploading}
            disabled={!file || isBusy}
            onClick={handleUpload}
          >
            {localUploading
              ? "上传中"
              : uploadedVideo
                ? "重新上传"
                : "上传视频"}
          </Button>
        </div>
      </Space>
    </Card>
  );
}
