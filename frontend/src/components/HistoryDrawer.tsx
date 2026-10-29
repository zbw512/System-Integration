import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Skeleton,
  Tag,
  Typography,
} from "antd";
import { getErrorMessage } from "../api/client";
import { getAnalysisHistory } from "../api/history";
import type { HistoryItem } from "../types";
import { useAuthStore } from "../store/useAuthStore";
import { formatTime } from "../utils/format";

interface HistoryDrawerProps {
  open: boolean;
  onClose: () => void;
  onOpenJob: (item: HistoryItem) => void | Promise<void>;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  failed: "失败",
  canceled: "已取消",
};

function formatDate(value: string | null): string {
  if (!value) {
    return "时间未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusColor(status: string): string {
  if (status === "completed") {
    return "success";
  }
  if (status === "running" || status === "queued") {
    return "processing";
  }
  if (status === "failed") {
    return "error";
  }
  return "default";
}

export function HistoryDrawer({
  open,
  onClose,
  onOpenJob,
}: HistoryDrawerProps) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getAnalysisHistory(50, 0);
      setItems(response.items);
    } catch (loadError) {
      if (
        axios.isAxiosError(loadError) &&
        loadError.response?.status === 401
      ) {
        useAuthStore.getState().markSignedOut();
        onClose();
        setError("登录状态已过期，请重新登录。");
        return;
      }
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [onClose]);

  useEffect(() => {
    if (open) {
      void loadHistory();
    }
  }, [loadHistory, open]);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={430}
      placement="right"
      className="history-drawer"
      title={
        <div className="history-title">
          <span>
            <strong>分析历史</strong>
            <small>仅显示当前账户最近的 50 个分析任务</small>
          </span>
          <Button
            type="text"
            size="small"
            loading={loading}
            onClick={() => void loadHistory()}
          >
            刷新
          </Button>
        </div>
      }
    >
      {error && (
        <Alert
          type="error"
          showIcon
          message="历史记录加载失败"
          description={error}
          className="history-alert"
        />
      )}

      {loading && (
        <div className="history-loading">
          <Skeleton active paragraph={{ rows: 2 }} />
          <Skeleton active paragraph={{ rows: 2 }} />
          <Skeleton active paragraph={{ rows: 2 }} />
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span>
              还没有个人分析记录
              <br />
              登录后完成一次视频分析，记录会显示在这里
            </span>
          }
        />
      )}

      {!loading && items.length > 0 && (
        <div className="history-list">
          {items.map((item) => {
            const canOpen =
              item.status === "completed" && item.segment_count > 0;
            return (
              <article className="history-item" key={item.job_id}>
                <div className="history-item-top">
                  <Typography.Text strong ellipsis>
                    {item.video_name}
                  </Typography.Text>
                  <Tag color={statusColor(item.status)}>
                    {STATUS_LABELS[item.status] ?? item.status}
                  </Tag>
                </div>

                <div className="history-meta">
                  <span>{formatDate(item.created_at)}</span>
                  <span>
                    {item.duration_s === null
                      ? "时长未知"
                      : formatTime(item.duration_s)}
                  </span>
                </div>

                <div className="history-item-bottom">
                  <span className="history-result">
                    {item.segment_count > 0
                      ? `${item.segment_count} 个场景片段`
                      : "暂无场景结果"}
                    <span className="history-source">
                      {item.is_mock
                        ? "模拟结果"
                        : item.prediction_source === "model"
                          ? "真实模型"
                          : ""}
                    </span>
                  </span>

                  <Button
                    type="link"
                    size="small"
                    disabled={!canOpen}
                    onClick={() => void onOpenJob(item)}
                  >
                    {canOpen ? "查看" : "不可打开"}
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Drawer>
  );
}
