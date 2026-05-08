"""
适配器 — TTSAdapter

提供与旧 `SrtTxtToAudio` 兼容的接口，内部使用新模块（Task 14）。

用法（与旧代码完全兼容）:
```python
from pipeline.tts_adapter import TTSAdapter
tts = TTSAdapter(video_path=..., ...)
tts.model_version = "v2"
tts.EdgeTTS_TXT_To_Audio()
```
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from pipeline.tts_config import TTSConfig

from pipeline.logger import get_logger

logger = get_logger(__name__)
from pipeline.tts_pipeline import TtsPipeline
from pipeline.tts_resume import ResumeManager


class TTSAdapter:
    """与旧 SrtTxtToAudio 兼容的适配器。

    保持 interface 兼容：
    - `__init__(...)` 参数与旧版一致
    - `model_version` 属性
    - `EdgeTTS_TXT_To_Audio()` 方法

    内部委托到 TtsPipeline。
    """

    def __init__(
        self,
        video_path: str,
        video_instrumental_path: str,
        chinese_srt_path: str,
        english_srt_path: str,
        TTS_audio_output_path: str,
        threading_workers: int = 7,
        clone_color: bool = False,
        speed_max: int = 7,
        edgeTTS_vocal: str = "zh-CN-XiaoxiaoNeural",
        base_speed: int = 3,
        caption: bool = True,
        voice: Optional[str] = None,
    ):
        # 构建旧参数映射
        self._config = TTSConfig(
            engine_type="edge",
            voice=edgeTTS_vocal,
            base_speed=speed_max * 10,
            max_speed=speed_max * 10,
            speed_tolerance=0.15,
            threading_workers=threading_workers,
            enable_caption=caption,
            enable_openvoice=clone_color,
            openvoice_model_version="v2",
            output_dir=os.path.dirname(TTS_audio_output_path) or "file",
            audio_codec="pcm_s32le",
            audio_bitrate="192k",
            video_bitrate="10M",
        )
        # 字体路径
        self._config.caption_font = "./models/font/Minecraft_font/5_Minecraft_AE_zh_en.ttf"

        self._pipeline = TtsPipeline(self._config)

        self.video_path = video_path
        self.video_instrumental_path = video_instrumental_path
        self.chinese_srt_path = chinese_srt_path
        self.english_srt_path = english_srt_path
        self.TTS_audio_output_path = TTS_audio_output_path

        # 旧版兼容属性
        self.model_version = "v2"
        self.speed_max = speed_max * 10
        self.base_speed = base_speed * 10
        self.vocal = edgeTTS_vocal
        self.clone_color = clone_color
        self.caption = caption
        self.threading_workers = threading_workers

    def EdgeTTS_TXT_To_Audio(self):
        """与旧版完全兼容的入口方法。

        内部委托到 TtsPipeline.run()。
        """
        self._pipeline.run(
            video_path=self.video_path,
            instrumental_path=self.video_instrumental_path,
            chinese_srt_path=self.chinese_srt_path,
            english_srt_path=self.english_srt_path,
        )
        logger.info(f"TTS 处理完成: {self.TTS_audio_output_path}")


# ── 便捷工厂函数 ──────────────────────────────────────

def create_adapter_from_config(config_path: str, **overrides) -> TTSAdapter:
    """从 YAML 配置创建 TTSAdapter。

    Args:
        config_path: tts.yaml 路径
        **overrides: 覆盖配置中的参数

    Returns:
        TTSAdapter 实例
    """
    cfg = TTSConfig.from_yaml(config_path)
    for k, v in overrides.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)

    return TTSAdapter(
        video_path=cfg.get("video_path", ""),
        video_instrumental_path=cfg.get("instrumental_path", ""),
        chinese_srt_path=cfg.get("chinese_srt_path", ""),
        english_srt_path=cfg.get("english_srt_path", ""),
        TTS_audio_output_path=cfg.output_dir,
        threading_workers=cfg.threading_workers,
        clone_color=cfg.enable_openvoice,
        speed_max=cfg.max_speed // 10,
        edgeTTS_vocal=cfg.voice,
        base_speed=cfg.base_speed // 10,
        caption=cfg.enable_caption,
    )
