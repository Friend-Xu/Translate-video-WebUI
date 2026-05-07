"""
VRAM 检测与设备选择

为音色克隆引擎提供 GPU 显存检测和自动设备/引擎推荐。
"""

from __future__ import annotations

import subprocess
from typing import Optional


def detect_vram_mb(device: str = "cuda:0") -> int:
    """查询 GPU 总显存（MB）。

    通过 nvidia-smi 查询，失败时返回 0（视为无 GPU）。

    Args:
        device: CUDA 设备标识，如 "cuda:0"

    Returns:
        显存大小（MB），0 表示无可用 GPU
    """
    if ":" in device:
        try:
            gpu_idx = int(device.split(":")[1])
        except (ValueError, IndexError):
            gpu_idx = 0
    else:
        gpu_idx = 0

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
                f"--id={gpu_idx}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().split("\n")[0])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return 0


def _torch_cuda_available() -> bool:
    """检测 PyTorch CUDA 是否可用。"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def detect_best_device(vram_limit_mb: int = 0) -> str:
    """自动选择最优推理设备。

    决策逻辑：
    1. PyTorch CUDA 不可用 → "cpu"
    2. 显存 < 阈值 → "cpu"
    3. 否则 → "cuda:0"

    Args:
        vram_limit_mb: 最低显存要求(MB)。0=使用默认阈值 2048MB。

    Returns:
        设备字符串: "cpu" 或 "cuda:0"
    """
    if not _torch_cuda_available():
        return "cpu"

    threshold = vram_limit_mb if vram_limit_mb > 0 else 2048
    vram = detect_vram_mb()

    if vram < threshold:
        return "cpu"
    return "cuda:0"


def recommend_engine(available_vram_mb: Optional[int] = None) -> str:
    """根据 VRAM 推荐最优音色克隆引擎。

    阈值：
    - ≥8GB → CosyVoice（质量优先）
    - 2-8GB → OpenVoice（兼容优先）
    - <2GB → none（不建议启用）

    Args:
        available_vram_mb: 可用显存(MB)。None 时自动检测。

    Returns:
        引擎标识: "cosyvoice" | "openvoice" | "none"
    """
    if available_vram_mb is None:
        available_vram_mb = detect_vram_mb()

    if available_vram_mb >= 8192:
        return "cosyvoice"
    elif available_vram_mb >= 2048:
        return "openvoice"
    else:
        return "none"


def get_vram_info(device: str = "cuda:0") -> dict:
    """获取完整 GPU 信息。

    Returns:
        {"device": "cuda:0", "total_mb": 8192, "available": True, "recommended_engine": "cosyvoice"}
    """
    total_mb = detect_vram_mb(device)
    available = total_mb > 0 and _torch_cuda_available()

    return {
        "device": device,
        "total_mb": total_mb,
        "available": available,
        "recommended_engine": recommend_engine(total_mb) if available else "none",
    }
