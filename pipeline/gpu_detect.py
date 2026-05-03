"""
GPU 编码器自动检测 — detect_gpu_encoder

检查可用 ffmpeg 硬件编码器，按质量排序自动选最优。
"""

from __future__ import annotations

import os
import subprocess
from typing import Dict, List, Optional


# 编码器优先级（质量/速度综合排序）
#
# 策略:
# - 只有 h264_nvenc 通过 nvidia-smi 可验证，优先使用
# - AMF/QSV/VideoToolbox/OMX 虽有编译但无可用运行时验证（避免 BrokenPipe），
#   需要硬件编码器时可手动指定或通过 test_encode() 验证
_ENCODER_PRIORITY: List[str] = [
    "h264_nvenc",
    "libx264",
]

# 硬件编码器 → ffmpeg-preset 兼容值映射
# x264 用 "medium"，各硬件编码器 preset 命名与内涵不同。
_ENCODER_PRESETS: Dict[str, str] = {
    "h264_nvenc": "p4",   # p4 ≈ medium（NVENC 命名不同）
}


def _get_available_encoders(ffmpeg_exe: str) -> List[str]:
    """调用 ffmpeg -encoders 获取可用的编码器列表。"""
    try:
        result = subprocess.run(
            [ffmpeg_exe, "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        encoders = []
        for line in result.stdout.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("Encoders:"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                encoders.append(parts[1])
        return encoders
    except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
        return []


def _check_nvidia_gpu() -> bool:
    """检查 NVIDIA GPU 是否可用。"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def detect_best_encoder(ffmpeg_exe: Optional[str] = None) -> str:
    """自动检测最优视频编码器。

    检查顺序:
    1. ffmpeg 可用编码器列表
    2. NVIDIA GPU 是否存在
    3. 按优先级队列选择第一个可用的硬件编码器
    4. 无硬件加速 → libx264

    Args:
        ffmpeg_exe: ffmpeg 可执行文件路径。None 时自动查找。

    Returns:
        编码器名称，如 "h264_nvenc" 或 "libx264"
    """
    from pipeline.utils import get_ffmpeg_exe

    if ffmpeg_exe is None:
        ffmpeg_exe = get_ffmpeg_exe()

    available = _get_available_encoders(ffmpeg_exe)

    for enc in _ENCODER_PRIORITY:
        if enc in available:
            if enc == "h264_nvenc" and not _check_nvidia_gpu():
                continue
            return enc

    return "libx264"


def detect_gpu_info() -> Dict[str, Optional[str]]:
    """检测 GPU 信息。

    Returns:
        {"vendor": "nvidia" | "amd" | "intel" | None, "name": GPU 名称或 None}
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            return {"vendor": "nvidia", "name": parts[0].strip()}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return {"vendor": None, "name": None}


def apply_best_encoder_to_config(config) -> None:
    """自动检测 GPU 并设置 config.video_codec 为最优编码器。

    如果当前 video_codec 已是硬件编码器则跳过（尊重用户手动配置）。
    同时调整 video_preset 为硬件编码器兼容值。

    Args:
        config: TTSConfig 实例（或具有 video_codec/video_preset 属性的对象）
    """
    from pipeline.utils import get_ffmpeg_exe

    manual_hw = [e for e in _ENCODER_PRIORITY if e != "libx264"]
    if config.video_codec in manual_hw:
        return

    best = detect_best_encoder(get_ffmpeg_exe())
    if best != config.video_codec:
        print(f"[GPU 检测] 编码器 {config.video_codec} → {best}")
        config.video_codec = best

        # 同步调整 preset
        if best in _ENCODER_PRESETS:
            config.video_preset = _ENCODER_PRESETS[best]
