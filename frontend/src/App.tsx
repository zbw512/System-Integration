import { useCallback, useEffect, useState } from "react";
import { ConfigProvider, message } from "antd";
import zhCN from "antd/locale/zh_CN";
import { getErrorMessage, isMockMode } from "./api/client";
import {
  extractVlmSegments,
  getJob,
  getJobId,
  getVideo,
  startVideoAnalysis,
} from "./api/videos";
import { AnalysisProgress } from "./components/AnalysisProgress";
import { AppHeader } from "./components/AppHeader";
import { AuthModal } from "./components/AuthModal";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { TimelineViewer } from "./components/TimelineViewer";
import { VideoUpload } from "./components/VideoUpload";
import { usePollingJob } from "./hooks/usePollingJob";
import { useAppStore } from "./store/useAppStore";
import { useAuthStore } from "./store/useAuthStore";
import type { HistoryItem } from "./types";

export default function App() {
  const [authOpen, setAuthOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const status = useAppStore((state) => state.status);
  const video = useAppStore((state) => state.video);
  const videoUrl = useAppStore((state) => state.videoUrl);
  const segments = useAppStore((state) => state.segments);
  const jobId = useAppStore((state) => state.jobId);
  const beginAnalysis = useAppStore((state) => state.beginAnalysis);
  const setJobId = useAppStore((state) => state.setJobId);
  const setAnalysisProgress = useAppStore(
    (state) => state.setAnalysisProgress
  );
  const failAnalysis = useAppStore((state) => state.failAnalysis);
  const completeAnalysis = useAppStore(
    (state) => state.completeAnalysis
  );

  const user = useAuthStore((state) => state.user);
  const authBusy = useAuthStore((state) => state.busy);
  const initializeAuth = useAuthStore((state) => state.initialize);
  const logout = useAuthStore((state) => state.logout);

  const handleCloseHistory = useCallback(() => {
    setHistoryOpen(false);
  }, []);

  useEffect(() => {
    if (!isMockMode) {
      void initializeAuth();
    }
  }, [initializeAuth]);

  usePollingJob(
    video?.video_id ?? null,
    jobId,
    status === "analyzing"
  );

  const handleAnalyze = async () => {
    if (!video || status === "analyzing") {
      return;
    }

    beginAnalysis();

    try {
      setAnalysisProgress(0, "正在创建视频分析任务...");
      const job = await startVideoAnalysis(video.video_id);
      setJobId(getJobId(job));
    } catch (error) {
      failAnalysis(getErrorMessage(error));
    }
  };

  const handleOpenLogin = () => {
    if (isMockMode) {
      message.info(
        "当前为前端 Mock 模式，账户服务需要连接本地后端后使用。"
      );
      return;
    }
    setAuthOpen(true);
  };

  const handleLogout = async () => {
    try {
      await logout();
      setHistoryOpen(false);
      message.success("已退出登录");
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const handleOpenHistoryJob = async (item: HistoryItem) => {
    if (status === "analyzing") {
      message.warning("当前视频正在分析，请完成后再打开历史记录。");
      return;
    }

    try {
      const [job, historicalVideo] = await Promise.all([
        getJob(item.job_id),
        getVideo(item.video_id),
      ]);
      const historicalSegments = extractVlmSegments(job, historicalVideo);

      if (historicalSegments.length === 0) {
        message.warning("该历史任务没有可展示的场景结果。");
        return;
      }

      completeAnalysis(historicalVideo, historicalSegments);
      setHistoryOpen(false);
      message.success("已打开历史分析结果");
      window.setTimeout(() => {
        document
          .getElementById("analysis-workspace")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1677ff",
          colorInfo: "#1677ff",
          colorSuccess: "#2f8f5b",
          colorWarning: "#b7791f",
          colorError: "#d64242",
          colorText: "#1d1d1f",
          colorTextSecondary: "#6e6e73",
          colorBorder: "#e5e5e7",
          colorBgLayout: "#f5f5f7",
          colorBgContainer: "#ffffff",
          borderRadius: 12,
          borderRadiusLG: 18,
          controlHeight: 38,
          fontFamily:
            '"SF Pro Text", "SF Pro Display", "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif',
        },
        components: {
          Button: {
            borderRadius: 10,
            primaryShadow: "none",
            fontWeight: 600,
          },
          Card: {
            headerFontSize: 15,
            headerHeight: 56,
          },
          Modal: {
            borderRadiusLG: 22,
          },
          Drawer: {
            colorBgElevated: "#fbfbfa",
          },
          Input: {
            activeShadow: "0 0 0 3px rgba(22, 119, 255, 0.12)",
          },
        },
      }}
    >
      <div className="app-shell">
        <AppHeader
          user={user}
          busy={authBusy}
          onLogin={handleOpenLogin}
          onHistory={() => setHistoryOpen(true)}
          onLogout={() => void handleLogout()}
        />

        <main className="page-main">
          <section className="hero">
            <span className="eyebrow">学生学习过程分析</span>
            <h1>
              让课堂场景可观察
              <br />
              <span>让多模态研究可展开</span>
            </h1>
            <p>
              从视频画面识别学习场景与时间结构，为后续接入脑电专注度解码和
              跨模态融合建立清晰、可追溯的分析入口。
            </p>
          </section>

          <section className="capability-band" aria-label="系统能力状态">
            <article className="capability-item is-available">
              <span className="capability-index">01</span>
              <div>
                <strong>学习场景识别</strong>
                <small>VLM 视频分析已接入</small>
              </div>
              <span className="capability-state">当前可用</span>
            </article>
            <article className="capability-item">
              <span className="capability-index">02</span>
              <div>
                <strong>脑电专注度分析</strong>
                <small>EEG 解码能力规划中</small>
              </div>
              <span className="capability-state">后续接入</span>
            </article>
            <article className="capability-item">
              <span className="capability-index">03</span>
              <div>
                <strong>多模态融合</strong>
                <small>时间对齐与融合分析规划中</small>
              </div>
              <span className="capability-state">后续接入</span>
            </article>
          </section>

          <p className="scope-note">
            当前版本仅展示实际视频分析结果并明确标记 Mock
            来源，不生成脑电曲线、专注度评分或融合结论。
          </p>

          <section className="workspace-section" id="analysis-workspace">
            <div className="section-heading">
              <div>
                <span className="eyebrow">视频分析工作台</span>
                <h2>上传课堂视频，复核场景时间轴</h2>
              </div>
              <span className="workspace-badge">
                <span aria-hidden="true" />
                文件在本地服务处理
              </span>
            </div>

            <div className="workspace-grid">
              <div className="workflow-column">
                <VideoUpload />
                <AnalysisProgress onAnalyze={handleAnalyze} />
              </div>

              <TimelineViewer
                videoUrl={videoUrl}
                segments={segments}
                video={video}
              />
            </div>
          </section>
        </main>

        <footer className="site-footer">
          <span>基于视频 VLM 与 EEG 的多模态学生学习状态分析系统</span>
          <span>本地研究初版 · 视频场景分析</span>
        </footer>

        <AuthModal
          open={authOpen}
          onClose={() => setAuthOpen(false)}
        />

        <HistoryDrawer
          open={historyOpen}
          onClose={handleCloseHistory}
          onOpenJob={handleOpenHistoryJob}
        />
      </div>
    </ConfigProvider>
  );
}
