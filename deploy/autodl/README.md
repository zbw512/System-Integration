# AutoDL MiniCPM-V 4.5 + LoRA 推理服务

本目录只部署云端推理服务。视频上传、窗口抽取、Segment 保存和前端仍由本地 Flask 项目负责。

从配置连接到真实上传测试的完整流程见
[`AUTODL_DEPLOYMENT.md`](../../AUTODL_DEPLOYMENT.md)。

## 1. 创建服务目录

建议将项目上传到：

```text
/root/autodl-tmp/minicpmv45-service
```

模型默认放在：

```text
/root/autodl-tmp/MiniCPM-V-4_5
/root/autodl-tmp/checkpoint-600
```

## 2. 配置 Token

```bash
cd /root/autodl-tmp/minicpmv45-service
cp deploy/autodl/.env.example deploy/autodl/.env
python3 -c "import secrets; print(secrets.token_hex(32))"
chmod 600 deploy/autodl/.env
```

把生成的 Token 写入 `deploy/autodl/.env` 的 `VLM_SERVICE_TOKEN`。Token 同时配置到本地 Flask 后端，但绝不能写入 React 前端。

## 3. 安装

```bash
bash deploy/autodl/install.sh
```

若 AutoDL 虚拟环境没有 Torch/Torchvision，需要根据实际 CUDA 镜像设置：

```bash
TORCH_INDEX_URL=<official-pytorch-wheel-index> \
TORCH_VERSION=2.14.1 \
TORCHVISION_SPEC=torchvision \
bash deploy/autodl/install.sh
```

`torchvision` 必须与所选 Torch/CUDA 使用同一个 wheel index。当前没有 GPU 环境，不能在本地验证这一项。

## 4. 环境与模型检查

```bash
bash deploy/autodl/check_environment.sh
bash deploy/autodl/load_model.sh
```

第二条会真实加载模型，因此必须在 AutoDL GPU 上运行。

## 5. 启动和停止

```bash
bash deploy/autodl/start_service.sh
bash deploy/autodl/healthcheck.sh
bash deploy/autodl/stop_service.sh
```

日志与 PID 默认位于项目根目录 `.run/`。

## 6. 接口

两个接口均要求：

```text
Authorization: Bearer <VLM_SERVICE_TOKEN>
```

`GET /health` 在模型加载完成时返回 200，否则返回 503，并仍提供结构化状态。

`POST /predict_window` 接收 1-8 张 PNG。所有图片保持请求中的顺序，整体传入一次 `model.chat()`。服务不使用任意客户端 Prompt，也不读取 `temperature`、`max_new_tokens` 等参数。

## 7. SSH 隧道

开发阶段建议在 Windows 执行：

```powershell
ssh -N -L 18080:127.0.0.1:18080 autodl
```

服务只监听 AutoDL 的 `127.0.0.1`。不要把未配置 TLS 的端口直接公开到公网。
