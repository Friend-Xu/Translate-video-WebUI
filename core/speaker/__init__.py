"""core/speaker — 说话人身份管理模块 (Chapter 4, Chapter 7)

- SpeakerEmbeddingExtractor: 提取 speaker embedding + 质心计算 (Ch4)
- SpeakerClustering: 基于 embedding 的层次聚类 + auto-merge (Ch4)
- SpeakerDriftDetector: 三信号身份漂移检测 (Ch4)
- VoiceMemoryIndex: 三层声纹资产索引系统 (Ch7)
"""
from core.speaker.embedding import SpeakerEmbeddingExtractor
from core.speaker.clustering import SpeakerClustering, ClusterResult
from core.speaker.drift import SpeakerDriftDetector, DriftCandidate
from core.speaker.voice_memory import (
    VoiceMemoryIndex, VoicePrototype, VoiceInstance, VoiceAsset,
)

__all__ = [
    "SpeakerEmbeddingExtractor",
    "SpeakerClustering",
    "ClusterResult",
    "SpeakerDriftDetector",
    "DriftCandidate",
    "VoiceMemoryIndex",
    "VoicePrototype",
    "VoiceInstance",
    "VoiceAsset",
]
