"""
OpenVoice 声音克隆器

从原 `SrtTxtToAudio` 中的声音克隆逻辑提取。
原代码在 __init__ 中检测 clone_color 路径，在 slow_down/current 中用
OpenVoice API 合成。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class OpenVoiceConfig:
    """OpenVoice 声音克隆配置"""
    enabled: bool = False
    model_version: str = "v2"
    color_audio_path: str = "./speakers/Color_audio.WAV"
    vocal_output_dir: str = "file/OpenVoice_file"
    vad_duration: int = 8  # VAD 分段时长（秒）
    error_log_path: str = "./file/openvoice_error_log.txt"


class OpenVoiceCloner(Protocol):
    """OpenVoice 声音克隆接口 Protocol。

    与原版签名一致: `clone(tts_audio_path, output_dir) -> cloned_audio_path`
    """

    def clone(self, tts_audio_path: str, output_dir: str) -> Optional[str]:
        """克隆声音。

        Args:
            tts_audio_path: TTS 生成的音频路径
            output_dir: 输出目录

        Returns:
            克隆后的音频路径，失败返回 None
        """
        ...


class NoopOpenVoiceCloner:
    """哑克隆器 — 克隆被禁用时的占位实现"""

    def clone(self, tts_audio_path: str, output_dir: str) -> Optional[str]:
        return None


class ExtraVocalCloner:
    """基于 Extra_Vocal 模块的 OpenVoice 声音克隆。

    从原版 __init__ 和 slow_down/current 调用中提取。
    内置 speaker embedding 缓存：同次会话中多次 clone() 只提取一次音色嵌入。
    """

    def __init__(self, config: OpenVoiceConfig):
        self.config = config
        self._prepared = False
        self._embedding = None  # speaker embedding 缓存

    def prepare(self, voice_path: Optional[str] = None) -> bool:
        """准备音色参考文件。

        切换音色参考时清空 embedding 缓存。

        对应原版 __init__ 中：
        ```python
        if clone_color:
            if voice is None:
                voice = f"{os.path.dirname(self.video_path)}\\1_{...}"
            from speakers import Extra_Vocal
            Extra_Vocal.extra_vocal(voice, self.color_path, vad_duration=8)
        ```

        Args:
            voice_path: 人声 WAV 路径（来自 vocals 提取）
        """
        if self._prepared:
            self._embedding = None
            return True

        color_path = self.config.color_audio_path
        if os.path.isfile(color_path):
            print("存在音色")
            self._prepared = True
            self._embedding = None
            return True

        if voice_path is None or not os.path.isfile(voice_path):
            print("未提供有效的人声路径，跳过声音克隆准备")
            return False

        try:
            from speakers import Extra_Vocal
            print(f"提取音色参考：{voice_path} -> {color_path}")
            Extra_Vocal.extra_vocal(
                voice_path, color_path, vad_duration=self.config.vad_duration
            )
            self._prepared = True
            self._embedding = None
            return True
        except Exception as e:
            self._log_error(f"准备音色失败: {e}")
            return False

    def clone(self, tts_audio_path: str, output_dir: str) -> Optional[str]:
        """克隆声音。

        对应原版 slow_down/current_video_to_file 中的 clone_color 调用。
        内置 embedding 缓存：同次会话多次克隆只调用一次 se_extractor。

        Args:
            tts_audio_path: TTS 音频路径
            output_dir: 输出目录

        Returns:
            克隆后音频路径，失败返回 None
        """
        try:
            from openvoice import se_extractor, api
            os.makedirs(output_dir, exist_ok=True)

            # 缓存 speaker embedding，避免重复计算
            if self._embedding is None:
                self._embedding = se_extractor.get_se(
                    self.config.color_audio_path,
                    api.v2.tone_color_converter,
                    vad=True,
                )

            save_path = os.path.join(
                output_dir,
                f"cloned_{os.path.basename(tts_audio_path)}",
            )
            api.v2.tone_color_converter.convert(
                audio_src_path=tts_audio_path,
                src_se=self._embedding,
                dst_se=self._embedding,
                output_path=save_path,
            )
            return save_path
        except Exception as e:
            # 第一次失败时清空缓存，下次会重试
            self._embedding = None
            self._log_error(f"声音克隆失败 [{tts_audio_path}]: {e}")
            return None

    def _log_error(self, message: str):
        """写入错误日志（对应原版 openvoice_error_log.txt）"""
        log_path = self.config.error_log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{message}\n")
