"""
Voice Cloner 抽象层 — VoiceCloner Protocol + VoiceCloneConfig

统一 OpenVoice 和 CosyVoice 的音色克隆接口。
新增引擎只需实现 VoiceCloner Protocol，无需继承。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class VoiceCloneConfig:
    """音色克隆统一配置"""

    engine: str = "openvoice"
    """克隆引擎: openvoice | cosyvoice | none"""

    device: str = "auto"
    """设备: auto | cuda:0 | cpu"""

    vram_limit_mb: int = 0
    """显存上限(MB)。0=自动检测"""

    concurrent_workers: int = 1
    """并发 clone 数。1=串行"""

    model_dir: str = "./models"
    """模型根目录"""

    color_audio_path: str = "./speakers/Color_audio.WAV"
    """音色参考音频路径"""

    enable_watermark: bool = False
    """是否启用水印（增加显存消耗）"""

    vad_duration: int = 8
    """VAD 分段时长（秒）"""

    error_log_path: str = ""  # default: written to workspace by tts_video.py

    # CosyVoice 专用
    cosyvoice_mode: str = "local"
    """CosyVoice 运行模式: local | docker"""

    cosyvoice_docker_url: str = "http://127.0.0.1:5000"
    """Docker 模式下的服务地址"""

    se_cache_dir: str = "./models/.se_cache"
    """Speaker embedding 缓存目录"""

    # 模型版本（CosyVoice 用）
    model_version: str = "v2"
    """CosyVoice 模型版本: v2 | v3"""

    cosyvoice_fp16: bool = True
    """CosyVoice 本地模式是否启用 fp16"""

    cosyvoice_load_jit: bool = False
    """CosyVoice 是否启用 JIT"""

    cosyvoice_load_trt: bool = False
    """CosyVoice 是否启用 TensorRT"""

    cosyvoice_docker_timeout: int = 300
    """CosyVoice Docker 请求超时(秒)"""

    sample_rate: int = 24000
    """输出采样率（CosyVoice 默认 24000）"""

    def __post_init__(self):
        if self.engine not in ("openvoice", "cosyvoice", "none"):
            raise ValueError(f"不支持的克隆引擎: {self.engine}")
        if self.cosyvoice_mode not in ("local", "docker"):
            raise ValueError(f"不支持的 CosyVoice 模式: {self.cosyvoice_mode}")
        if self.concurrent_workers < 1:
            raise ValueError(f"concurrent_workers 不能小于 1: {self.concurrent_workers}")


@runtime_checkable
class VoiceCloner(Protocol):
    """音色克隆统一接口 Protocol。

    实现此 Protocol 即可接入新的音色克隆引擎。
    无需继承，Python 结构类型系统自动匹配。
    """

    def prepare(self, voice_path: str) -> bool:
        """准备音色参考。

        从参考音频提取 speaker embedding，缓存到内存/磁盘。

        Args:
            voice_path: 人声 WAV 路径（来自 Demucs vocal 分离）

        Returns:
            True 成功，False 失败
        """
        ...

    def clone(self, tts_audio_path: str, output_dir: str) -> Optional[str]:
        """克隆音色。

        将 TTS 音频的音色转换为目标说话人音色。

        Args:
            tts_audio_path: TTS 生成的音频路径
            output_dir: 输出目录

        Returns:
            克隆后音频路径，失败返回 None
        """
        ...

    def device_info(self) -> dict:
        """返回设备信息。

        Returns:
            {"device": "cuda:0", "vram_mb": 8192, "mode": "gpu", "concurrency": 2}
        """
        ...

    def cleanup(self) -> None:
        """释放模型资源（GPU 显存、文件句柄等）。"""
        ...


class NoopVoiceCloner:
    """空操作克隆器 — 克隆被禁用时的占位实现"""

    def prepare(self, voice_path: str) -> bool:
        return True

    def clone(self, tts_audio_path: str, output_dir: str) -> Optional[str]:
        return tts_audio_path

    def device_info(self) -> dict:
        return {"device": "none", "vram_mb": 0, "mode": "disabled", "concurrency": 0}

    def cleanup(self) -> None:
        pass
