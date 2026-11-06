from __future__ import annotations

import json
import sys
import types
from contextlib import nullcontext
from pathlib import Path

import pytest
from PIL import Image

from cloud_vlm_service.config import Settings
from cloud_vlm_service.errors import ModelAssetsMissingError
from cloud_vlm_service.runtime import MiniCPMV45LoRARuntime, inspect_model_assets


def make_settings(tmp_path: Path) -> Settings:
    base = tmp_path / "base"
    adapter = tmp_path / "adapter"
    base.mkdir()
    adapter.mkdir()
    (base / "config.json").write_text(
        json.dumps({"version": 4.5}),
        encoding="utf-8",
    )
    for filename in (
        "configuration_minicpm.py",
        "image_processing_minicpmv.py",
        "modeling_minicpmv.py",
        "modeling_navit_siglip.py",
        "preprocessor_config.json",
        "processing_minicpmv.py",
        "resampler.py",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        (base / filename).write_text("{}", encoding="utf-8")
    shard = "model-00001-of-00001.safetensors"
    (base / shard).write_bytes(b"\0")
    (base / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"weight": shard}}),
        encoding="utf-8",
    )
    (adapter / "adapter_config.json").write_text(
        json.dumps({"peft_type": "LORA"}),
        encoding="utf-8",
    )
    (adapter / "adapter_model.safetensors").write_bytes(b"\0")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(
        "仅依据视频画面，判断班级当前的主要学习场景。\n"
        "候选类别：听讲、小组讨论、独立学习、其他。\n"
        "只输出一个类别名称，不要解释。\n",
        encoding="utf-8",
    )
    return Settings(
        base_model_path=base,
        adapter_path=adapter,
        service_token="x" * 32,
        prompt_path=prompt,
        load_on_startup=False,
    )


def test_structural_asset_check(tmp_path: Path) -> None:
    result = inspect_model_assets(make_settings(tmp_path))
    assert result["valid"] is True
    assert result["base_shards"] == ["model-00001-of-00001.safetensors"]


def test_missing_adapter_is_reported(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    (settings.adapter_path / "adapter_model.safetensors").unlink()
    result = inspect_model_assets(settings)
    assert result["valid"] is False
    assert "adapter_weights_missing" in result["errors"]


def test_missing_assets_prevent_load(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    (settings.base_model_path / "config.json").unlink()
    runtime = MiniCPMV45LoRARuntime(settings)
    with pytest.raises(ModelAssetsMissingError):
        runtime.load()


def test_minicpm_v46_base_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    (settings.base_model_path / "config.json").write_text(
        json.dumps({"version": 4.6}),
        encoding="utf-8",
    )
    result = inspect_model_assets(settings)
    assert result["valid"] is False
    assert "base_model_version_not_4_5" in result["errors"]


def test_model_is_loaded_once_and_chat_receives_all_frames_in_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path)
    calls = {"auto_model": 0, "auto_model_kwargs": [], "peft_model": 0, "chat": []}

    class FakeTorchModel:
        def eval(self):
            return self

        def cuda(self):
            return self

        def chat(self, **kwargs):
            calls["chat"].append(kwargs)
            return "小组讨论"

    class FakeTokenizer:
        pass

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return FakeTokenizer()

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            calls["auto_model"] += 1
            calls["auto_model_kwargs"].append(kwargs)
            return FakeTorchModel()

    class FakePeftModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            calls["peft_model"] += 1
            return FakeTorchModel()

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = object()
    fake_torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        get_device_name=lambda index: "Fake GPU",
    )
    fake_torch.inference_mode = lambda: nullcontext()
    transformers = types.ModuleType("transformers")
    transformers.AutoModel = FakeAutoModel
    transformers.AutoTokenizer = FakeAutoTokenizer
    peft = types.ModuleType("peft")
    peft.PeftModel = FakePeftModel

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "peft", peft)

    runtime = MiniCPMV45LoRARuntime(settings)
    runtime.load()
    runtime.load()
    frames = [
        Image.new("RGB", (2, 2), (index, index, index))
        for index in range(8)
    ]
    result = runtime.predict_window(frames)

    assert result.raw_prediction == "小组讨论"
    assert calls["auto_model"] == 1
    assert calls["peft_model"] == 1
    assert len(calls["chat"]) == 1
    assert calls["auto_model_kwargs"][0]["torch_dtype"] is fake_torch.bfloat16
    assert "dtype" not in calls["auto_model_kwargs"][0]

    kwargs = calls["chat"][0]
    assert kwargs["image"] is None
    assert kwargs["use_image_id"] is False
    assert kwargs["max_slice_nums"] == 2
    assert set(kwargs) == {
        "image",
        "msgs",
        "tokenizer",
        "use_image_id",
        "max_slice_nums",
    }
    content = kwargs["msgs"][0]["content"]
    assert len(content) == 9
    assert content[:-1] == frames
    assert content[-1].startswith("仅依据视频画面")
