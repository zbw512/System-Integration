import { Button, Dropdown } from "antd";
import type { MenuProps } from "antd";
import type { AuthUser } from "../types";
import appMark from "../assets/app-mark.svg";

interface AppHeaderProps {
  user: AuthUser | null;
  busy: boolean;
  onLogin: () => void;
  onHistory: () => void;
  onLogout: () => void;
}

function getInitial(user: AuthUser): string {
  return (user.display_name || user.username).trim().slice(0, 1).toUpperCase();
}

export function AppHeader({
  user,
  busy,
  onLogin,
  onHistory,
  onLogout,
}: AppHeaderProps) {
  const menuItems: MenuProps["items"] = [
    {
      key: "account",
      label: (
        <div className="account-summary">
          <strong>{user?.display_name}</strong>
          <span>@{user?.username}</span>
        </div>
      ),
      disabled: true,
    },
    { type: "divider" },
    {
      key: "history",
      label: "分析历史",
    },
    {
      key: "logout",
      label: "退出登录",
      danger: true,
      disabled: busy,
    },
  ];

  const handleMenuClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "history") {
      onHistory();
    }
    if (key === "logout") {
      onLogout();
    }
  };

  return (
    <header className="site-header">
      <div className="header-inner">
        <a className="brand" href="/" aria-label="学生学习过程分析首页">
          <img src={appMark} alt="" />
          <span className="brand-copy">
            <strong>学习过程分析</strong>
            <span>Video VLM · EEG</span>
          </span>
        </a>

        <div className="header-actions">
          <span className="local-state">
            <span aria-hidden="true" />
            本地处理
          </span>

          {user ? (
            <Dropdown
              trigger={["click"]}
              menu={{ items: menuItems, onClick: handleMenuClick }}
              placement="bottomRight"
            >
              <button
                className="account-button"
                type="button"
                aria-label={`账户菜单：${user.display_name}`}
              >
                <span className="account-avatar">{getInitial(user)}</span>
                <span className="account-name">{user.display_name}</span>
              </button>
            </Dropdown>
          ) : (
            <Button
              className="login-button"
              type="text"
              loading={busy}
              onClick={onLogin}
            >
              登录
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
