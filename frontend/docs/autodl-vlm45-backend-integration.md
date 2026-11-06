# Flask 接入 AutoDL MiniCPM-V 4.5

本文记录现有 Flask 后端如何调用 AutoDL 独立推理服务。前端、SQLite Schema、Job 状态机和 Segment 核心字段保持不变。

## 1. 调用流程

```text
React 上传视频
  -> Flask 创建 video_process Job
  -> JobRunner 串行执行
  -> MiniCPMV45RemoteAdapter
  -> PyAV 顺序解码完整视频一次
  -> 按 3 秒窗口、3 秒步长分组
  -> 每窗口按负责人公式选择最多 8 帧
  -> 无损 PNG + Base64
  -> POST http://127.0.0.1:18080/predict_window
  -> SSH 隧道
  -> AutoDL FastAPI
  -> 一次 model.chat() 处理 8 帧
  -> 返回 raw_prediction
  -> Flask 本地解析四分类
  -> 一窗口一个 Segment
  -> Job/Video 事务保存
  -> 前端轮询并显示时间轴
```

## 2. 窗口策略

- 窗口长度：3 秒。
- 窗口步长：3 秒。
- 不重叠。
- 不足 3 秒且含有效画面的尾部保留为短窗口。
- 一个窗口的所有帧按时间顺序放在同一个 `model.chat()` 请求中。
- 窗口内不足或等于 8 帧时全部使用。
- 多于 8 帧时使用负责人公式：

```text
indices[i] = round(i * (frame_count - 1) / 7)
i = 0..7
```

- 相邻窗口即使标签相同也不合并，以保留“一窗口一预测”的追溯关系。

原始训练视频构造和 ms-swift 视频加载源码未提供。因此 3 秒/3 秒策略在结果元数据中标记为 `provisional`，不能描述为已经与训练阶段逐字节一致。

## 3. 环境变量

先设置与 AutoDL 完全一致的 Token：

```powershell
$env:VLM_SERVICE_TOKEN = "<AutoDL 服务 Token>"
```

启动 Flask 前设置：

```powershell
$env:BACKEND_VLM_ADAPTER = "minicpm_remote"
$env:BACKEND_VLM_REMOTE_URL = "http://127.0.0.1:18080"
$env:BACKEND_VLM_REMOTE_TOKEN = $env:VLM_SERVICE_TOKEN
$env:BACKEND_VLM_REMOTE_TIMEOUT_S = "300"
$env:BACKEND_VLM_REMOTE_RETRIES = "2"
$env:BACKEND_VLM_REMOTE_MAX_RESPONSE_BYTES = "1048576"
$env:BACKEND_VLM_MAX_FRAMES = "8"
$env:BACKEND_VLM_WINDOW_SECONDS = "3"
$env:BACKEND_VLM_WINDOW_STRIDE_SECONDS = "3"
$env:BACKEND_VLM_MAX_DURATION_S = "60"
```

`BACKEND_VLM_ADAPTER` 可选值：

| 值 | 用途 |
|---|---|
| `mock` | 默认开发模式，不调用网络或模型 |
| `minicpm_remote` | 正式 AutoDL MiniCPM-V 4.5 + LoRA |
| `minicpm_v45_lora` | 与 `minicpm_remote` 完全相同的别名 |
| `minicpm` | 历史本地 MiniCPM-V 4.6，仅保留兼容 |

## 4. 打开 SSH 隧道

先按照 [`AUTODL_DEPLOYMENT.md`](../AUTODL_DEPLOYMENT.md) 填写
`scripts/autodl.connection.psd1` 和 `scripts/autodl.secrets.psd1`，然后运行：

```powershell
cd E:\dachuang\System-Intergration
.\scripts\start_autodl_tunnel.ps1
```

停止和检查：

```powershell
.\scripts\stop_autodl_tunnel.ps1
.\scripts\check_autodl_connection.ps1
```

配置驱动脚本会使用本地配置中的主机、端口和密钥，不再要求硬编码 SSH 地址。

## 5. 启动 Flask

```powershell
cd E:\dachuang\System-Intergration\backend
.\.venv\Scripts\python.exe app.py
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/info |
  Select-Object -ExpandProperty adapters |
  Select-Object -ExpandProperty vlm
```

应看到 `name=minicpm_remote`、`model.version=4.5`、`checkpoint=checkpoint-600`。

## 6. 单窗口预检

```powershell
$env:VLM_SERVICE_TOKEN = "<同一个 Token>"
.\scripts\test_single_window.ps1 `
  -Video "E:\dachuang\SAV\dataset\20181016_05_1064.mp4" `
  -StartS 0 `
  -EndS 3
```

该脚本从视频窗口内按同一规则选择最多 8 帧，经隧道调用 `/predict_window`。

## 7. 完整上传测试

1. 确认 AutoDL `/health` 返回 200 且 `loaded=true`。
2. 保持 SSH 隧道运行。
3. 用上面的远程环境变量启动 Flask。
4. 启动现有 React 前端。
5. 上传 3 秒、6 秒或 9 秒视频。
6. 前端创建 Job 并每 2 秒轮询。
7. Job 完成后确认时间轴出现对应 1、2 或 3 个 Segment。
8. 检查 `GET /api/v1/videos/{video_id}/results?format=json` 和 `format=csv`。

## 8. Mock 和真实结果区分

| 字段 | Mock | AutoDL 真实模型 |
|---|---|---|
| `prediction_source` | `mock` | `model` |
| `provider` | `mock_vlm` | `minicpm_v` |
| `is_mock` | `true` | `false` |
| `model.version` | `0.1.0-mock` | `4.5` |
| `model.checkpoint` | 无 | `checkpoint-600` |
| `evaluation_eligible` | `false` | `true` |

真实模式网络或模型失败时 Job 直接 `failed`，不会产生 Segment，也不会回退 Mock。

## 9. 错误分类

| code | 含义 |
|---|---|
| `VLM_REMOTE_NOT_CONFIGURED` | URL 或 Token 配置缺失 |
| `VLM_REMOTE_UNAVAILABLE` | SSH 隧道断开、连接失败或重试耗尽 |
| `VLM_REMOTE_AUTH_FAILED` | 云端 Token 不一致 |
| `VLM_REMOTE_REQUEST_REJECTED` | 云端拒绝请求，例如图片或字段不合法 |
| `VLM_REMOTE_INFERENCE_FAILED` | 云端模型/OOM/生成异常 |
| `VLM_RESULT_INVALID` | 云端响应结构、模型版本或帧数不合法 |

模型成功生成但文本不属于四分类时，不是 Job 失败：该窗口保存为 `scene_label=未分类`、`is_uncertain=true`。
