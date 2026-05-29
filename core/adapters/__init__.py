"""core/adapters — 引擎适配层 (CLI Runtime 计划书 §5)

每个 Adapter 负责将原始引擎输出转为 Patch 列表。
Adapter 不做 IR 操作，只做格式转换。
v2: 所有 Adapter 实现 AdapterProtocol 统一接口。
"""
from core.adapters.protocol import (
    AdapterProtocol, AdapterCapability, AdapterResult,
    ErrorCategory, ResourceRequirement, AdapterRegistry,
)
from core.adapters.whisper_adapter import WhisperAdapter, EngineContext
from core.adapters.wav2vec2_adapter import Wav2Vec2Adapter
from core.adapters.pyannote_adapter import PyannoteAdapter
from core.adapters.chattts_adapter import ChatTTSAdapter, TTSSegmentContext
from core.adapters.cosyvoice_adapter import CosyVoiceAdapter, CosyVoiceSegmentContext
from core.adapters.indextts_adapter import IndexTTSAdapter, IndexTTSSegmentContext
from core.adapters.openvoice_adapter import OpenVoiceTransferAdapter, OpenVoiceTransferContext
from core.adapters.edge_tts_adapter import EdgeTTSAdapter, EdgeTTSSegmentContext
from core.adapters.media_validator_adapter import MediaValidatorAdapter, AudioDefectContext
from core.adapters.demucs_adapter import DemucsAdapter, DemucsContext
from core.adapters.vad_boundary_adapter import VADBoundaryAdapter, VADBoundaryContext
from core.adapters.minilm_adapter import MiniLMAdapter, MiniLMContext
from core.adapters.ppl_adapter import PPLAdapter, PPLContext
from core.adapters.emotion_recognizer_adapter import EmotionRecognizerAdapter, EmotionRecognizerContext

__all__ = [
    "AdapterProtocol", "AdapterCapability", "AdapterResult",
    "ErrorCategory", "ResourceRequirement", "AdapterRegistry",
    "WhisperAdapter", "Wav2Vec2Adapter", "PyannoteAdapter",
    "ChatTTSAdapter", "TTSSegmentContext", "EngineContext",
    "CosyVoiceAdapter", "CosyVoiceSegmentContext",
    "IndexTTSAdapter", "IndexTTSSegmentContext",
    "OpenVoiceTransferAdapter", "OpenVoiceTransferContext",
    "EdgeTTSAdapter", "EdgeTTSSegmentContext",
    "MediaValidatorAdapter", "AudioDefectContext",
    "DemucsAdapter", "DemucsContext",
    "VADBoundaryAdapter", "VADBoundaryContext",
    "MiniLMAdapter", "MiniLMContext",
    "PPLAdapter", "PPLContext",
    "EmotionRecognizerAdapter", "EmotionRecognizerContext",
]
