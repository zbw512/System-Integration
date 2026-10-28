# 学生学习状态分析系统 — 后端（backend/）

项目总说明见：[根 README](../README.md)。

基于 Flask 的后端服务，面向「视频 VLM + EEG 多模态学习状态分析」项目。
接口契约以《前后端接口与数据标准 v1》为准。

> **当前阶段：P0-5（真实 MiniCPM-V 4.6 离线视频分析适配器）**
>
> 已完成：应用骨架、健康检查、服务信息、统一错误响应、配置、日志、SQLite 持久化、
> 视频上传/登记/列表/详情/受控文件访问、分析任务创建（202）/ 任务查询 / Job 状态机 /
> 单线程后台执行、结果查询与 JSON/CSV 导出、
> **真实 MiniCPM-V 4.6 适配器（按需加载、逐帧分类、显式边界）**。
>
> **未完成**：SAV 批量处理与评价指标（仍缺人工标注）、EEG、跨模态融合、实时流。
> 默认 `BACKEND_VLM_ADAPTER=mock`；只有切到 `minicpm` 才会加载本地权重。
> Mock 结果始终标记 `prediction_source=mock`，不会被当作真实模型预测。


---

## 1. 环境要求

| 项 | 值（本机实测） |
|---|---|
| 操作系统 | Windows |
| Python | 3.12.7（建议项目内 `backend/.venv`） |
| Flask | 3.1.3 |
| pytest | 9.1.1 |
| 持久化 | SQLite（标准库 `sqlite3`，本机 3.45.3） |
| 端口 | 8000（接口标准约定 `http://127.0.0.1:8000`） |

本文使用项目内虚拟环境；不同机器可换成自己的 Python 3.12 环境：

```text
backend\.venv\Scripts\python.exe
```

> 默认 Mock 模式不需要 GPU、PyTorch、Transformers 或模型权重。
> 上传阶段只用纯 Python 解析 ISO-BMFF `mvhd`；真实 VLM 模式使用 PyAV 解码视频，
> 并在首次任务中加载本地 MiniCPM-V 权重。

---

## 2. 安装依赖

```powershell
cd <project-root>\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 当前显式声明的直接依赖：

```text
Flask       3.1.3
pytest      9.1.1
Pillow      10.4.0
numpy       1.26.4
av          19.0.2
```

真实 VLM 还需要与主机 CUDA 匹配的 torch/torchvision/transformers。
这些包没有固定在基础依赖中，必须使用已经验证过的 GPU 环境。
不要执行其他目录中的 `inference/requirements.txt` 覆盖当前环境。

后端不会自动读取 `.env`。请按 PowerShell 设置进程环境变量：

```powershell
$env:BACKEND_VLM_ADAPTER = "mock"
$env:BACKEND_DATA_DIR = "<optional-absolute-data-dir>"
```

---

## 3. 启动服务

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe app.py
```

启动时自动创建数据目录、执行 SQLite 建表（含 `jobs` 表）并拉起**单个**后台任务线程：

```text
backend/var/
├── app.db            SQLite 元数据（videos、jobs）
├── app.db-wal        WAL 日志
└── videos/           上传/登记的视频文件
```

---

## 4. 接口

统一前缀 `/api/v1`，列表统一 `items` + `pagination`，错误统一（见 §6）。

### 4.1 端点一览

| 方法 | 路径 | 作用 | 成功状态 |
|---|---|---|---|
| GET | `/health` | 健康检查 | 200 |
| GET | `/api/v1/info` | 服务与接口说明（能力矩阵、适配器、枚举、Job 策略） | 200 |
| POST | `/api/v1/videos/upload` | 上传视频（`multipart/form-data`，字段 `file`） | 201 |
| POST | `/api/v1/videos/register` | 登记导入目录内的视频 | 201 |
| GET | `/api/v1/videos` | 视频列表 | 200 |
| GET | `/api/v1/videos/{video_id}` | 视频详情 | 200 |
| GET | `/api/v1/videos/{video_id}/file` | 受控文件访问（支持 `Range`） | 200 / 206 |
| **POST** | **`/api/v1/videos/{video_id}/process`** | **创建分析任务** | **202** |
| **GET** | **`/api/v1/jobs`** | **任务列表** | **200** |
| **GET** | **`/api/v1/jobs/{job_id}`** | **任务详情** | **200** |
| **GET** | **`/api/v1/videos/{video_id}/results`** | **查询/导出已保存的分析结果（`format=json\|csv`）** | **200 / 200(CSV)** |

### 4.2 视频接口（P0-2，未变）

上传、登记、列表、详情、文件访问的行为与限制见 P0-2 说明，本轮未改动其语义：

- 上传校验：扩展名（`.mp4`/`.m4v`/`.mov`）+ 容器签名（偏移 4 处 `ftyp`）+ 非空 + 大小上限；
- 登记：只允许读取 `BACKEND_IMPORT_ROOTS`（或数据目录）内的文件，并**复制**入库；
- 文件访问：路径 containment 校验，支持 `Range`（`206`）。

### 4.3 `POST /api/v1/videos/{video_id}/process` — 创建分析任务

请求：无请求体。

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/videos/vid_abc123/process
```

响应：**202 Accepted**（本机实测，仅摘录关键字段）

```json
{
  "schema_version": "1.0",
  "job_id": "job_7c91cdd9ee32",
  "job_type": "video_process",
  "status": "queued",
  "stage": "queued",
  "progress": 0.0,
  "video_id": "vid_af59faab03da",
  "created_at": "2026-10-22T09:20:11Z",
  "started_at": null,
  "finished_at": null,
  "result": null,
  "error": null,
  "provider": null,
  "model": null,
  "metadata": { "requested_from": "api" }
}
```

响应头含 `Location: /api/v1/jobs/{job_id}`。

**立即返回 202**：请求只创建持久化任务记录并入队，不等待分析完成。

错误：

| HTTP | code | 场景 |
|---:|---|---|
| 404 | `VIDEO_NOT_FOUND` | `video_id` 不存在 |
| 409 | `JOB_ALREADY_RUNNING` | 该视频已有 `queued`/`running` 任务（`details` 含已有 `job_id`） |

### 4.4 `GET /api/v1/jobs`

| 参数 | 默认 | 约束 |
|---|---|---|
| `limit` | 50 | 1–500，越界/非整数 → `400 VALIDATION_ERROR` |
| `offset` | 0 | ≥ 0 |
| `status` | — | `queued`/`running`/`completed`/`failed`/`canceled` |
| `video_id` | — | 精确匹配 |
| `job_type` | — | `video_process`/`evaluation`/`fusion`/`export` |

```json
{
  "items": [ { "job_id": "job_7c91cdd9ee32", "status": "completed", "...": "..." } ],
  "pagination": { "limit": 50, "offset": 0, "total": 3, "has_next": false },
  "jobs": [ "标准 §1.4 规定的过渡别名，内容与 items 相同" ]
}
```

### 4.5 `GET /api/v1/jobs/{job_id}`

返回单个 `Job`；不存在 → `404 JOB_NOT_FOUND`。

### 4.6 完成后的 `Job` 示例（本机实测）

```json
{
  "job_id": "job_7c91cdd9ee32",
  "status": "completed",
  "stage": "done",
  "progress": 1.0,
  "started_at": "2026-10-22T09:20:11Z",
  "finished_at": "2026-10-22T09:20:11Z",
  "error": null,
  "provider": "mock_vlm",
  "model": { "name": "mock-vlm", "version": "0.1.0-mock", "prompt_version": "mock-scene-v1" },
  "result": {
    "video_id": "vid_af59faab03da",
    "prediction_source": "mock",
    "provider": "mock_vlm",
    "model": { "name": "mock-vlm", "version": "0.1.0-mock", "prompt_version": "mock-scene-v1" },
    "segments": [
      { "index": 0, "start_s": 0.0, "end_s": 1.0, "scene_label": "听讲",      "confidence": 0.55, "evidence": "Mock 适配器生成的占位判断依据，不代表真实模型输出", "is_uncertain": false },
      { "index": 1, "start_s": 1.0, "end_s": 2.0, "scene_label": "小组讨论",   "confidence": 0.65, "evidence": "…", "is_uncertain": false },
      { "index": 2, "start_s": 2.0, "end_s": 3.0, "scene_label": "独立学习",   "confidence": 0.75, "evidence": "…", "is_uncertain": false }
    ],
    "segment_count": 3,
    "is_mock": true
  }
}
```

失败任务示例：

```json
{
  "status": "failed",
  "result": null,
  "error": { "code": "VLM_UPSTREAM_ERROR", "message": "无法从视频容器解析时长，Mock 适配器不会伪造时间段", "retryable": true }
}
```

---

### 4.7 `GET /api/v1/videos/{video_id}/results` — 结果查询与导出

| 参数 | 默认 | 允许值 |
|---|---|---|
| `format` | `json` | `json`、`csv`（大小写不敏感） |

**数据来源**：只读 `videos` 表中已保存的分析结果。导出**不会**触发分析、**不会**创建任务、
**不会**重新生成模拟分段；JSON 与 CSV 来自**同一行**数据。

#### JSON（200）

```json
{
  "schema_version": "1.0",
  "video_id": "vid_5bf8f1443db1",
  "name": "export_clip.mp4",
  "source": "upload",
  "status": "processed",
  "duration_s": 3.0,
  "size_bytes": 148,
  "created_at": "2026-10-24T07:52:13Z",
  "file_url": "/api/v1/videos/vid_5bf8f1443db1/file",
  "prediction_source": "mock",
  "provider": "mock_vlm",
  "evaluation_eligible": false,
  "model": { "name": "mock-vlm", "version": "0.1.0-mock", "prompt_version": "mock-scene-v1" },
  "segments": [
    { "index": 0, "start_s": 0.0, "end_s": 1.0, "scene_label": "听讲",
      "confidence": 0.55, "evidence": "Mock 适配器生成的占位判断依据，不代表真实模型输出",
      "is_uncertain": false }
  ],
  "metadata": { "sha256": "...", "analysis": { "job_id": "job_e8b239c55919", "is_mock": true, "...": "..." } },
  "job_id": "job_e8b239c55919",
  "prompt_version": "mock-scene-v1",
  "is_mock": true,
  "segment_count": 3,
  "exported_at": "2026-10-24T07:52:31Z"
}
```

`job_id` / `prompt_version` / `is_mock` / `segment_count` / `exported_at` 是**附加字段**，
全部由已保存数据推导（`metadata.analysis`、`model.prompt_version`），不伪造。

#### CSV（200）

响应头：

```text
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="results_vid_5bf8f1443db1.csv"
```

- 编码为 **UTF-8 with BOM**（`EF BB BF`），Windows Excel 双击打开中文不乱码；
- 每行一个场景分段；**无分段时只返回表头**，不伪造数据行；
- 使用标准库 `csv` 处理引号/逗号/换行，行终止符 `CRLF`。

列（顺序固定）：

```text
video_id, video_name, segment_index, start_s, end_s, scene_label, confidence,
evidence, is_uncertain, prediction_source, provider,
model_name, model_version, prompt_version, evaluation_eligible
```

实测（3 段，Console 编码无关）：

```text
vid_5bf8f1443db1,export_clip.mp4,0,0.0,1.0,听讲,0.55,Mock 适配器生成的占位判断依据…,false,mock,mock_vlm,mock-vlm,0.1.0-mock,mock-scene-v1,false
vid_5bf8f1443db1,export_clip.mp4,1,1.0,2.0,小组讨论,0.65,…,false,mock,mock_vlm,mock-vlm,0.1.0-mock,mock-scene-v1,false
vid_5bf8f1443db1,export_clip.mp4,2,2.0,3.0,独立学习,0.75,…,false,mock,mock_vlm,mock-vlm,0.1.0-mock,mock-scene-v1,false
```

缺失字段（例如没有 `model` 的 `oracle` 结果）输出**空字符串**，JSON 中为 `null`，不捏造。

#### 错误

| HTTP | code | 场景 |
|---:|---|---|
| 400 | `VALIDATION_ERROR` | `format` 不是 json/csv（`details` 含 `allowed`） |
| 404 | `VIDEO_NOT_FOUND` | 视频不存在（与"未分析"明确区分） |
| 409 | `VIDEO_NOT_PROCESSED` | 视频存在但无已保存结果（`registered`/`processing`/`failed`） |

409 的 `details` 给出当前 `status` 与最近一次任务的 `job_id/status/progress/error`，
让前端能解释"为什么还没有结果"，而不是伪造成功：

```json
{
  "error": {
    "code": "VIDEO_NOT_PROCESSED",
    "message": "视频尚未分析完成，暂无结果可导出",
    "details": {
      "resource": "video",
      "video_id": "vid_x",
      "status": "failed",
      "job": {
        "job_id": "job_y", "status": "failed", "stage": "inference", "progress": 0.35,
        "error": { "code": "VLM_UPSTREAM_ERROR", "message": "…", "retryable": true }
      }
    },
    "request_id": "…", "retryable": false, "timestamp": "…"
  }
}
```

---

## 5. 任务机制（P0-3 核心）

### 5.1 Job 状态机

```text
创建 ──► queued ──► running ──► completed
                         └────► failed
```

| 状态 | 何时进入 | 约束（由 `schemas/job.py` 强制） |
|---|---|---|
| `queued` | 创建任务 | `progress == 0`、`started_at == null`、`finished_at == null` |
| `running` | worker 取出任务 | 必须有 `started_at` |
| `completed` | 适配器返回合法结果并落库 | `progress == 1`、`stage == done`、必须有 `finished_at`、`error == null` |
| `failed` | 任一环节抛错 | 必须有 `error`、**`result` 必须为 null**（不允许伪造成功） |
| `canceled` | **未实现** | 无取消接口；调用 `/jobs/{id}/cancel` 返回 404，不会伪造取消成功 |

`stage` 取值来自标准枚举：`queued`、`loading_video`、`sampling_frames`、`inference`、`parsing`、`saving`、`done`。

当前实现实际经过的阶段与进度：

| 阶段 | progress | 说明 |
|---|---:|---|
| `queued` | 0.0 | 已入队 |
| `loading_video` | 0.1 | 校验存储文件存在（缺失则 `VIDEO_FILE_MISSING`） |
| `inference` | 0.35 | 调用 VLM 适配器 |
| `parsing` | 0.75 | 校验适配器返回的 segments（合法性 + 时间升序不重叠） |
| `saving` | 0.9 | 事务写入 job + video |
| `done` | 1.0 | 完成 |

> `sampling_frames` 属于标准枚举，但 **Mock 适配器不抽帧**，因此当前不会出现该阶段；
> 真实 MiniCPM 适配器会真正抽帧并推进到该阶段。

### 5.2 执行方式

- **单进程、单线程、单队列、串行执行**（`services/task_runner.py` 的 `JobRunner`）；
- 不用 Redis / Celery：单机开发环境没有收益，且任务书禁止无谓引入重型组件；
- HTTP 请求只入队，**不等待**分析；
- **不使用 sleep 冒充推理**：Mock 适配器本身就是瞬时的，因此中间阶段很短；
  测试若需要观察 `running`，使用的是"会阻塞的适配器替身"，而不是定时器；
- 任务与视频的状态变更在**同一个 SQLite 事务**内完成（`storage/db.py::connect`）；
- 每次状态迁移都是带条件的 `UPDATE ... WHERE status = ?`，非法迁移会抛 `JobStateError`，
  避免出现"completed 却被改成 running"这类不一致。

### 5.3 重复提交策略

**同一视频最多一个活动任务**（`queued` 或 `running`）。

| 情况 | 行为 |
|---|---|
| 已有 `queued`/`running` 任务 | 返回 `409 JOB_ALREADY_RUNNING`，`details` 给出已有 `job_id` 与 `job_status` |
| 上一个任务已 `completed`/`failed` | 允许再次提交，创建**新** `job_id` |
| 提交瞬间的并发 | 由数据库唯一约束 + 条件更新保证不会产生两个活动任务 |

> 选择 409 而不是"静默返回旧任务"，是为了让前端能明确区分"新建"与"已在进行"，
> 并避免用户重复点击造成不可见的多余任务。

### 5.4 重启与并发限制

- **进程重启**：`create_app` 会把上次遗留在 `queued`/`running` 的任务标记为
  `failed`，`error.code = JOB_INTERRUPTED`、`retryable = true`，其视频同步置为 `failed`
  —— 单进程 worker 无法恢复中断的工作，**不会假装仍在运行**；
- **并发**：`concurrency = 1`。8 GB 显卡上未来加载 MiniCPM 后必须串行；当前由单 worker 强制；
- **生产部署**：多进程 WSGI（如 gunicorn 多 worker）下每个进程都有独立队列，
  会造成任务不被执行或重复执行。生产化需要外部队列或单 worker 进程模型，
  这属于 P2 范围，当前未实现。

### 5.5 事务与一致性（Job ↔ Video）

| 时点 | Job | Video |
|---|---|---|
| 创建 | 插入 `queued` 行 | `status=processing`，**清空**旧的 `segments`/`model`/`provider`/`prediction_source=none`/`evaluation_eligible=false` |
| 完成 | `completed` + `result` + `finished_at` | `status=processed` + `segments`/`model`/`provider`/`prediction_source` |
| 失败 | `failed` + `error`（无 `result`） | `status=failed`（仅在 `processing` 时；不回退已完成结果） |
| 重启恢复 | `failed` + `JOB_INTERRUPTED` | `status=failed` |

"创建时清空旧结果"是刻意的：重新分析期间若失败，视频不会残留上一轮的标签，
从而保证 `status` 与 `segments` 语义一致。

---

## 6. 两个适配器：Mock 与真实 MiniCPM-V 4.6

`adapters/vlm/base.py` 定义接口，`build_vlm_adapter()` 按 `BACKEND_VLM_ADAPTER` 选择实现：

| 模式 | 适配器 | `prediction_source` | 模型加载 | 用途 |
|---|---|---|---|---|
| `mock` | `MockVlmAdapter` | `mock` | 不加载 | 验证任务链路（P0-3 起） |
| `minicpm` | `MiniCPMV46Adapter` | `model` | 首个任务时按需加载并复用 | 真实离线短视频分析（P0-5） |

**失败绝不回退**：真实模式任一步出错（模型缺失/加载失败/解码失败/生成失败）都会让 Job
`failed` 并记录错误码，**不会**返回 mock 标签。

### 6.1 Mock 模式的标记

| 项 | 值 |
|---|---|
| `prediction_source` / `provider` / `model.name` | `mock` / `mock_vlm` / `mock-vlm` |
| `model.version` / `prompt_version` | `0.1.0-mock` / `mock-scene-v1` |
| `is_mock` / `evaluation_eligible` | `true` / `false`（Mock 不可参与模型评价） |

### 6.2 真实模式（P0-5）

启用：

```powershell
$env:BACKEND_VLM_ADAPTER = "minicpm"
$env:BACKEND_VLM_MODEL_PATH = "<project-root>\models\MiniCPM-V-4.6"
python app.py
```

处理流程（全部在 `MiniCPMV46Adapter.analyze()` 内，API/存储无需改动）：

1. **校验模型目录**：`config.json` + `model*.safetensors` 存在，否则 `VLM_MODEL_NOT_FOUND`；
2. **解码采样**（`adapters/vlm/frames.py`，PyAV）：顺序解码，按 `interval_s` 取样，
   每帧保留真实 `pts` 时间戳；最多 `max_frames` 帧、最长 `max_duration_s` 秒；
3. **惰性加载**：首次任务时 `AutoProcessor` + `AutoModelForImageTextToText`
   （`bfloat16` + `sdpa`，`local_files_only=True`，CUDA），之后进程内复用；
4. **逐帧推理**：一次一张图 + 约束提示词，要求输出 `类别|≤20字依据`；
5. **解析**（`adapters/vlm/scene.py`）：只接受 5 个标准标签；无法匹配 → `未分类` + `is_uncertain=true`；
6. **合并分段**：相邻同标签合并，边界取采样时间戳，末段收敛到视频时长。

结果字段：

| 项 | 值 |
|---|---|
| `prediction_source` / `provider` | `model` / `minicpm_v` |
| `model.name` / `version` / `prompt_version` | `MiniCPM-V` / `4.6` / `scene-zh-v1` |
| `is_mock` | `false` |
| `evaluation_eligible` | `true`（沿用既有规则：真实模型预测可进入评价；**仍需人工标注才能算指标**） |
| `confidence` | `null` —— 模型没有可校准概率，**不编造数字** |
| `evidence` | 模型输出中 `|` 之后的依据（截断 200 字） |

任务阶段由适配器**真实上报**（见 `AnalysisRequest.on_progress`）：
`loading_video 0.1 → sampling_frames 0.2 → inference 0.35→0.75（逐帧递增）→ parsing 0.8 → saving 0.9 → done 1.0`。

#### 能力边界（重要）

- 模型是**逐帧分类**，不是视频时序模型：分段边界来自**采样分辨率**（默认 1 秒），
  不是模型检测到的场景切换点；
- 因此不要把分段时间当作精确的课堂事件边界；
- 场景标签是**画面层面的课堂形态判断**，不构成对学生专注度或心理状态的推断；
- 采样帧、时间戳、标签分布、prompt 版本都写入 `metadata`，结果可追溯。

#### 本机实测（2026-10-24，RTX 4060 Laptop 8 GB）

| 指标 | 实测值 |
|---|---|
| 模型加载 | ≈7–9 s（首次任务），之后复用 |
| 单帧推理 | ≈1.6–2.2 s（`max_new_tokens=48`，`sdpa`） |
| 3 s / 752 KB SAV 片段端到端 | 冷启动 30.4 s；热态 12.8 s（3 帧） |
| 显存 | 进程内 2516 MiB；`nvidia-smi` 总计 2861 MiB / 8188 MiB |
| 输入 token | 155 / 帧（1280×720，`max_slice_nums=1`，`downsample_mode=16x`） |
| 真实输出示例 | `听讲\|学生举手参与课堂活动` |

> 未安装 `causal_conv1d` / `flash-linear-attention`，transformers 会回退到参考实现（较慢但正确）。
> 未提供 CPU 回退：`BACKEND_VLM_DEVICE` 非 `cuda` 或 CUDA 不可用时会明确报错。

### 6.3 如何切换到同类模型

新增一个实现 `VlmAdapter` 的类并在 `build_vlm_adapter()` 里注册即可；
`segments` 仍要经过 `parse_label_response` + `build_segments`（或自行保证同等校验），
`prediction_source` 填 `model`、`provider` 填实际标识。


---

## 7. 统一错误响应

```json
{
  "error": {
    "code": "JOB_ALREADY_RUNNING",
    "message": "该视频已有正在进行的分析任务",
    "details": { "resource": "video", "video_id": "vid_x", "job_id": "job_y", "job_status": "queued" },
    "request_id": "436cdf111208",
    "retryable": false,
    "timestamp": "2026-10-22T09:20:11Z"
  }
}
```

### 7.1 业务错误码

| HTTP | code | 场景 |
|---:|---|---|
| 400 | `VALIDATION_ERROR` | 参数缺失/非法、空文件、分页越界、枚举非法 |
| 400 | `LOCAL_PATH_NOT_ALLOWED` | 登记路径不在允许导入目录内 |
| 404 | `VIDEO_NOT_FOUND` / `JOB_NOT_FOUND` | 资源不存在 |
| 404 | `VIDEO_FILE_MISSING` | 记录存在、存储文件缺失 |
| 409 | `VIDEO_ALREADY_EXISTS` | `video_id` 重复 |
| 409 | `JOB_ALREADY_RUNNING` | 重复提交活动任务 |
| 409 | `JOB_STATE_CONFLICT` | 非法状态迁移（内部保护） |
| 413 | `PAYLOAD_TOO_LARGE` | 上传超限 |
| 415 | `UNSUPPORTED_VIDEO_FORMAT` | 扩展名/容器不支持 |
| 422 | `VLM_RESULT_INVALID` | 适配器输出不合法（Job 内记录） |
| 422 | `VIDEO_DECODE_FAILED` | 视频无法解码（Job 内记录） |
| 422 | `VIDEO_NO_FRAMES` | 解码未得到可用帧（Job 内记录） |
| 502 | `VLM_LOAD_FAILED` | 模型加载失败（Job 内记录，可重试） |
| 503 | `VLM_MODEL_NOT_FOUND` | 本地模型目录/权重缺失（Job 内记录） |
| 500 | `STORAGE_ERROR` | 本地存储失败 |
| 502 | `VLM_UPSTREAM_ERROR` | 适配器分析失败（Job 内记录） |

> `VLM_*` 与 `JOB_INTERRUPTED` 通常出现在 `job.error` 中（异步失败），
> 而不是 HTTP 响应体。

---

## 8. 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `BACKEND_HOST` / `BACKEND_PORT` | `127.0.0.1` / `8000` | 监听地址 |
| `BACKEND_ENV` / `BACKEND_DEBUG` | `development` / `false` | 环境标识 / 调试 |
| `BACKEND_LOG_LEVEL` / `BACKEND_LOG_FILE` | `INFO` / 空 | 日志 |
| `BACKEND_MAX_UPLOAD_MB` | `512` | 上传/导入上限 |
| `BACKEND_DATA_DIR` | `backend/var` | 数据目录 |
| `BACKEND_DB_PATH` | `<data_dir>/app.db` | 数据库文件 |
| `BACKEND_VIDEO_SUBDIR` | `videos` | 视频子目录 |
| `BACKEND_IMPORT_ROOTS` | 空 | 允许 `register` 的目录（`;` 分隔） |
| **`BACKEND_JOB_WORKER`** | `true` | 是否启动后台任务线程 |
| **`BACKEND_VLM_ADAPTER`** | `mock` | 适配器：`mock` 或 `minicpm` |
| **`BACKEND_VLM_MODEL_PATH`** | `<project-root>/models/MiniCPM-V-4.6` | 本地模型目录（不复制进 backend） |
| **`BACKEND_VLM_DEVICE`** | `cuda` | 推理设备；仅实现并验证 `cuda`，无 CPU 回退 |
| **`BACKEND_VLM_MAX_FRAMES`** | `8` | 单任务最多采样帧数（1–64） |
| **`BACKEND_VLM_FRAME_INTERVAL_S`** | `1.0` | 采样间隔（秒，>0） |
| **`BACKEND_VLM_MAX_DURATION_S`** | `60.0` | 单任务最长处理时长（秒，>0） |
| **`BACKEND_VLM_MAX_NEW_TOKENS`** | `48` | 每帧生成上限 |
| `BACKEND_TESTING` | `false` | 仅测试用 |

---

## 9. 运行测试

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe -m pytest -v
```

在隔离环境中的实测结果：

```text
277 passed, 1 skipped
```

> 被跳过的 1 项是 `test_real_vlm_optional.py`：它会加载真实模型，默认跳过；
> 设置 `BACKEND_REAL_VLM_TEST=1` 才运行（本机实测 `1 passed in 29.77s`）。

全部使用 `tmp_path` 独立数据目录、合成 MP4（148 字节）与 `job_worker_enabled=False` 的确定性队列，
**不下载真实视频、不加载模型、不依赖网络**（唯一例外是上面那条 opt-in 测试）。

| 测试文件 | 数量 | 覆盖 |
|---|---:|---|
| `test_videos_api.py` | 42 | 上传/登记/列表/详情/文件、分页、错误分支、重启持久化 |
| `test_storage.py` | 28 | 仓储 CRUD/排序/过滤、文件名清洗、路径越界、原子写 |
| `test_system.py` | 27 | `/health`、`/info`、统一错误、请求 ID、评价资格规则 |
| `test_jobs_api.py` | 26 | 任务创建 202/404/409、查询、分页过滤、完成/失败、一致性、重启 |
| `test_results_api.py` | 23 | JSON/CSV 结果、与 DB 一致、CSV 转义/BOM、404/400/409、无副作用 |
| **`test_minicpm_adapter.py`** | **27** | 适配器选择、配置校验、模型缺失/加载/生成失败、不回退 mock、Job 集成 |
| `test_mock_adapter.py` | 17 | Mock 标记、时间段合法性、时长未知拒绝 |
| `test_job_runner.py` | 16 | queued→running→completed、失败路径、非法迁移、进度边界 |
| **`test_scene_parse.py`** | **30** | 标签解析（含中文/异常输出）、分段合并、边界与置信度策略 |
| **`test_frames.py`** | **16** | 真实解码（PyAV 生成视频）、采样上限、时间戳守卫 |
| `test_segment.py` | 12 | Segment 时间/置信度/标签校验 |
| `test_media_probe.py` | 9 | `ftyp` 嗅探、`mvhd` 时长、非法容器 |
| `test_config.py` | 4 | 配置默认值与校验 |
| `test_real_vlm_optional.py` | **1（默认跳过）** | 真实模型加载 + 短视频分析（opt-in） |
| **合计** | **277 通过 + 1 跳过** | |

---

## 10. 目录结构

```text
backend/
├── app.py                   create_app()、请求 ID、存储初始化、适配器与 runner 装配、重启恢复
├── config.py                不可变配置 + 环境变量解析
├── logging_setup.py         日志格式与 request_id 过滤器
├── common/timeutil.py       RFC3339 UTC 时间
├── adapters/vlm/            VLM 适配器契约与 Mock 实现
│   ├── base.py              AnalysisRequest / AnalysisOutput / VlmAdapter
│   ├── mock.py              MockVlmAdapter
│   ├── minicpm.py           MiniCPMV46Adapter（真实模型，惰性加载）
│   ├── frames.py            PyAV 解码 + 带时间戳的帧采样
│   ├── scene.py             标签解析 + 分段合并（含边界/置信度策略）
│   └── __init__.py          build_vlm_adapter()
├── api/
│   ├── errors.py            ApiError / ServiceError 映射 / 统一错误处理器
│   ├── params.py            共享分页参数解析
│   ├── system.py            /health、/info
│   ├── videos.py            视频 5 个端点 + process
│   └── jobs.py              任务列表 / 详情
├── schemas/
│   ├── enums.py             标准枚举 + 评价资格规则
│   ├── video.py             Video 模型
│   ├── segment.py           Segment 校验
│   └── job.py               Job 模型 + 状态/进度约束
├── services/
│   ├── errors.py            领域错误
│   ├── media_probe.py       容器嗅探 + mvhd 时长
│   ├── video_service.py     视频业务
│   ├── job_service.py       任务创建/查询/重复策略
│   ├── export_service.py    结果 JSON/CSV 导出（只读持久化数据）
│   └── task_runner.py       单线程队列执行器 + 状态机
├── storage/
│   ├── db.py                SQLite 连接/建表/ping
│   ├── files.py             受限路径/原子写/sha256
│   └── repositories.py      videos 与 jobs 仓储（含条件状态迁移）
├── tests/                   14 个测试文件 + 合成 MP4 工厂 + 真实视频工厂
├── var/                     运行期数据（gitignored）
└── deliverables/            每轮交付 zip（gitignored）
```

---

## 11. 已实现 / 未实现

### 已实现（P0-3 实际验证）

- [x] `POST /videos/{id}/process` → 202 + Job，`Location` 头
- [x] `GET /jobs`（`limit`/`offset`/`status`/`video_id`/`job_type`）、`GET /jobs/{id}`
- [x] Job 持久化于 SQLite，重启后可查（真实进程重启验证）
- [x] queued → running → completed 全流程（真实后台线程验证）
- [x] 失败路径：适配器异常、非法输出、存储文件缺失、时长未知
- [x] 重复提交 409 策略
- [x] Mock 适配器输出明确标记 mock，`evaluation_eligible=false`
- [x] Job/Video 状态在单事务内一致更新
- [x] 重启后中断任务标记 `JOB_INTERRUPTED`
- [x] **`GET /videos/{id}/results?format=json|csv`**：同一份持久化数据，CSV 带 BOM/正确转义
- [x] **真实 MiniCPM-V 4.6 适配器**：`BACKEND_VLM_ADAPTER=minicpm`，惰性加载 + 进程内复用
- [x] **PyAV 解码 + 带真实时间戳的帧采样**（顺序解码，非 seek）
- [x] **标签解析与分段合并**：只接受 5 个标准标签，异常输出 → `未分类`+`is_uncertain`
- [x] **真实模型验收**：3 s / 752 KB 真实片段端到端完成，`prediction_source=model`、`is_mock=false`
- [x] **失败不回退 mock**：模型缺失/加载/解码/生成失败均使任务 `failed` 并记录错误码
- [x] **未分析/运行中/失败的视频导出返回 409 `VIDEO_NOT_PROCESSED`**（不伪造成功）
- [x] **277 项自动化测试通过 + 1 项 opt-in 真实模型测试**

### 未实现（后续阶段）

| 能力 | 计划 |
|---|---|
| SAV 批量处理与评价指标 | P1（**阻塞：无人工标注**） |
| 任务取消（`canceled`） | 未排期；当前明确不支持 |
| EEG Adapter | P0-7 |
| 跨模态融合、实时流、SSE/WebSocket | P2 |
| CPU 推理回退 | 未实现（未验证，因此也不声称支持） |
| 视频级时序模型（真实场景切换点） | 未实现；当前是逐帧分类 + 采样分辨率边界 |

---

## 12. 已知限制

1. **默认是 Mock 适配器**：`prediction_source=mock`，**不能**当作模型性能。
   切到 `minicpm` 后结果为 `prediction_source=model`，但**仍需人工标注才能计算指标**。
2. **真实适配器是逐帧分类**：分段边界等于采样分辨率（默认 1 s），不是模型识别的场景切换点；
   不要把边界当成精确课堂事件时间。
3. **`confidence` 恒为 `null`**：小 VLM 没有可校准概率，不编造数字。
4. **场景标签不等于专注度**：模型只说画面里的课堂形态，不能推断学生心理状态或学习效果。
5. **仅支持 CUDA**：`BACKEND_VLM_DEVICE` 非 `cuda` 或 CUDA 不可用时明确报错，无 CPU 回退。
6. **模型首次加载约 7–9 s**：加载在首个任务内完成，会让第一个任务明显更慢。
7. 未安装 `causal_conv1d` / `flash-linear-attention`，transformers 回退到参考实现（较慢但正确）。
8. **任务取消未实现**，`canceled` 状态不会出现。
9. **单进程单线程**：多进程部署会出现任务不被执行或重复执行，需要外部队列（P2）。
   同一进程内模型被复用，不会重复占用显存。
10. **重启不续跑**：中断任务一律标记 `failed`（`JOB_INTERRUPTED`），需重新提交。
11. **重新分析会清空旧结果**：任务创建时即清空视频的 `segments`/`model`，失败后不保留上一轮。
12. 数据目录默认在源码树内（`backend/var`），与"默认数据不入源码目录"的要求冲突，
    可用 `BACKEND_DATA_DIR` 覆盖。
13. 容器校验只做头部嗅探；真实解码由 PyAV 完成（`torchcodec` 在本环境不可用）。
14. `frontend_task_list(4).md` 在工作区中不存在，实现依据接口标准与 `frontend_task_list.md`。
15. Flask 开发服务器仅适合本地联调。
16. **未分析/运行中/失败的视频查询结果返回 `409 VIDEO_NOT_PROCESSED`**（不是空结果，也不是成功），
    `details.job` 会给出最近任务的状态与错误；这与"未知视频 = 404"明确区分。
17. CSV 固定带 **UTF-8 BOM**；如果下游程序不希望有 BOM，需要自行 `utf-8-sig` 解码后处理。
18. 导出只读当前结果，**不保留历史版本**；重新分析会覆盖旧结果（见第 11 条）。
19. 预览帧与原始视频内容属于学生画面数据：`metadata` 只记录时间戳/标签/依据，不写日志、不入库原始帧。

---

## 13. 与接口标准的一致性

| 标准要求 | 实现 |
|---|---|
| `POST /videos/{id}/process` → 202 + Job | ✅ |
| `GET /videos/{id}/results?format=json\|csv` | ✅ 默认 json；非法 format → 400 |
| Job 字段（12 个标准字段） | ✅ 另加 `provider`/`model`/`metadata`（标准允许向后兼容新增） |
| Job 状态 5 值 | ✅ 实现 4 值，`canceled` 明确未实现 |
| Job 阶段枚举 | ✅ 使用标准 7 个阶段 |
| `progress` 0–1 | ✅ 模型层与数据库层双重校验 |
| 列表 `items` + `pagination` | ✅ 另保留 `jobs` 过渡别名 |
| 统一错误 6 字段 | ✅ 新增错误全部映射 |
| `prediction_source` 枚举（§2.2） | ✅ Mock→`mock`，真实模型→`model`，不复用 `provider` 值 |
| `evaluation_eligible` 由后端计算（§2.2） | ✅ `model`→true，`mock`→false；不因导出改变 |
| `provider` 记录具体实现（§2.2） | ✅ `mock_vlm` / `minicpm_v` |
| `model.name/version/prompt_version` | ✅ `MiniCPM-V` / `4.6` / `scene-zh-v1` |
| `*_at` RFC3339 UTC | ✅ |
| 未处理/失败不得伪造结果 | ✅ `failed` 时 `result` 必须为 null；导出未分析视频 → 409 |
| `evaluation_eligible` 由后端计算 | ✅ Mock → false，导出不改变 |
| `VIDEO_NOT_PROCESSED` 错误码（标准 §6.3） | ✅ 用于未分析/运行中/失败的导出 |
| 不泄露主机路径 | ✅ 有测试断言 |

