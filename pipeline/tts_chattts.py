"""
ChatTTS 离线引擎实现 — ChatTTSEngine

基于 ChatTTS（2noise/ChatTTS）的离线语音合成引擎。
一次加载模型，后续调用复用缓存。

ChatTTS 是专为对话场景设计的轻量中文 TTS 引擎。
中文自然度高，MIT 协议可商用。

用法:
    engine = ChatTTSEngine()
    duration = engine.synthesize("你好世界", "output.wav")
"""

from __future__ import annotations

import os
import warnings
from typing import List, Optional

import numpy as np


class ChatTTSEngine:
    """ChatTTS 离线 TTS 引擎。

    模型懒加载：第一次 synthesize 调用时加载，之后复用。
    支持中文/英文混合合成，不需要网络连接。

    用法:
        engine = ChatTTSEngine()
        engine.synthesize("你好", "output.wav")
    """

    def __init__(
        self,
        speaker_seed: Optional[int] = None,
        model_source: str = "local",
        model_path: Optional[str] = None,
        use_decoder: bool = True,
        sample_rate: int = 24000,
    ):
        """
        Args:
            speaker_seed: 说话人随机种子（固定种子保持音色一致）
            model_source: 模型来源 "local" | "huggingface" | "custom"
            model_path: 自定义模型路径（model_source="custom" 时需要）
            use_decoder: 是否使用解码器（True 产生更高质量音频）
            sample_rate: 采样率（ChatTTS 默认为 24000）
        """
        self._speaker_seed = speaker_seed
        self._model_source = model_source
        self._model_path = model_path
        self._use_decoder = use_decoder
        self._sample_rate = sample_rate

        self._chat: Optional["ChatTTS.Chat"] = None  # type: ignore
        self._loaded = False

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    def _load_model(self) -> None:
        """懒加载 ChatTTS 模型。"""
        if self._loaded and self._chat is not None:
            return

        import ChatTTS
        from ChatTTS import Chat

        # 使用模块级 HF 镜像配置
        chat = Chat()
        load_kwargs = {
            "source": self._model_source,
            "compile": False,
        }

        if self._model_source == "custom" and self._model_path:
            load_kwargs["custom_path"] = self._model_path

        chat.load(**load_kwargs)
        self._chat = chat
        self._loaded = True
        print("[ChatTTS] 模型加载完成")

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional["EmotionStyle"] = None,  # type: ignore
    ) -> float:
        """合成语音，返回音频时长（秒）。

        Args:
            text: 要合成的文本
            output_path: 输出 WAV 文件路径
            rate: 语速调整（ChatTTS 不支持实时变速，忽略该参数）
            emotion: 情感参数（ChatTTS 不支持，忽略）

        Returns:
            音频时长（秒）

        Raises:
            RuntimeError: 合成失败
        """
        import ChatTTS
        import soundfile as sf
        from ChatTTS import Chat

        self._load_model()
        assert self._chat is not None

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            # 设置说话人种子（保持音色一致）
            params_infer_code = Chat.InferCodeParams()
            if self._speaker_seed is not None:
                params_infer_code.spk_emb = self._chat.sample_random_speaker()
                # 通过设置随机种子来固定说话人
                np.random.seed(self._speaker_seed)

            # 推理
            wavs = self._chat.infer(
                text,
                skip_refine_text=False,
                use_decoder=self._use_decoder,
                do_text_normalization=True,
                split_text=False,  # 单个文本不分段
                params_infer_code=params_infer_code,
            )

            if not wavs or len(wavs) == 0:
                raise RuntimeError("ChatTTS 推理返回空结果")

            # wavs[0] 是 numpy 数组（float32），范围 [-1, 1]
            audio_data = wavs[0]

            # 写入 WAV 文件
            sf.write(output_path, audio_data, self._sample_rate)

            # 计算时长
            duration = len(audio_data) / self._sample_rate
            return float(duration)

        except Exception as e:
            raise RuntimeError(f"ChatTTS 合成失败: {e}") from e

    def get_voices(self) -> List[str]:
        """ChatTTS 不提供命名音色列表。使用 speaker_seed 控制。"""
        return []

    def supports_emotion(self) -> bool:
        """ChatTTS 不支持情感克隆。"""
        return False

    def emotion_modes(self) -> List[str]:
        return []


class ChatTTSEngineFactory:
    """ChatTTSEngine 工厂方法。"""

    @staticmethod
    def from_config(config) -> ChatTTSEngine:
        """从 TTSConfig 创建 ChatTTSEngine。

        Args:
            config: TTSConfig 实例

        Returns:
            ChatTTSEngine 实例
        """
        return ChatTTSEngine(
            speaker_seed=getattr(config, "chattts_speaker_seed", None),
            model_source=getattr(config, "chattts_model_source", "local"),
            model_path=getattr(config, "chattts_model_path", None),
        )
