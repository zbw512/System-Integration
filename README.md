# 学生学习状态分析系统
本项目包含一个 React 视频分析前端和一个 Flask 分析后端，当前围绕本地短视频完成：

```text
视频上传 -> 创建异步任务 -> 2 秒 HTTP 轮询 -> 场景结果 -> 视频时间轴联动
```

后端支持浏览器内 Mock 适配器和真实 MiniCPM-V 4.6 适配器。默认使用 Mock，且所有 Mock 结果均明确标记为模拟数据。

> 本 README 以当前项目根目录为基准。后续调整根目录名称时，不需要修改其中的相对路径。

详细子模块文档：

- [前端说明](frontend/README.md)
- [后端说明](backend/README.md)

## 当前能力

已实现：

- MP4、M4V、MOV 视频上传及受控文件访问；
- 本地文件登记和视频列表；
- 持久化分析任务及单线程后台队列；
- 任务进度、状态和结构化错误；
- 场景 Segment 结果；
- JSON/CSV 结果导出；
- 前端上传进度、轮询、视频播放器和场景时间轴；
- 前端独立 Mock 模式；
- 可选的真实 MiniCPM-V 4.6 离线逐帧分类。

尚未实现：

- EEG 数据接入；
- 评估指标和混淆矩阵；
- 跨模态融合；
- WebSocket/SSE、实时视频流；
- 任务取消；
- CPU 推理；
- 视频转码；
- 用户、权限和多用户隔离。

## 技术栈

| 模块 | 技术 |
|---|---|
| 前端 | React 18、TypeScript、Vite 5、Zustand、Ant Design、Axios |
| 后端 | Python 3.12、Flask 3.1、标准库 SQLite、PyAV |
| 真实 VLM | MiniCPM-V 4.6、PyTorch、Transformers、CUDA |
| 持久化 | SQLite WAL |

依赖入口：

- 前端：`frontend/package.json` + `frontend/package-lock.json`
- 后端：`backend/requirements.txt`

## 项目结构

```text
<project-root>/
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── mock/
│   │   ├── store/
│   │   ├── types/
│   │   └── utils/
│   ├── .env.example
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   └── README.md
├── backend/
│   ├── adapters/vlm/
│   ├── api/
│   ├── schemas/
│   ├── services/
│   ├── storage/
│   ├── tests/
│   ├── app.py
│   ├── config.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── README.md
│   └── var/                 # 运行期生成，Git 忽略
├── models/                  # 可选本地模型目录，Git 忽略
├── .gitignore
└── README.md
```

职责：

| 路径 | 职责 |
|---|---|
| `frontend/` | 页面、用户交互、上传、轮询、API 响应适配、视频播放器、时间轴和前端 Mock |
| `backend/` | Flask API、视频校验与受控存储、SQLite、Job 状态机、单线程队列、VLM 适配器和导出 |
| `models/` | 可选本地模型资产目录；实际路径可由环境变量指向仓库外 |
| `backend/var/` | 运行期 SQLite 和视频，默认由后端创建并被 Git 忽略 |
| 根 `README.md` | 新成员入口、启动、接口、数据、测试、限制和排障 |

## 运行要求

| 项 | 当前要求/验证值 |
|---|---|
| Node.js | `>=18`；2026-10-28 使用 v24.22.1 |
| npm | `>=9`；2026-10-28 使用 v11.19.1 |
| Python | 3.12；2026-10-28 使用 3.12.7 |
| 后端基础环境 | `backend/.venv` |
| GPU | 仅真实 MiniCPM-V 模式需要，当前未验证 |
| SQLite | 使用 Python 标准库，不需要独立服务 |

## 快速启动

### 1. 后端虚拟环境

```powershell
cd <project-root>\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

当前 `requirements.txt` 已覆盖 Mock/API 和视频解码直接依赖，包括 Flask、pytest、Pillow、numpy 和 PyAV。

真实 MiniCPM-V 还需要另行准备：

- CUDA 可用的 PyTorch/torchvision；
- 兼容的 Transformers；
- 本地 MiniCPM-V 4.6 权重；
- 足够显存。

这些大型依赖没有放入通用 `requirements.txt`，避免覆盖已经验证的 GPU 环境。

### 2. 启动后端

```powershell
cd <project-root>\backend
$env:BACKEND_VLM_ADAPTER = "mock"
.\.venv\Scripts\python.exe app.py
```

默认地址：

```text
http://127.0.0.1:8000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

后端默认在 `backend/var/` 创建：

```text
app.db
videos/
```

### 3. 启动前端

首次配置：

```powershell
cd <project-root>\frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

默认地址：

```text
http://127.0.0.1:5173
```

前端通过同源代理访问后端：

```text
/api    -> http://127.0.0.1:8000/api
/health -> http://127.0.0.1:8000/health
```

代理目标可由 `VITE_BACKEND_PROXY_TARGET` 修改。dev 和 preview 使用同一代理。

### 4. 前端环境变量

```env
VITE_API_BASE_URL=/api/v1
VITE_USE_MOCK=false
VITE_REQUEST_TIMEOUT_MS=30000
VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:8000
```

- `VITE_USE_MOCK=false`：调用 Flask；
- `VITE_USE_MOCK=true`：不启动后端，使用浏览器内 Mock；
- 修改环境变量后必须重启 Vite。

## 后端环境变量

后端只读取进程环境变量，不自动加载 `.env` 文件。参考模板为 `backend/.env.example`。

PowerShell 示例：

```powershell
$env:BACKEND_HOST = "127.0.0.1"
$env:BACKEND_PORT = "8000"
$env:BACKEND_DATA_DIR = ""
$env:BACKEND_JOB_WORKER = "true"
$env:BACKEND_VLM_ADAPTER = "mock"
$env:BACKEND_VLM_DEVICE = "cuda"
```

完整变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `BACKEND_HOST` | `127.0.0.1` | 监听地址 |
| `BACKEND_PORT` | `8000` | 监听端口 |
| `BACKEND_ENV` | `development` | 环境标识 |
| `BACKEND_DEBUG` | `false` | Flask 调试模式 |
| `BACKEND_LOG_LEVEL` | `INFO` | 日志等级 |
| `BACKEND_LOG_FILE` | 空 | 可选日志文件 |
| `BACKEND_MAX_UPLOAD_MB` | `512` | 上传/导入上限 |
| `BACKEND_DATA_DIR` | `backend/var` | SQLite 和视频数据目录 |
| `BACKEND_DB_PATH` | `<data_dir>/app.db` | 可选显式数据库路径 |
| `BACKEND_VIDEO_SUBDIR` | `videos` | 视频子目录 |
| `BACKEND_IMPORT_ROOTS` | 空 | `register` 可读取的额外根目录，`;` 分隔 |
| `BACKEND_JOB_WORKER` | `true` | 是否启动后台 Job 线程 |
| `BACKEND_VLM_ADAPTER` | `mock` | `mock` 或 `minicpm` |
| `BACKEND_VLM_MODEL_PATH` | `<root>/models/MiniCPM-V-4.6` | 真实模型目录 |
| `BACKEND_VLM_DEVICE` | `cuda` | 当前只实现 CUDA |
| `BACKEND_VLM_MAX_FRAMES` | `8` | 每任务最多采样帧，1–64 |
| `BACKEND_VLM_FRAME_INTERVAL_S` | `1.0` | 采样间隔，必须大于 0 |
| `BACKEND_VLM_MAX_DURATION_S` | `60.0` | 单任务素材上限 |
| `BACKEND_VLM_MAX_NEW_TOKENS` | `48` | 每帧生成上限 |
| `BACKEND_TESTING` | `false` | pytest 专用 |

真实模型示例：

```powershell
$env:BACKEND_VLM_ADAPTER = "minicpm"
$env:BACKEND_VLM_MODEL_PATH = "<confirmed-absolute-model-directory>"
$env:BACKEND_VLM_DEVICE = "cuda"
```

默认模型路径为：

```text
<project-root>\models\MiniCPM-V-4.6
```

路径存在不代表权重完整；真实模型测试前必须同时确认 `config.json`、模型权重、CUDA 和 Transformers 兼容性。

## 核心 API

基础前缀：`/api/v1`

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/info` | 服务能力和接口信息 |
| POST | `/api/v1/videos/upload` | multipart 上传，字段 `file` |
| POST | `/api/v1/videos/register` | 登记允许目录内视频 |
| GET | `/api/v1/videos` | 视频列表 |
| GET | `/api/v1/videos/{video_id}` | 视频详情 |
| GET | `/api/v1/videos/{video_id}/file` | 视频文件，支持 Range |
| POST | `/api/v1/videos/{video_id}/process` | 创建分析任务，返回 202 |
| GET | `/api/v1/jobs` | 任务列表 |
| GET | `/api/v1/jobs/{job_id}` | 任务详情 |
| GET | `/api/v1/videos/{video_id}/results?format=json\|csv` | 查询或导出结果 |

上传：

```http
POST /api/v1/videos/upload
Content-Type: multipart/form-data
file=<视频>
```

成功返回 201。关键字段：

```text
video_id, name, source, status, duration_s, size_bytes,
created_at, file_url, prediction_source, segments, metadata
```

创建分析任务：

```http
POST /api/v1/videos/{video_id}/process
```

成功返回 202。响应顶层直接包含：

```text
job_id, video_id, job_type, status, stage, progress,
created_at, started_at, finished_at, result, error, provider, model, metadata
```

任务详情：

```http
GET /api/v1/jobs/{job_id}
```

前端每 2 秒轮询。完成时 `status=completed`、`progress=1`、`stage=done`；失败时 `result=null`，`error` 为对象。

### 关键契约

- 视频主键：`video_id`
- 任务主键：`job_id`
- 创建任务直接返回扁平 Job，不再包一层 `job`
- Job `progress` 范围：0–1
- Job `status`：`queued/running/completed/failed/canceled`
- Job `error` 是对象：`code/message/retryable/details?`
- Segment 使用 `start_s/end_s/scene_label/confidence`
- 真实模型的 `confidence` 可以为 `null`

HTTP 错误统一为：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数不合法",
    "details": {},
    "request_id": "...",
    "retryable": false,
    "timestamp": "2026-10-28T00:00:00Z"
  }
}
```

## 前后端数据流

```text
VideoUpload
  -> POST /videos/upload
  -> video_id + file_url

App
  -> POST /videos/{video_id}/process
  -> job_id

usePollingJob
  -> GET /jobs/{job_id} 每 2 秒
  -> completed
  -> GET /videos/{video_id}
  -> job.result.segments / video.segments

TimelineViewer
  -> GET /videos/{video_id}/file
  -> 场景高亮、视频 seek
```

Job 状态机：

```text
queued -> running -> completed
                  -> failed
```

- `canceled` 属于契约枚举，但当前没有取消接口；
- 同一视频同一时刻只能有一个 queued/running Job；
- 重复提交返回 409 `JOB_ALREADY_RUNNING`；
- 服务重启会把中断的 queued/running Job 标记为 failed。

## 数据模型与持久化

### Video

```text
video_id, name, source, status, duration_s, size_bytes, created_at,
file_url, prediction_source, provider, evaluation_eligible,
model, segments, metadata
```

状态：

```text
registered -> processing -> processed
                         -> failed
```

### Job

```text
job_id, job_type, status, stage, progress, video_id,
created_at, started_at, finished_at, result, error,
provider, model, metadata
```

### Segment

```text
index, start_s, end_s, scene_label,
confidence, evidence, is_uncertain
```

`confidence` 允许为 `null`，前端显示“未提供”。

### SQLite

`backend/var/app.db` 包含：

- `videos` 表：视频元数据、当前分析来源、Segment JSON、模型和评价资格；
- `jobs` 表：任务状态、阶段、进度、结果/错误 JSON 和模型信息。

数据库使用 WAL。视频文件在 `backend/var/videos/`，API 不暴露存储绝对路径。

## Mock 与真实模型

### 后端 Mock

```powershell
$env:BACKEND_VLM_ADAPTER = "mock"
```

- 不加载模型；
- 不抽帧；
- 根据视频时长生成最多 3 个合法模拟分段；
- `prediction_source=mock`；
- `is_mock=true`；
- `evaluation_eligible=false`。

### 前端 Mock

```env
VITE_USE_MOCK=true
```

- 使用浏览器内 Blob URL 和内存任务；
- 刷新页面后数据丢失；
- 不访问 Flask；
- 固定场景数据不能作为模型评估结果。

### 真实 MiniCPM-V

```powershell
$env:BACKEND_VLM_ADAPTER = "minicpm"
$env:BACKEND_VLM_MODEL_PATH = "<confirmed-model-path>"
```

真实模式失败不会回退到 Mock。当前实现是逐帧分类，分段边界来自采样时间，不是视频级模型检测到的精确场景切换点。

## 本地视频格式

前端预检和后端上传规则一致：

```text
.mp4
.m4v
.mov
```

后端还要求文件内容符合 ISO-BMFF `ftyp`。浏览器能否播放取决于内部编码；当前没有转码服务。

## 测试与构建

后端：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe -m pytest -v
```

2026-10-28 在新建隔离环境中的结果：

```text
277 passed, 1 skipped
```

跳过项是 opt-in 的真实模型测试。本轮未加载真实模型。

前端：

```powershell
cd <project-root>\frontend
npm run typecheck
npm run build
```

当前 TypeScript 检查和生产构建通过。

2026-10-28 端到端验收还确认：

- 可播放 H.264 视频上传、分析、播放和时间轴跳转；
- 文件 Range 返回 206；
- JSON/CSV 导出一致，CSV 带 UTF-8 BOM；
- 重复 Job 返回 409；
- 后端重启后视频与 Job 仍可查询；
- Vite dev 和 preview 的 `/api`、`/health` 代理；
- 前端独立 Mock 显示 5 个固定场景；
- 模型缺失时页面显示结构化错误消息。

当前没有前端自动化测试脚本，`npm test` 会报 `Missing script: "test"`。

## 生产预览和部署

```powershell
cd <project-root>\frontend
npm run build
npm run preview
```

预览地址：

```text
http://127.0.0.1:4173
```

Vite preview 已代理 `/api` 和 `/health`。正式部署建议将前端静态文件与 Flask API 放在同一源后，由反向代理转发 `/api`；当前没有启用 CORS。

## 已知限制

1. 后端是单进程单线程队列，不适合多进程直接扩展。
2. 服务重启时活动任务会被标记失败，不会自动续跑。
3. 没有任务取消。
4. 重新分析会清除旧结果。
5. 真实模型仅支持 CUDA，目前没有 CPU 回退。
6. 真实模型置信度为 `null`，前端显示“未提供”。
7. 上传上限默认 512 MB，真实 VLM 采样上限默认 8 帧/60 秒。
8. EEG、融合、评价指标和实时流未实现。
9. 当前 `.venv` 只验证了 Mock/API 和 PyAV 解码依赖；GPU 模型环境仍需单独验收。
10. `npm audit` 当前报告 Vite/esbuild 开发依赖存在 1 个中危和 1 个高危项；自动修复要求 Vite 大版本升级，尚未在本轮执行。开发服务器仅绑定 `127.0.0.1`。
11. 异步 Job 错误展示 `message`，页面同时显示 `job_id`，但当前 Job error 不携带创建请求的 `request_id`。
12. Ant Design 静态 `message` API 会在浏览器控制台产生一条上下文警告，不影响当前操作。

## 常见问题

### 前端请求 404

确认 Flask 正在 `127.0.0.1:8000` 运行，并检查 `VITE_BACKEND_PROXY_TARGET`。

### 页面一直停在 queued

检查 `BACKEND_JOB_WORKER=true`，并查看后端日志。

### 后端提示 VIDEO_NOT_PROCESSED

视频存在，但分析未完成、失败或尚无结果。查询对应 Job 的 `error` 和 `state`。

### 真实模型提示 VLM_MODEL_NOT_FOUND

检查：

- `BACKEND_VLM_MODEL_PATH`；
- `config.json`；
- `model*.safetensors`；
- CUDA 与 torch/transformers 环境。

### npm 或 Python 依赖不一致

前端优先使用 `npm ci`；后端建议使用独立的 `backend/.venv`，不要混装多个项目的推理依赖。

## 新成员首次运行检查清单

- [ ] 已从仓库根进入 `backend/`；
- [ ] 已创建或使用 `backend/.venv`；
- [ ] `pip check` 无损坏依赖；
- [ ] `$env:BACKEND_VLM_ADAPTER` 明确设为 `mock`；
- [ ] 后端 `/health` 返回 `status=ok`；
- [ ] 已从 `frontend/.env.example` 创建 `.env.local`；
- [ ] `.env.local` 中的 `VITE_USE_MOCK=false`；
- [ ] `npm ci` 成功；
- [ ] 前端页面可以在 5173 打开；
- [ ] 上传一个真实可解码的短视频；
- [ ] 创建任务后页面轮询到完成并显示时间轴；
- [ ] 视频可播放且点击时间轴可以 seek；
- [ ] 已阅读当前限制，不把 Mock 结果作为模型评估结果。

## 后续方向

EEG 接入、评估指标、跨模态融合、实时流和任务取消仍属于后续工作。它们当前没有可用接口，不能按现有 README 推断为已经实现。

