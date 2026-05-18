"""
环境检测模块 — 自动检测 GPU/VRAM/RAM/CUDA/PyTorch

用于模型管理面板显示运行环境信息，并评估各模型的适配级别。

用法:
    from pipeline.env_detect import detect_env, assess_model_fit

    env = detect_env()
    fit = assess_model_fit(env, vram_required_gb=3.0)
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EnvInfo:
    gpu_name: str = ""
    vram_total_gb: float = 0.0
    vram_free_gb: float = 0.0
    cpu_cores: int = 0
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    cuda_version: str = ""
    pytorch_version: str = ""
    python_version: str = ""
    os_name: str = ""
    has_gpu: bool = False
    errors: list = field(default_factory=list)


def detect_env() -> EnvInfo:
    """检测当前运行环境。"""
    info = EnvInfo()

    info.python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    info.os_name = f"{platform.system()} {platform.release()}"

    # PyTorch
    try:
        import torch
        info.pytorch_version = torch.__version__
    except Exception:
        info.pytorch_version = "未安装"

    # CPU / RAM
    try:
        import psutil
        info.cpu_cores = os.cpu_count() or 0
        mem = psutil.virtual_memory()
        info.ram_total_gb = round(mem.total / (1024 ** 3), 1)
        info.ram_available_gb = round(mem.available / (1024 ** 3), 1)
    except Exception:
        info.cpu_cores = os.cpu_count() or 0

    # GPU / CUDA
    _detect_cuda(info)
    if not info.has_gpu:
        _detect_gpu_fallback(info)

    return info


def _detect_cuda(info: EnvInfo) -> None:
    """通过 PyTorch CUDA 检测 GPU。"""
    try:
        import torch
    except Exception:
        return

    try:
        info.cuda_version = torch.version.cuda or ""
    except Exception:
        pass

    if not torch.cuda.is_available():
        return

    info.has_gpu = True
    try:
        info.gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        info.gpu_name = "NVIDIA GPU"

    try:
        total_mb = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
        info.vram_total_gb = round(total_mb / 1024, 1)

        allocated = torch.cuda.memory_allocated(0) // (1024 * 1024)
        reserved = torch.cuda.memory_reserved(0) // (1024 * 1024)
        free_mb = total_mb - max(allocated, reserved)
        info.vram_free_gb = round(free_mb / 1024, 1)
    except Exception:
        pass


def _detect_gpu_fallback(info: EnvInfo) -> None:
    """nvidia-smi 回退检测 (当 PyTorch CUDA 不可用时)。"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            timeout=10,
            text=True, encoding="utf-8", errors="replace",
        )
        parts = out.strip().split(",")
        if len(parts) >= 2:
            info.has_gpu = True
            info.gpu_name = parts[0].strip()
            info.vram_total_gb = round(float(parts[1].strip()) / 1024, 1)
            if len(parts) >= 3:
                info.vram_free_gb = round(float(parts[2].strip()) / 1024, 1)
    except Exception:
        pass


def assess_model_fit(env: EnvInfo, vram_gb: float) -> dict:
    """评估模型在当前硬件上的适配级别。

    Returns:
        { "level": "recommended"|"runnable"|"tight"|"unusable"|"cloud",
          "label": "✓ 推荐"|"○ 可运行"|"△ 紧张"|"✗ 不可用"|"☁ 云端",
          "color": "success"|"info"|"warning"|"error"|"default" }
    """
    if vram_gb <= 0:
        return {"level": "cloud", "label": "☁ 云端", "color": "default"}

    if not env.has_gpu:
        # CPU 模式：检查 RAM
        if env.ram_total_gb > 0 and vram_gb * 2.5 < env.ram_total_gb:
            return {"level": "runnable", "label": "○ CPU可运行", "color": "info"}
        elif env.ram_total_gb > 0 and vram_gb * 1.5 < env.ram_total_gb:
            return {"level": "tight", "label": "△ CPU紧张", "color": "warning"}
        return {"level": "unusable", "label": "✗ 不可用", "color": "error"}

    free = env.vram_free_gb if env.vram_free_gb > 0 else env.vram_total_gb * 0.5
    total = env.vram_total_gb

    if free > vram_gb * 1.5:
        return {"level": "recommended", "label": "✓ 推荐", "color": "success"}
    elif free > vram_gb:
        return {"level": "runnable", "label": "○ 可运行", "color": "info"}
    elif total > vram_gb:
        return {"level": "tight", "label": "△ 显存紧张", "color": "warning"}
    elif total * 1.5 > vram_gb:
        return {"level": "tight", "label": "△ 显存紧张", "color": "warning"}
    return {"level": "unusable", "label": "✗ 不可用", "color": "error"}
