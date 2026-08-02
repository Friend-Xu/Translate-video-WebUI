"""
core — IR v2 系统迁移

Phase 1: core/ir/     — 纯不可变数据定义（frozen dataclass，零 Pydantic）
Phase 2: core/runtime/ — 状态层 + Patch 引擎 + Synthesis（零 deepcopy）
Phase 3: core/engine/  — Pass 调度 + 引擎适配协议
Phase 4: core/adapters/ — 引擎适配层 (Whisper, wav2vec2, pyannote, TTS)

v2.1: 九语义槽位 + Timeline 中间层 + 三类版本管理 + ASR 域适配器

旧系统 (timeline/) 保持不变，永远可运行。
新系统以并行影子模式运行，双写输出，比对通过后逐步切换。
"""

from core.ir import TimelineEventIR, SpeakerNodeIR, TimelineProjectIR
from core.ir.version import SCHEMA_VERSION, IR_VERSION, PATCH_VERSION
from core.runtime import (
    TimelineEventState,
    TimelineProjectState,
    Patch,
    OpCode,
    PatchEngine,
    SynthesisEngine,
)
from core.adapters import WhisperAdapter, Wav2Vec2Adapter, PyannoteAdapter, EngineContext
from core.scoring import ASRScorer, ASRScore
from core.speaker import (
    SpeakerEmbeddingExtractor, SpeakerClustering, ClusterResult,
    SpeakerDriftDetector, DriftCandidate,
)

__all__ = [
    # IR
    "TimelineEventIR",
    "SpeakerNodeIR",
    "TimelineProjectIR",
    # Version
    "SCHEMA_VERSION",
    "IR_VERSION",
    "PATCH_VERSION",
    # Runtime
    "TimelineEventState",
    "TimelineProjectState",
    "Patch",
    "OpCode",
    "PatchEngine",
    "SynthesisEngine",
    # Adapters
    "WhisperAdapter",
    "Wav2Vec2Adapter",
    "PyannoteAdapter",
    "EngineContext",
    # Scoring
    "ASRScorer",
    "ASRScore",
    # Speaker
    "SpeakerEmbeddingExtractor",
    "SpeakerClustering",
    "ClusterResult",
    "SpeakerDriftDetector",
    "DriftCandidate",
]
