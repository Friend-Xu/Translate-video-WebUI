"""
ChatTTS 离线引擎实现 — ChatTTSEngine

基于 ChatTTS（2noise/ChatTTS）的离线语音合成引擎。
一次加载模型，后续调用复用缓存。spk_emb 在首次合成时生成并缓存，
确保同一视频所有段落的音色一致。

用法:
    engine = ChatTTSEngine(speaker_seed=42)
    duration = engine.synthesize("你好世界", "output.wav")
    engine.reset_speaker(seed=99)  # 换一个声音
"""

from __future__ import annotations

import os
import random
from typing import List, Optional

import numpy as np

from pipeline.logger import get_logger

logger = get_logger(__name__)


class ChatTTSEngine:
    """ChatTTS 离线 TTS 引擎。

    模型懒加载：第一次 synthesize 调用时加载，之后复用。
    spk_emb 缓存：首次合成时生成说话人嵌入，后续段落复用，
    确保同一视频所有字幕段落音色一致。

    用法:
        engine = ChatTTSEngine(speaker_seed=42)
        engine.synthesize("你好", "output.wav")
        engine.reset_speaker(seed=None)  # 随机换音色
    """

    def __init__(
        self,
        speaker_seed: Optional[int] = None,
        model_source: str = "local",
        model_path: Optional[str] = None,
        use_decoder: bool = True,
        sample_rate: int = 24000,
    ):
        self._speaker_seed = speaker_seed
        self._model_source = model_source
        self._model_path = model_path
        self._use_decoder = use_decoder
        self._sample_rate = sample_rate

        self._chat: Optional["ChatTTS.Chat"] = None  # type: ignore
        self._loaded = False
        self._spk_emb = None  # 缓存的说话人嵌入

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    @property
    def speaker_seed(self) -> Optional[int]:
        return self._speaker_seed

    def reset_speaker(self, seed: Optional[int] = None) -> None:
        """更换说话人：清除缓存嵌入并重新生成。

        seed=None 时随机生成新音色；不需重新加载模型。
        """
        self._speaker_seed = seed
        self._spk_emb = None

    def _load_model(self) -> None:
        """懒加载 ChatTTS 模型（不含 speaker 初始化）。"""
        if self._loaded and self._chat is not None:
            return

        from pipeline.model_manager import ModelManager

        import ChatTTS
        from ChatTTS import Chat

        chat = Chat()
        load_kwargs = {"source": self._model_source, "compile": False}

        if self._model_source == "custom" and self._model_path:
            load_kwargs["custom_path"] = self._model_path
        elif self._model_source == "local":
            # local: 使用 models/ChatTTS/（ModelManager 管理的目录）
            status = ModelManager.check("chattts")
            if status.exists:
                load_kwargs["custom_path"] = status.path

        chat.load(**load_kwargs)
        self._chat = chat
        self._loaded = True
        logger.info("ChatTTS 模型加载完成")

    def _ensure_spk_emb(self):
        """生成并缓存说话人嵌入。首次调用时执行。

        指定 seed → np.random.seed() 固定 → 确定性音色
        seed=None → 系统随机 seed → 随机但同视频一致的音色
        """
        if self._spk_emb is not None:
            return
        assert self._chat is not None

        if self._speaker_seed is not None:
            np.random.seed(self._speaker_seed)
        else:
            # 随机生成 seed 并保存，确保前端能获取到种子值
            self._speaker_seed = random.randint(0, 2 ** 31 - 1)
            np.random.seed(self._speaker_seed)

        self._spk_emb = self._chat.sample_random_speaker()

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional["EmotionStyle"] = None,  # type: ignore
    ) -> float:
        """合成语音，返回音频时长（秒）。

        rate/emotion 参数接受但忽略（ChatTTS 不支持）。
        """
        import ChatTTS
        import soundfile as sf
        from ChatTTS import Chat

        self._load_model()
        self._ensure_spk_emb()
        assert self._chat is not None
        assert self._spk_emb is not None

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            params_infer_code = Chat.InferCodeParams()
            params_infer_code.spk_emb = self._spk_emb

            wavs = self._chat.infer(
                text,
                skip_refine_text=False,
                use_decoder=self._use_decoder,
                do_text_normalization=True,
                split_text=False,
                params_infer_code=params_infer_code,
            )

            if not wavs or len(wavs) == 0:
                raise RuntimeError("ChatTTS 推理返回空结果")

            audio_data = wavs[0]
            sf.write(output_path, audio_data, self._sample_rate)
            return float(len(audio_data) / self._sample_rate)

        except Exception as e:
            raise RuntimeError(f"ChatTTS 合成失败: {e}") from e

    def get_voices(self) -> List[str]:
        return []

    def supports_emotion(self) -> bool:
        return False

    def emotion_modes(self) -> List[str]:
        return []


class ChatTTSEngineFactory:
    """ChatTTSEngine 工厂方法。"""

    @staticmethod
    def from_config(config) -> ChatTTSEngine:
        return ChatTTSEngine(
            speaker_seed=getattr(config, "chattts_speaker_seed", None),
            model_source=getattr(config, "chattts_model_source", "local"),
            model_path=getattr(config, "chattts_model_path", None),
        )
