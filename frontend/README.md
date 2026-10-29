# Video VLM Frontend

项目总说明见：[根 README](../README.md)。

基于 React、TypeScript、Zustand 与 Ant Design 的本地视频 VLM 分析前端。

第一版 P0 Demo 聚焦一个最小可运行闭环：

```text
选择本地视频
→ Upload multipart/form-data
→ 创建 VLM 分析任务
→ 每 2 秒轮询任务状态
→ 读取结构化场景结果
→ 视频与场景时间轴联动
```

> 当前版本不包含 EEG、WebSocket、实时视频流、跨模态融合、注意力评分或双屏对比功能。

---

## 1. 项目简介

本项目是“基于视频 VLM 与 EEG 的多模态学生学习状态分析系统”的前端初版。当前可执行部分是本地视频 VLM 学习场景分析；EEG 专注度解码、时间对齐和跨模态融合尚未接入。

分析完成后，页面展示：

- 视频文件基本信息；
- 上传进度；
- VLM 分析任务状态；
- 场景类别、开始时间、结束时间和置信度；
- 视频播放器；
- 场景时间轴；
- 当前视频播放位置对应的场景高亮；
- 点击时间轴色块跳转到对应视频时间。

P0 Demo 的目标是验证“视频上传 → VLM 分析 → 时间轴展示”的完整链路。项目通过本地 API 和后端通信，不依赖外部云服务。

---

## 2. 功能范围

### 已实现范围

- 本地视频文件选择与拖拽上传。
- Axios `multipart/form-data` 上传。
- 使用 Axios `onUploadProgress` 展示上传进度。
- 创建 VLM 分析任务。
- 每 2 秒进行一次 HTTP 任务状态轮询。
- 任务成功后自动读取视频分析结果。
- `queued`、`running` 等后端状态映射为前端四态。
- 场景时间轴渲染。
- 视频 `timeupdate` 事件监听。
- 根据当前播放时间高亮场景色块。
- 点击场景色块后执行视频 seek 和播放。
- 右上角本地账户登录、注册和退出入口。
- 登录后的个人分析历史抽屉，历史数据来自真实 Job 接口。
- 系统能力分区，明确标识当前可用能力与 EEG/融合后续能力。
- 错误、网络异常、空结果和重新分析状态展示。
- 前端独立 Mock 演示模式。
- TypeScript 严格模式。
- 生产构建与本地预览。

### 当前明确不包含

- EEG 数据接入。
- EEG 波形和专注度评分。
- WebSocket 或 SSE。
- 实时视频流或 `MediaStream`。
- 跨模态注意力融合。
- 多模态时间戳对齐。
- 细粒度角色权限、团队共享和完整的多用户 API 隔离。
- 评估页、混淆矩阵和人工标注管理。
- 云端对象存储。
- 公网数据上传。

---

## 3. 技术栈

| 技术 | 版本范围 | 用途 |
|---|---:|---|
| React | 18.x | 页面与组件 |
| TypeScript | 5.x | 类型约束 |
| Vite | 5.x | 本地开发与生产构建 |
| Zustand | 5.x | 轻量全局状态 |
| Ant Design | 5.x | 上传、进度、弹窗和页面组件 |
| Axios | 1.x | REST 请求、上传进度与错误处理 |

---

## 4. 业务流程

```mermaid
flowchart TD
    A[用户选择本地视频] --> B[Axios multipart 上传]
    B --> C[POST /videos/{video_id}/process]
    C --> D[获得 job_id]
    D --> E[每 2 秒 GET /jobs/{job_id}]
    E --> F{任务状态}
    F -->|queued / running| E
    F -->|completed| G[GET /videos/{video_id}]
    G --> H[标准化场景数组]
    H --> I[视频播放器与时间轴展示]
    F -->|failed / canceled| J[显示错误并停止轮询]
```

### 前端任务状态

前端只暴露四种业务状态：

```ts
type JobStatus =
  | "uploading"
  | "analyzing"
  | "success"
  | "error";
```

后端状态映射关系：

| 后端状态 | 前端状态 | 页面表现 |
|---|---|---|
| 上传请求进行中 | `uploading` | 上传进度条 |
| `queued` | `analyzing` | 等待后端处理 |
| `running` | `analyzing` | 正在抽帧分析 |
| `completed` | `success` | 展示分析结果 |
| `failed` | `error` | 展示错误 |
| `canceled` | `error` | 展示任务取消 |
| 网络或接口异常 | `error` | 停止轮询并提示 |

---

## 5. API 约定

### 5.1 环境变量

```env
VITE_API_BASE_URL=/api/v1
VITE_USE_MOCK=false
VITE_REQUEST_TIMEOUT_MS=30000
VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:8000
```

- `VITE_API_BASE_URL`：REST API 基础地址。
- `VITE_USE_MOCK`：设置为 `true` 时启用前端独立演示，不需要后端。
- `VITE_REQUEST_TIMEOUT_MS`：Axios 请求超时时间。
- `VITE_BACKEND_PROXY_TARGET`：Vite dev/preview 将 `/api` 和 `/health` 转发到的后端地址。

### 5.2 上传视频

```http
POST /api/v1/videos/upload
Content-Type: multipart/form-data
```

表单字段：

```text
file: <视频文件>
```

响应示例：

```json
{
  "video_id": "sav_20181016_05_1064",
  "name": "sample.mp4",
  "status": "registered",
  "size_bytes": 681715,
  "duration_s": 120.0,
  "file_url": "/api/v1/videos/sav_20181016_05_1064/file"
}
```

### 5.3 创建分析任务

```http
POST /api/v1/videos/{video_id}/process
```

响应示例：

```json
{
  "schema_version": "1.0",
  "job_id": "job-001",
  "video_id": "sav_20181016_05_1064",
  "job_type": "video_process",
  "status": "queued",
  "stage": "queued",
  "progress": 0.0,
  "result": null,
  "error": null
}
```

### 5.4 查询任务状态

```http
GET /api/v1/jobs/{job_id}
```

运行中示例：

```json
{
  "job_id": "job-001",
  "video_id": "sav_20181016_05_1064",
  "job_type": "video_process",
  "status": "running",
  "progress": 0.45,
  "result": null,
  "error": null
}
```

完成示例：

```json
{
  "job_id": "job-001",
  "video_id": "sav_20181016_05_1064",
  "job_type": "video_process",
  "status": "completed",
  "progress": 1.0,
  "result": {
    "provider": "minicpm_v",
    "segments": [
      {
        "start_s": 10.5,
        "end_s": 25.0,
        "scene_label": "听讲",
        "confidence": 0.95
      }
    ]
  },
  "error": null
}
```

### 5.5 查询视频结果

```http
GET /api/v1/videos/{video_id}
```

前端兼容以下结果位置：

```text
job.result.segments
video.segments
video.metadata.vlm_result.segments（兼容旧 Mock/旧数据）
```

统一转换为：

```ts
interface SceneSegment {
  start: number;
  end: number;
  scene: string;
  confidence: number | null;
}
```

最终业务数据格式：

```json
[
  {
    "start": 10.5,
    "end": 25.0,
    "scene": "听讲",
    "confidence": 0.95
  },
  {
    "start": 25.0,
    "end": 48.0,
    "scene": "小组讨论",
    "confidence": 0.88
  }
]
```

### 5.6 本地账户与个人历史

```text
POST /api/v1/auth/register  创建账户，成功返回 201 并设置会话 Cookie
POST /api/v1/auth/login     登录并设置会话 Cookie
POST /api/v1/auth/logout    撤销当前会话
GET  /api/v1/auth/me        查询当前登录状态
GET  /api/v1/history        查询当前用户的 Job 历史，未登录返回 401
```

会话令牌保存在 HttpOnly、SameSite=Lax Cookie 中。历史接口只返回 `jobs.user_id` 与当前用户一致的任务；升级前没有用户归属的匿名 Job 不会出现在个人历史中。未登录状态仍可继续上传、分析和查看当前结果。

---

## 6. 本地运行

### 6.1 环境要求

建议使用：

```text
Node.js >= 18
npm >= 9
```

检查版本：

```bash
node --version
npm --version
```

### 6.2 安装依赖

```bash
cd frontend
npm ci
```

如项目包含 `package-lock.json`，推荐使用：

```bash
npm ci
```

### 6.3 配置环境变量

```bash
cp .env.example .env.local
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env.local
```

默认配置：

```env
VITE_API_BASE_URL=/api/v1
VITE_USE_MOCK=false
VITE_REQUEST_TIMEOUT_MS=30000
VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:8000
```

### 6.4 启动前端

```bash
npm run dev
```

默认访问地址：

```text
http://127.0.0.1:5173
```

开发服务器会将以下路径代理到本地后端：

```text
/api  -> http://127.0.0.1:8000/api
/health -> http://127.0.0.1:8000/health
```

后端地址由 `VITE_BACKEND_PROXY_TARGET` 配置；缺省为 `http://127.0.0.1:8000`。dev 和 preview 使用同一代理配置。

### 6.5 后端启动要求

完整上传与分析流程需要本地后端提供：

- `/api/v1/videos/upload`
- `/api/v1/videos/{video_id}/process`
- `/api/v1/jobs/{job_id}`
- `/api/v1/videos/{video_id}`
- `/api/v1/videos/{video_id}/file`
- `/health`

后端文件响应应支持 HTTP Range，以便浏览器拖动视频进度。

### 6.6 无后端 Mock 模式

在 `.env.local` 中设置：

```env
VITE_USE_MOCK=true
```

重启开发服务器：

```bash
npm run dev
```

Mock 模式支持：

- 本地视频选择；
- 模拟上传进度；
- 模拟异步分析；
- 使用固定 VLM 场景数据；
- 视频与时间轴联动。

Mock 结果仅用于前端独立开发，不得作为真实模型预测用于实验汇报。

---

## 7. 生产构建

执行类型检查：

```bash
npm run typecheck
```

执行生产构建：

```bash
npm run build
```

本地预览构建产物：

```bash
npm run preview
```

构建结果位于：

```text
dist/
```

生产环境推荐由本地 Flask、FastAPI 或 Nginx 同源托管 `dist/`，并将 `/api` 反向代理到本地后端。
`npm run preview` 已配置 `/api` 和 `/health` 代理，可直接用于本地生产构建联调。

---

## 8. 核心交互说明

### 8.1 上传

- 仅接受 `video/*` 文件。
- 文件通过 `FormData` 和 Axios 上传。
- Axios `onUploadProgress` 计算上传百分比。
- 上传成功后保存 `video.id` 和 `video.file_url`。
- 上传失败显示可读错误，不继续创建分析任务。

### 8.2 HTTP 轮询

自定义 Hook：

```text
src/hooks/usePollingJob.ts
```

轮询规则：

1. 创建任务成功后读取 `job_id`。
2. 每隔 2 秒调用一次 `GET /jobs/{job_id}`。
3. 使用 `setTimeout` 串行调度，避免请求重叠。
4. `completed` 后立即停止轮询。
5. `failed` 或 `canceled` 后立即停止轮询。
6. 组件卸载或任务 ID 变化时清理定时器。
7. 使用 `disposed` 标记阻止卸载后的异步响应更新状态。

### 8.3 时间轴联动

组件：

```text
src/components/TimelineViewer.tsx
```

联动规则：

1. `<video>` 通过 `onTimeUpdate` 监听 `timeupdate` 事件。
2. 使用 `video.currentTime` 与场景数组比较。
3. 当前时间满足 `start <= currentTime < end` 时高亮对应场景。
4. 时间轴红色游标跟随视频播放位置。
5. 点击场景色块后设置 `video.currentTime = segment.start`。
6. 用户点击后调用 `video.play()`，实现跳转并继续播放。
7. 时间轴宽度按照视频总时长计算。
8. 场景色块使用百分比定位，支持响应式布局。

### 8.4 场景颜色

| 场景 | 颜色 |
|---|---|
| 听讲 | 蓝色 |
| 小组讨论 | 绿色 |
| 独立学习 | 橙色 |
| 其他或未分类 | 灰色 |

---

## 9. 目录结构

```text
frontend/
├── public/
│   └── favicon.svg
├── src/
│   ├── api/
│   │   ├── auth.ts
│   │   ├── client.ts
│   │   ├── history.ts
│   │   ├── mock.ts
│   │   └── videos.ts
│   ├── assets/
│   │   └── app-mark.svg
│   ├── components/
│   │   ├── AnalysisProgress.tsx
│   │   ├── AppHeader.tsx
│   │   ├── AuthModal.tsx
│   │   ├── HistoryDrawer.tsx
│   │   ├── TimelineViewer.tsx
│   │   └── VideoUpload.tsx
│   ├── hooks/
│   │   └── usePollingJob.ts
│   ├── mock/
│   │   └── vlmSegments.ts
│   ├── store/
│   │   ├── useAppStore.ts
│   │   └── useAuthStore.ts
│   ├── types/
│   │   └── index.ts
│   ├── utils/
│   │   ├── format.ts
│   │   └── sceneColors.ts
│   ├── App.tsx
│   ├── index.css
│   ├── main.tsx
│   └── vite-env.d.ts
├── .env.example
├── .gitignore
├── index.html
├── package.json
├── README.md
├── tsconfig.json
├── tsconfig.node.json
└── vite.config.ts
```

### 目录职责

| 目录 | 职责 |
|---|---|
| `api` | Axios 实例、REST 请求、Mock API |
| `assets` | 打包进应用的静态资源 |
| `components` | 上传、进度、视频时间轴等业务组件 |
| `hooks` | 任务轮询等可复用 React Hook |
| `mock` | 前后端联调使用的固定场景数据 |
| `store` | Zustand 全局状态 |
| `types` | P0 领域类型与后端接口类型 |
| `utils` | 时间格式化和场景配色等纯函数 |

---

## 10. 状态管理

```ts
interface AppStore {
  status: JobStatus | null;
  uploadProgress: number;
  analysisProgress: number;
  progressText: string;
  video: VideoRecord | null;
  videoUrl: string | null;
  jobId: string | null;
  segments: SceneSegment[];
  error: string | null;
}
```

状态职责：

- `status`：前端四态任务状态。
- `uploadProgress`：文件上传百分比。
- `analysisProgress`：VLM 分析百分比。
- `progressText`：后端阶段对应的可读文本。
- `video`：上传后的后端视频记录。
- `videoUrl`：视频预览地址。
- `jobId`：当前分析任务 ID。
- `segments`：标准化后的场景数组。
- `error`：错误信息。

项目中不包含：

- `EEGData`
- `AttentionScore`
- `MultiModalAlignedData`
- `MediaStream`
- WebSocket 连接实例
- 实时流缓冲队列
- 多模态对齐状态

---

## 11. 接口结果兼容性

后端字段可同时兼容 snake_case 和前端简化格式。

```ts
const start = Number(record.start ?? record.start_s);
const end = Number(record.end ?? record.end_s);
const scene = String(record.scene ?? record.scene_label ?? "其他");
```

该兼容逻辑集中位于：

```text
src/api/videos.ts
```

页面组件只消费标准化后的：

```ts
interface SceneSegment {
  start: number;
  end: number;
  scene: string;
  confidence: number | null;
}
```

---

## 12. 错误处理

覆盖以下错误：

- 未选择视频文件；
- 非视频文件；
- 上传请求失败；
- 本地后端不可达；
- 请求超时；
- VLM 分析失败；
- 任务取消；
- 任务成功但没有场景结果；
- 视频文件无法被浏览器播放；
- 视频元数据缺失。

轮询遇到不可恢复错误后立即停止定时器，并显示中文错误提示。

---

## 13. 验证清单

### 上传

- [ ] 可选择单个本地视频。
- [ ] 可拖拽上传。
- [ ] 非视频文件被拒绝。
- [ ] 上传过程中显示百分比。
- [ ] 上传完成后显示可开始分析。

### 轮询

- [ ] 创建任务后间隔 2 秒轮询。
- [ ] 不产生并行轮询请求。
- [ ] `queued/running` 持续轮询。
- [ ] `completed` 后停止轮询。
- [ ] `failed/canceled` 后停止轮询。
- [ ] 页面卸载时清理定时器。
- [ ] 任务完成后自动加载场景结果。

### 时间轴

- [ ] 视频播放时当前场景高亮。
- [ ] 时间轴游标跟随播放位置。
- [ ] 点击“听讲”色块跳转到开始时间。
- [ ] 点击“小组讨论”色块跳转到开始时间。
- [ ] 点击后播放继续。
- [ ] 场景空数组时显示空状态。
- [ ] 视频未上传时不渲染播放器。
- [ ] 视频加载失败时可见。
- [ ] 时间轴在较窄屏幕下仍可操作。

### 构建

- [ ] `npm install` 成功。
- [ ] `npm run typecheck` 成功。
- [ ] `npm run build` 成功。
- [ ] `npm run preview` 可访问。
- [ ] 无 TypeScript 编译错误。
- [ ] 无遗留 EEG、WebSocket 或 MediaStream 代码。

---

## 14. 隐私与离线说明

- 视频只发送到本地 `/api/v1/videos/upload`。
- 前端不调用外部 CDN、云模型或远程分析服务。
- 不采集浏览器指纹。
- 不上传 EEG 或个人生理数据。
- VLM 服务地址由本地后端管理。
- 生产构建可完全部署在本地主机。
- 页面刷新后会丢失当前页面操作状态；登录用户可在“分析历史”中查看已经完成并归属本人的 Job。
- 上传视频保存在本地后端配置的数据目录。

---

## 15. 已知限制

1. 当前只接受 MP4、M4V、MOV；不包含 WebM、AVI、MKV、SAV 或视频转码能力。
2. 当前活动上传和分析状态不做前端持久化；已完成的登录用户 Job 由后端保存并显示在历史抽屉。
3. 第一版不支持取消任务；是否取消由后端能力决定。
4. 分析百分比取决于后端 `progress` 字段；后端无法估算时可能长期显示阶段文本。
5. Mock 数据不代表真实模型准确率。
6. 本项目是前端工作成果，真实 VLM 推理由本地后端负责。
7. 当前 Vite 5 开发依赖的安全审计报告包含 1 个中危和 1 个高危项；可用的自动修复会升级到 Vite 8，属于后续独立依赖升级工作。开发服务器仅绑定 `127.0.0.1`。
8. 现有匿名 VLM 流程保持可用；账户和历史只对新建任务建立用户归属，旧的匿名 Job 不会出现在个人历史中。

---

## 16. 交付说明

本项目交付内容为：

- 独立前端工程；
- 完整 TypeScript 类型；
- Axios 接口封装；
- 2 秒 HTTP 轮询 Hook；
- 视频上传组件；
- 视频与时间轴联动组件；
- Zustand 状态管理；
- Mock VLM 场景数据；
- Vite 开发代理；
- 生产构建配置；
- 本 README。

接手人应先运行：

```bash
npm install
npm run typecheck
npm run dev
```

确认页面可打开后，再连接本地 VLM 后端进行完整流程联调。
