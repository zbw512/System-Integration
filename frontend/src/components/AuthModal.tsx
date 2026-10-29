import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Segmented,
  Typography,
  message,
} from "antd";
import { getErrorMessage } from "../api/client";
import { useAuthStore } from "../store/useAuthStore";

interface AuthModalProps {
  open: boolean;
  onClose: () => void;
}

type AuthMode = "login" | "register";

interface AuthValues {
  username?: string;
  password?: string;
  display_name?: string;
}

export function AuthModal({ open, onClose }: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [form] = Form.useForm<AuthValues>();
  const [error, setError] = useState<string | null>(null);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const busy = useAuthStore((state) => state.busy);

  useEffect(() => {
    if (open) {
      setError(null);
      form.resetFields();
    }
  }, [form, open]);

  const handleSubmit = async (values: AuthValues) => {
    setError(null);

    try {
      if (mode === "login") {
        await login(values.username?.trim() ?? "", values.password ?? "");
        message.success("已登录");
      } else {
        await register(
          values.username?.trim() ?? "",
          values.password ?? "",
          values.display_name
        );
        message.success("账户已创建");
      }
      onClose();
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={430}
      centered
      destroyOnHidden
      className="auth-modal"
    >
      <div className="auth-heading">
        <span className="eyebrow">个人研究空间</span>
        <Typography.Title level={2}>
          {mode === "login" ? "登录" : "创建本地账户"}
        </Typography.Title>
        <Typography.Paragraph>
          登录后可查看自己的视频分析历史。当前功能不影响未登录状态下的视频分析。
        </Typography.Paragraph>
      </div>

      <Segmented
        block
        value={mode}
        options={[
          { label: "登录", value: "login" },
          { label: "创建账户", value: "register" },
        ]}
        onChange={(value) => {
          setMode(value as AuthMode);
          setError(null);
          form.resetFields();
        }}
      />

      {error && (
        <Alert
          className="auth-alert"
          type="error"
          showIcon
          message={error}
        />
      )}

      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={handleSubmit}
        className="auth-form"
      >
        <Form.Item
          label="用户名"
          name="username"
          rules={[
            { required: true, message: "请输入用户名" },
            { min: 2, max: 32, message: "用户名长度为 2-32 个字符" },
          ]}
        >
          <Input
            autoComplete="username"
            placeholder={mode === "login" ? "输入用户名" : "设置用户名"}
          />
        </Form.Item>

        {mode === "register" && (
          <Form.Item
            label="显示名称"
            name="display_name"
            rules={[{ max: 40, message: "显示名称不能超过 40 个字符" }]}
          >
            <Input
              autoComplete="name"
              placeholder="可选，例如：我的研究空间"
            />
          </Form.Item>
        )}

        <Form.Item
          label="密码"
          name="password"
          rules={[
            { required: true, message: "请输入密码" },
            { min: 8, max: 128, message: "密码长度为 8-128 个字符" },
          ]}
        >
          <Input.Password
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            placeholder={mode === "login" ? "输入密码" : "至少 8 个字符"}
          />
        </Form.Item>

        <Button
          type="primary"
          htmlType="submit"
          loading={busy}
          block
          size="large"
        >
          {mode === "login" ? "登录" : "创建并登录"}
        </Button>
      </Form>

      <p className="auth-footnote">
        账户仅保存在当前本地分析服务中，不会上传到外部平台。
      </p>
    </Modal>
  );
}
