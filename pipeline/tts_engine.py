"""
TTS 引擎抽象层 — BaseTTSEngine Protocol + EmotionStyle

定义 TTS 引擎的统一接口，新增引擎只需实现 BaseTTSEngine Protocol。
情感克隆通过 EmotionStyle 参数传入，引擎自行判断支持模式。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable, List


@dataclass
class EmotionStyle:
    """情感风格参数。支持两种模式：

    1. **参数式**: style_name + style_degree
       通过指定情感标签和强度来控制合成语音的情感。
       适用于 Azure TTS 等内置情感支持的引擎。
       示例: style="cheerful", style_degree=1.5

    2. **参考音频式**: reference_audio + reference_text
       通过一段带目标情感的参考音频来迁移情感。
       适用于 OpenVoice、StyleTTS 等支持情感迁移的引擎。
       示例: reference_audio="happy_sample.wav"

    两种模式可同时使用（若引擎支持），引擎按自己的逻辑合并处理。
    """

    # ── 参数式情感 ────────────────────────────
    style_name: Optional[str] = None
    """情感标签。常用值: cheerful, sad, angry, calm, fearful, surprised, excited"""

    style_degree: Optional[float] = None
    """情感强度。范围 0.5~2.0，1.0 为默认强度"""

    # ── 参考音频式情感 ────────────────────────
    reference_audio: Optional[str] = None
    """参考音频路径。引擎从中提取情感特征"""

    reference_text: Optional[str] = None
    """参考音频的文字内容（可选）。提供后可提升情感克隆质量"""

    # ── 角色身份（多角色情景预留） ─────────────
    role: Optional[str] = None
    """角色标识。用于多角色对话场景: "narration" | "dialogue" | "character_name" """


@runtime_checkable
class BaseTTSEngine(Protocol):
    """TTS 引擎抽象接口。

    实现此 Protocol 即可接入新的 TTS 引擎。
    无需继承，Python 结构类型系统会自动匹配。

    情感克隆通过 EmotionStyle 参数传入，引擎自行判断支持哪种模式：
    - 仅参数式: 引擎支持内置情感标签（如 Azure TTS）
    - 仅参考音频式: 引擎支持从参考音频迁移情感（如情感克隆引擎）
    - 两种都支持: 引擎可同时处理参数式 + 参考音频式
    - 都不支持: 基础引擎如 Edge TTS，直接忽略 emotion 参数
    """

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional[EmotionStyle] = None,
    ) -> float:
        """合成语音，返回音频时长（秒）。

        Args:
            text: 要合成的文本
            output_path: 输出文件路径
            rate: 语速调整，格式如 "+30%", "-10%"
                  （引擎内部自行映射到平台特有的语速参数）
            emotion: 情感风格参数（可选）
                     引擎不支持情感克隆时直接忽略

        Returns:
            音频时长（秒）

        Raises:
            RuntimeError: 合成失败（引擎内部应实现自动重试）
        """
        ...

    def get_voices(self) -> List[str]:
        """获取可用音色列表（可选实现）。

        Returns:
            可用音色名称列表。默认返回空列表。
        """
        return []

    def supports_rate(self) -> bool:
        """引擎是否支持语速调节。

        EdgeTTS 原生支持 rate 参数；ChatTTS 不支持（返回 False），
        依赖下游视频变速补偿。
        """
        return True

    def supports_emotion(self) -> bool:
        """引擎是否支持情感克隆。

        返回 True 的引擎应同时实现 emotion_modes()。
        """
        return False

    def emotion_modes(self) -> List[str]:
        """返回支持的情感克隆模式。

        可能值:
        - "parameter": 参数式，通过 style_name + style_degree 控制
        - "reference": 参考音频式，通过 reference_audio 迁移情感
        - "both": 两种都支持

        Returns:
            支持的模式列表。默认返回空列表。
        """
        return []


class NoopTTSEngine:
    """空 TTS 引擎 — 用于测试和占位。

    不执行任何实际合成，直接创建空文件并返回固定时长。
    """

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional[EmotionStyle] = None,
    ) -> float:
        """创建空文件并返回固定时长 1 秒。"""
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        # 创建一个极短的有效 WAV 文件头（44 字节）
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 44)
        return 1.0

    def get_voices(self) -> List[str]:
        return []

    def supports_rate(self) -> bool:
        return False

    def supports_emotion(self) -> bool:
        return True

    def emotion_modes(self) -> List[str]:
        return ["parameter", "reference"]


def is_tts_engine(obj) -> bool:
    """判断对象是否符合 BaseTTSEngine Protocol。"""
    return isinstance(obj, BaseTTSEngine)
