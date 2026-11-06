# AutoDL 从零部署手册

本文面向当前仓库的 Windows 本地环境。完成后，Flask 继续处理上传、窗口切分和 Segment 保存，AutoDL 只运行 MiniCPM-V 4.5 + scene4/checkpoint-600 推理。

## 1. 选择 AutoDL GPU

MiniCPM-V 4.5 BF16 权重约 16.2 GiB，经 PyAV 解码后的 8 帧、SDPA 推理和 PEFT 还需要额外显存。

- 最低建议：24 GiB 显存。
- 更稳妥：32 GiB 或 40 GiB。
- 不推荐：16 GiB 或更小；16.2 GiB 权重本身已无法完整驻留。
- 数据盘：至少预留 40 GB，用于 16.2 GiB 基座、LoRA、虚拟环境和日志。

当前部署脚本的环境检查要求在 AutoDL 中至少检测到 20 GiB 总显存，否则明确退出。

## 2. 获取 AutoDL SSH 信息

在 AutoDL 实例详情或登录说明中找到：

- SSH 主机名，例如 `region-1.autodl.com`，不是网页 URL。
- SSH 端口，例如 `12345`。
- 用户名，通常为 `root`。
- 登录密码或推荐使用的 SSH 私钥。

如果还没有密钥，在 Windows PowerShell 中生成：

```powershell
ssh-keygen -t ed25519 -f "$HOME\.ssh\id_ed25519"
```

把公钥安装到 AutoDL：

```powershell
Get-Content "$HOME\.ssh\id_ed25519.pub" |
  ssh -p <SSH端口> root@<SSH主机> `
  "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

此步骤会要求输入一次 AutoDL 密码。之后自动部署使用密钥。

## 3. 配置本机连接信息

复制配置文件：

```powershell
cd E:\dachuang\System-Intergration
Copy-Item scripts\autodl.connection.example.psd1 scripts\autodl.connection.psd1
Copy-Item scripts\autodl.secrets.example.psd1 scripts\autodl.secrets.psd1
```

编辑 `scripts\autodl.connection.psd1`，填写 SSH 主机、端口、用户、私钥和本地模型目录。

生成 Token：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

编辑 `scripts\autodl.secrets.psd1`，把同一个 Token 写入：

```powershell
@{
    ServiceToken = "<生成的Token>"
    BackendRemoteToken = "<同一个Token>"
}
```

这两个本地文件已加入 `.gitignore`，不会上传到前端。

## 4. 上传模型

可单独运行：

```powershell
.\scripts\upload_model_to_autodl.ps1
```

脚本会检查：

- 基座 `config.json`。
- 权重索引及所有索引引用的 safetensors 分片。
- Tokenizer、Processor、远程模型代码等必要文件。
- LoRA 的 `adapter_config.json` 和 `adapter_model.safetensors`。

上传恢复策略：

- 优先使用 `rsync --partial --append-verify` 断点续传。
- 没有 rsync 时，小文件使用 `scp`；大权重按 256 MiB 分块上传并跳过已完成块，
  所有块齐全后校验总大小再拼接。
- 结束后逐文件比较本地和远端字节数。

## 5. 安装 AutoDL 环境

正常不需要单独运行，`deploy_to_autodl.ps1` 会调用：

```bash
bash deploy/autodl/install.sh
bash deploy/autodl/check_environment.sh
```

安装脚本使用 `--system-site-packages` 虚拟环境，优先复用 AutoDL 镜像已有的 Torch/Torchvision/CUDA，不修改系统环境。如果镜像没有 Torch，需要通过 `TORCH_INDEX_URL` 提供与实际 CUDA 版本匹配的官方 wheel index。

检查内容包括：

- Python 3.10+。
- `nvidia-smi`、GPU 型号、显存和驱动。
- Torch、Torchvision 和 CUDA 可用性。
- Transformers、PEFT、Accelerate、Safetensors、FastAPI、Pillow。
- 模型文件结构。

## 6. 一键部署与启动

如果 AutoDL 镜像已经包含匹配的 Torch：

```powershell
.\scripts\deploy_to_autodl.ps1
```

如果镜像没有 Torch，需要提供 wheel index：

```powershell
.\scripts\deploy_to_autodl.ps1 -TorchIndexUrl "<与实际CUDA匹配的PyTorch索引>"
```

脚本依次完成：

1. 上传服务代码和部署脚本。
2. 通过加密 SSH stdin 写入远端 `.env` 并设置权限 600。
3. 上传并校验模型。
4. 安装独立依赖。
5. 检查 GPU、CUDA、依赖和模型。
6. 启动 FastAPI，加载基座和 LoRA。
7. 启动 Windows 后台 SSH 隧道。
8. 检查 SSH、GPU、云端健康和隧道。
9. 执行一个真实窗口测试。

服务日志位于远端项目 `.run/cloud-vlm.log`。

## 7. 建立 SSH 隧道

一键部署会自动启动。后续手动启动：

```powershell
.\scripts\start_autodl_tunnel.ps1
```

停止：

```powershell
.\scripts\stop_autodl_tunnel.ps1
```

检查：

```powershell
.\scripts\check_autodl_connection.ps1
```

隧道只转发到 AutoDL 的 `127.0.0.1`，不把模型端口直接暴露到公网。

## 8. 检查服务

```powershell
.\scripts\check_autodl_connection.ps1
```

也可以直接查看健康响应：

```powershell
$secrets = Import-PowerShellDataFile .\scripts\autodl.secrets.psd1
Invoke-RestMethod `
  -Uri http://127.0.0.1:18080/health `
  -Headers @{ Authorization = "Bearer $($secrets.ServiceToken)" }
```

必须看到：

```text
loaded = true
model.version = 4.5
model.checkpoint = checkpoint-600
```

## 9. 测试一组 8 帧

```powershell
.\scripts\test_single_window.ps1 `
  -Video "E:\dachuang\SAV\dataset\20181016_05_1064.mp4" `
  -StartS 0 `
  -EndS 3
```

脚本按负责人规则选择最多 8 帧，以无损 PNG 发送到云端。响应包含：

- `raw_prediction`。
- `predicted_label`。
- `is_uncertain`。
- `frame_count`。
- `inference_ms`。

真实 GPU 服务端模型加载测试：

```bash
bash /root/autodl-tmp/minicpmv45-service/deploy/autodl/real_gpu_check.sh
```

## 10. 打开原前端并上传视频

先启动 Flask：

```powershell
.\scripts\start_backend_remote.ps1
```

这里运行在当前 PowerShell 前台，按 `Ctrl+C` 停止。

新开一个 PowerShell：

```powershell
cd E:\dachuang\System-Intergration\frontend
npm run dev
```

浏览器打开 Vite 显示的本地地址，上传视频并创建分析任务。

## 11. 查看真实模型结果

使用前端时间轴查看 Segment。也可以 API 查看：

```text
GET /api/v1/jobs/{job_id}
GET /api/v1/videos/{video_id}/results?format=json
GET /api/v1/videos/{video_id}/results?format=csv
```

真实模型结果：

```text
prediction_source = model
provider = minicpm_v
is_mock = false
model.version = 4.5
model.checkpoint = checkpoint-600
```

Mock 结果：

```text
prediction_source = mock
provider = mock_vlm
is_mock = true
```

无人值守端到端测试：

```powershell
.\scripts\test_full_video_e2e.ps1
```

组合执行健康、单窗口和端到端测试：

```powershell
.\scripts\run_real_acceptance.ps1
```

## 12. 关闭服务和 AutoDL 实例

停止云端模型服务：

```powershell
ssh -p <端口> root@<主机> `
  "bash /root/autodl-tmp/minicpmv45-service/deploy/autodl/stop_service.sh"
```

停止隧道：

```powershell
.\scripts\stop_autodl_tunnel.ps1
```

停止 Flask 和 Vite 使用各自窗口的 `Ctrl+C`。最后在 AutoDL 控制台停止或释放实例，避免继续计费。

## 13. 850 条验证集评估

当前 850 条 CSV 和全部视频已核对，可确定性重建验证集：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\build_scene4_val_jsonl.py
```

设置评估 Token：

```powershell
$env:VLM_SERVICE_TOKEN = (Import-PowerShellDataFile .\scripts\autodl.secrets.psd1).ServiceToken
```

通过隧道运行：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\evaluate_cloud_model.py `
  --jsonl .\work\minicpmv45_scene4_val_v1.jsonl `
  --url http://127.0.0.1:18080/predict_window `
  --output-dir .\work\eval-checkpoint-600 `
  --expected-count 850
```

输出包括：

- `metrics.json`：严格 Accuracy、可解析 Accuracy、Macro-F1、解析率。
- `per_class_metrics.json`：每类 Precision、Recall、F1、support。
- `confusion_matrix.json`。
- `classification_report.txt`。
- `predictions.csv`。
- `errors.csv`。

没有真实执行时不会生成真实指标，仓库中也不包含编造的指标。

## 14. 无 GPU 一键验收

```powershell
.\scripts\run_pre_gpu_acceptance.ps1
```

该命令运行云端服务 HTTP 测试、Flask 全量回归、Mock AutoDL 真实回环 HTTP 测试、
前端 API 契约测试、类型检查、生产构建，并确定性重建 850 条验证 JSONL。

## 15. 常见错误

| 错误 | 处理 |
|---|---|
| `Permission denied (publickey,password)` | 检查 `SshHostName`、`SshPort`、用户和私钥；手动执行一次 SSH 测试 |
| 隧道启动后立即退出 | 查看 `.run/autodl-tunnel.err.log`；检查远端 SSH 和端口转发权限 |
| `Address already in use` | 修改本地 `LocalPort`，确保 AutoDL 服务端口一致 |
| `VLM_UNAUTHORIZED` | 两份 Token 不一致；修正 `autodl.secrets.psd1` 后重新部署 |
| `VLM_MODEL_FILES_MISSING` | 远端路径错误或模型上传不完整；重新运行上传脚本 |
| `VLM_MODEL_LOAD_FAILED` | 检查 CUDA、PyTorch、Torchvision、磁盘和 `.run/cloud-vlm.log` |
| 显存不足或 OOM | 使用至少 24 GiB，优先 32/40 GiB；不要本机加载 BF16 模型绕过 |
| `torch.cuda.is_available=false` | 当前不是 GPU 实例或 CUDA wheel 与镜像不匹配 |
| 健康检查超时但进程存在 | 大模型冷加载可能较慢；检查日志，等待时间由 `STARTUP_WAIT_S` 控制 |
| Flask 返回 `VLM_REMOTE_UNAVAILABLE` | 隧道断开或云端服务停止；运行连接检查并查看服务日志 |
| 输出为“未分类” | 模型成功生成但文本无法匹配四标签；查看 `errors.csv` 的原始输出 |

