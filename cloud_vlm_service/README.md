# MiniCPM-V 4.5 scene4 inference service

独立 FastAPI 服务，仅负责 MiniCPM-V 4.5 + scene4/checkpoint-600 的单窗口推理。

固定契约：

- 基座：MiniCPM-V 4.5，BF16，SDPA。
- LoRA：PEFT `checkpoint-600`。
- 每个窗口 1-8 张 PNG，按请求顺序作为一组图片。
- 一张窗口只调用一次 `model.chat()`。
- `image=None`、`use_image_id=False`、`max_slice_nums=2`。
- 不传递额外生成参数。
- Prompt 固定为 `scene4-label-v1`。
- 无法解析的输出返回 `未分类`，并设置 `is_uncertain=true`。

## 无 GPU 测试

```powershell
python -m venv <test-venv>
<test-venv>\Scripts\python.exe -m pip install -r cloud_vlm_service/requirements-test.txt
<test-venv>\Scripts\python.exe -m pytest cloud_vlm_service/tests -v
```

测试使用假模型运行时，不导入 Torch，不加载权重，也不访问 GPU。

## 启动

```bash
python -m uvicorn cloud_vlm_service.app:create_app \
  --factory \
  --host 127.0.0.1 \
  --port 18080 \
  --workers 1
```

生产部署优先使用 `deploy/autodl/start_service.sh`。

## 请求示例

```json
{
  "request_id": "job123-window0",
  "window_id": "job123-window0",
  "window_start_s": 0.0,
  "window_end_s": 3.0,
  "prompt_version": "scene4-label-v1",
  "frames": [
    {
      "timestamp_s": 0.0,
      "mime_type": "image/png",
      "image_base64": "<PNG base64>"
    }
  ]
}
```

## 响应示例

```json
{
  "request_id": "job123-window0",
  "window_id": "job123-window0",
  "raw_prediction": "听讲",
  "predicted_label": "听讲",
  "is_uncertain": false,
  "parse_status": "parsed",
  "model": {
    "name": "MiniCPM-V",
    "version": "4.5",
    "finetune": "scene4",
    "checkpoint": "checkpoint-600",
    "prompt_version": "scene4-label-v1"
  },
  "frame_count": 8,
  "inference_ms": 1234.5
}
```

## 尚未完成

- Flask 已通过 `MiniCPMV45RemoteAdapter` 接入本服务，使用
  `BACKEND_VLM_ADAPTER=minicpm_remote`。
- 真实模型加载、单窗口原始输出和 850 条验证集评估必须等 AutoDL GPU 可用后执行。
- 原始训练数据构造和 ms-swift 视频加载源码未提供，不能宣称线上窗口化已与训练加载器逐字节一致。
