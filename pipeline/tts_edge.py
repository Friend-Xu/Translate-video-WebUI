# -*- coding: utf-8 -*-
"""Edge-TTS 引擎封装。

对应原 `SrtTxtToAudio.TXT_Edge_TTS()`。
保留原版情感参数接口（传入即静默忽略）。
"""

from typing import Optional
from .tts_engine import BaseTTSEngine, EmotionStyle
import os

from pipeline.logger import get_logger

logger = get_logger(__name__)


class EdgeTTSEngine(BaseTTSEngine):
    """Edge-TTS 语音合成引擎。

    封装 edge_tts，与原 `TXT_Edge_TTS()` 行为对齐。
    支持重试、日语发音转写标记。
    输出强制转为 PCM WAV（edge_tts 原始输出为 MP3 格式）。
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        error_log_path: str = "log/edge_tts_error_log.txt",
    ):
        self._voice = voice
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._error_log_path = error_log_path

    def _add_japanese_markers(self, text: str) -> str:
        """在原版日语文中添加 <lang> 标记。"""
        import re
        # 极简启发式：检测日语特有的字符（平假名、片假名）
        jp_pattern = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
        if jp_pattern.search(text):
            return f"<lang xml:lang=\"ja-JP\">{text}</lang>"
        return text

    @property
    def voice(self) -> str:
        return self._voice

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional[EmotionStyle] = None,
    ) -> float:
        """合成语音。

        与原 `TXT_Edge_TTS()` 行为完全一致：
        - 最多重试 3 次
        - 重试间隔 1 秒
        - 失败后写入错误日志，抛出异常
        - 输出自动转为 PCM WAV

        Args:
            text: 要合成的文本
            output_path: 输出 WAV 文件路径
            rate: 语速调整，如 "+30%", "+0%", "-10%"
            emotion: 情感参数（Edge TTS 不支持，直接忽略）

        Returns:
            音频时长（秒）

        Raises:
            RuntimeError: 所有重试都失败后抛出
        """
        import asyncio
        return asyncio.run(self._synthesize_async(text, output_path, rate, emotion))

    async def _synthesize_async(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional[EmotionStyle] = None,
    ) -> float:
        """异步内部实现。"""
        import edge_tts
        import subprocess
        from moviepy.audio.io.AudioFileClip import AudioFileClip

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # edge_tts 输出是 MP3 格式，即使扩展名是 .wav
        # 先保存到临时路径，再转码为 PCM WAV
        mp3_path = output_path + ".tmp.mp3"

        attempts = 0
        last_exception: Optional[Exception] = None

        while attempts < self._max_retries:
            try:
                tts = edge_tts.Communicate(
                    text=text,
                    voice=self._voice,
                    rate=rate,
                    volume="+0%",
                )
                await tts.save(mp3_path)

                # 转码 MP3 → PCM WAV (s16le, 44100Hz, mono)
                # 注意: 不能降到 16kHz，否则后续 MoviePy 上采样到 44.1kHz 会引入插值伪影（电音）
                from pipeline.utils import get_ffmpeg_exe
                ffmpeg = get_ffmpeg_exe()
                subprocess.run(
                    [ffmpeg, "-y", "-i", mp3_path,
                     "-acodec", "pcm_s16le",
                     "-ar", "44100",
                     "-ac", "1",
                     output_path],
                    capture_output=True, check=True,
                )
                # 清理临时 MP3
                if os.path.isfile(mp3_path):
                    os.remove(mp3_path)

                audio = AudioFileClip(output_path)
                wave_time = audio.duration
                audio.close()
                return wave_time

            except Exception as e:
                attempts += 1
                last_exception = e
                logger.warning(
                    f"EdgeTTS 重试 (尝试 {attempts}/{self._max_retries}): {e}"
                )
                if attempts < self._max_retries:
                    import asyncio
                    await asyncio.sleep(self._retry_delay)

        # 清理残留临时文件
        if os.path.isfile(mp3_path):
            os.remove(mp3_path)

        # 所有重试失败，写错误日志
        os.makedirs(os.path.dirname(self._error_log_path) or ".", exist_ok=True)
        with open(self._error_log_path, "a", encoding="utf-8") as f:
            f.write(f"生成语音错误 text:{text}\n")

        raise RuntimeError(
            f"EdgeTTS 达到最大重试次数 ({self._max_retries})。"
            f"最后错误: {last_exception}"
        )


class EdgeTTSEngineFactory:
    """EdgeTTSEngine 工厂方法。"""

    @staticmethod
    def from_config(config) -> EdgeTTSEngine:
        """从 TTSConfig 创建引擎。"""
        return EdgeTTSEngine(
            voice=config.voice,
            max_retries=3,
            retry_delay=1.0,
        )
