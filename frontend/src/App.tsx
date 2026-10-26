import {
  Alert,
  ConfigProvider,
  Layout,
  Space,
  Typography,
} from "antd";
import zhCN from "antd/locale/zh_CN";
import { getErrorMessage } from "./api/client";
import {
  getJobId,
  startVideoAnalysis,
} from "./api/videos";
import { AnalysisProgress } from "./components/AnalysisProgress";
import { TimelineViewer } from "./components/TimelineViewer";
import { VideoUpload } from "./components/VideoUpload";
import { usePollingJob } from "./hooks/usePollingJob";
import { useAppStore } from "./store/useAppStore";

const { Header, Content, Footer } = Layout;
const { Title, Text, Paragraph } = Typography;

export default function App() {
  const status = useAppStore((state) => state.status);
  const video = useAppStore((state) => state.video);
  const videoUrl = useAppStore((state) => state.videoUrl);
  const segments = useAppStore((state) => state.segments);
  const jobId = useAppStore((state) => state.jobId);
  const beginAnalysis = useAppStore(
    (state) => state.beginAnalysis
  );
  const setJobId = useAppStore(
    (state) => state.setJobId
  );
  const setAnalysisProgress = useAppStore(
    (state) => state.setAnalysisProgress
  );
  const failAnalysis = useAppStore(
    (state) => state.failAnalysis
  );

  usePollingJob(
    video?.id ?? null,
    jobId,
    status === "analyzing"
  );

  const handleAnalyze = async () => {
    if (!video || status === "analyzing") {
      return;
    }

    beginAnalysis();

    try {
      setAnalysisProgress(
        0,
        "正在创建视频分析任务..."
      );

      const response = await startVideoAnalysis(video.id);
      setJobId(getJobId(response.job));
    } catch (error) {
      failAnalysis(getErrorMessage(error));
    }
  };

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1677ff",
          colorInfo: "#1677ff",
          colorSuccess: "#52c41a",
          colorWarning: "#faad14",
          colorError: "#ff4d4f",
          borderRadius: 8,
          fontFamily:
            '"Segoe UI", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif',
        },
        components: {
          Card: {
            headerFontSize: 15,
          },
          Layout: {
            bodyBg: "transparent",
            footerBg: "transparent",
            headerBg: "#001529",
          },
        },
      }}
    >
      <Layout
        style={{
          minHeight: "100vh",
          background: "#f5f7fa",
        }}
      >
        <Header
          style={{
            height: "auto",
            padding: "26px 32px 24px",
            background:
              "linear-gradient(135deg, #001529 0%, #003a70 58%, #005b7f 100%)",
          }}
        >
          <Space
            direction="vertical"
            size={5}
            style={{
              width: "100%",
              maxWidth: 1180,
              margin: "0 auto",
            }}
          >
            <Text
              style={{
                color: "#69c0ff",
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.16em",
              }}
            >
              VIDEO VLM · P0 DEMO
            </Text>

            <Title
              level={2}
              style={{
                margin: 0,
                color: "#ffffff",
                letterSpacing: "-0.02em",
              }}
            >
              多模态学习状态分析系统
            </Title>

            <Paragraph
              style={{
                margin: 0,
                color: "rgba(255, 255, 255, 0.74)",
                fontSize: 13,
              }}
            >
              本地离线视频上传 · HTTP 任务轮询 · VLM
              场景时间轴联动
            </Paragraph>
          </Space>
        </Header>

        <Content
          style={{
            width: "100%",
            maxWidth: 1180,
            margin: "0 auto",
            padding: "24px 20px 32px",
          }}
        >
          <Space
            direction="vertical"
            size={16}
            style={{ width: "100%" }}
          >
            <Alert
              type="info"
              showIcon
              message="当前交付范围"
              description="第一版仅支持本地视频文件上传、VLM 异步任务轮询和视频场景时间轴联动。EEG、WebSocket、实时视频流和多模态融合已从本版本移除。"
            />

            <VideoUpload />

            <AnalysisProgress onAnalyze={handleAnalyze} />

            <TimelineViewer
              videoUrl={videoUrl}
              segments={segments}
            />
          </Space>
        </Content>

        <Footer
          style={{
            padding: "8px 24px 28px",
            color: "#8c8c8c",
            textAlign: "center",
            fontSize: 12,
          }}
        >
          视频和分析结果仅用于本地研究演示 · Video VLM
          Frontend P0
        </Footer>
      </Layout>
    </ConfigProvider>
  );
}