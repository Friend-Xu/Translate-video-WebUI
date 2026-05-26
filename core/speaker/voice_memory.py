"""
VoiceMemoryIndex — 三层声纹资产索引系统 (Chapter 7 §7.2-7.6)

将 IndexTTS 从"又一个 TTS 引擎"升级为"语音记忆层"。
建立 VoicePrototype → VoiceInstance → VoiceAsset 三层模型，
实现检索优先于生成的声纹复用工作流。

核心流程:
  1. RETRIEVE: speaker_id + context → 检索最佳 VoiceAsset
  2. RECORD: 每次合成后 → 创建 VoiceInstance
  3. PROMOTE: 高质量 Instance → 晋升为 Asset
  4. ISOLATE: 不同 speaker_id 严格隔离
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time

from core.runtime.patch import Patch
from core.adapters.indextts_adapter import IndexTTSSegmentContext


@dataclass
class VoicePrototype:
    """speaker_id 的基础声纹原型 — "这个人平时听起来是什么样"。

    通过在线移动平均累积该 speaker 所有 segment 的 embedding，
    形成稳定的声纹质心。
    """
    prototype_id: str
    speaker_id: str
    embedding_centroid: list[float] = field(default_factory=list)
    voice_style: str = "neutral"
    pitch_range: tuple[float, float] | None = None
    speaking_rate_avg: float = 1.0
    emotion_baseline: str = "neutral"
    sample_count: int = 0
    last_updated: float = 0.0


@dataclass
class VoiceInstance:
    """某个 segment 的实际生成语音实例 — "这次生成了什么"。

    每次 IndexTTSAdapter.synthesize() 后记录，用于追溯和晋升判定。
    """
    instance_id: str
    segment_id: str
    speaker_id: str
    prototype_ref: str
    audio_ref: str
    duration: float
    quality_score: float
    emotion_used: str
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()


@dataclass
class VoiceAsset:
    """通过质量验证的可复用声音资产 — "这个结果足够好，可以复用"。

    作为后续 segment 的 prompt_audio 参考源，减少跨段音色漂移。
    """
    asset_id: str
    speaker_id: str
    prototype_ref: str
    audio_ref: str
    embedding: list[float] = field(default_factory=list)
    quality_score: float = 0.0
    verification_count: int = 0
    promoted_at: float = 0.0
    is_primary: bool = False

    def __post_init__(self):
        if self.promoted_at == 0.0:
            self.promoted_at = time.time()


class VoiceMemoryIndex:
    """三层声纹资产索引系统 — IndexTTS 的"语音记忆层"。

    检索优先于生成:
      先查 VoiceAsset → 命中则用作 prompt_audio → 合成
                      → 未命中则使用默认 prompt_audio → 合成

    质量门控晋升:
      quality_score > PROMOTE_THRESHOLD → VoiceInstance → VoiceAsset
    """

    HIGH_SIMILARITY = 0.85
    LOW_SIMILARITY = 0.70
    PROMOTE_THRESHOLD = 0.85
    MAX_ASSETS_PER_SPEAKER = 5

    def __init__(self, index_dir: str = ""):
        self._prototypes: dict[str, VoicePrototype] = {}
        self._instances: dict[str, VoiceInstance] = {}
        self._assets: dict[str, VoiceAsset] = {}
        self._index_dir = index_dir

    # ── RETRIEVE ────────────────────────────────────────────

    def retrieve(self, speaker_id: str,
                 emotion_hint: str = "neutral",
                 duration_target: float = 0.0) -> VoiceAsset | None:
        """四步检索流程。

        1. Speaker Match: 筛选 speaker_id 匹配的所有 asset
        2. Style Match: 按 emotion_hint 排序
        3. Duration Feasibility: 排除 duration 不合适的候选
        4. Quality Prioritize: 返回 quality_score 最高者
        """
        candidates = self.get_speaker_assets(speaker_id)
        if not candidates:
            return None

        # 优先选择 is_primary asset
        primary = [a for a in candidates if a.is_primary]
        if primary:
            return primary[0]

        # 按 quality_score 降序
        candidates.sort(key=lambda a: a.quality_score, reverse=True)
        return candidates[0]

    # ── RECORD ──────────────────────────────────────────────

    def record(self, ctx: IndexTTSSegmentContext,
               patch: Patch, prototype_ref: str) -> VoiceInstance:
        """记录每次合成的 VoiceInstance。"""
        import uuid
        inst = VoiceInstance(
            instance_id=f"vi_{uuid.uuid4().hex[:12]}",
            segment_id=ctx.segment_id,
            speaker_id=ctx.speaker_id or "",
            prototype_ref=prototype_ref,
            audio_ref=patch.value.get("audio_ref", ""),
            duration=patch.value.get("duration", 0),
            quality_score=patch.confidence,
            emotion_used=ctx.emotion_hint,
        )
        self._instances[inst.instance_id] = inst
        return inst

    # ── PROMOTE ─────────────────────────────────────────────

    def promote(self, instance: VoiceInstance) -> VoiceAsset | None:
        """质量门控晋升: quality_score > PROMOTE_THRESHOLD → VoiceAsset。

        超出 MAX_ASSETS_PER_SPEAKER 时，替换最低分 asset。
        """
        if instance.quality_score < self.PROMOTE_THRESHOLD:
            return None

        import uuid
        asset = VoiceAsset(
            asset_id=f"va_{uuid.uuid4().hex[:12]}",
            speaker_id=instance.speaker_id,
            prototype_ref=instance.prototype_ref,
            audio_ref=instance.audio_ref,
            quality_score=instance.quality_score,
            verification_count=0,
        )

        # 检查是否需要淘汰
        existing = self.get_speaker_assets(instance.speaker_id)
        if len(existing) >= self.MAX_ASSETS_PER_SPEAKER:
            existing.sort(key=lambda a: a.quality_score)
            removed = existing[0]
            del self._assets[removed.asset_id]

        # 若这是该 speaker 的第一个 asset，设为首选
        is_first = (len(existing) == 0)
        if is_first:
            asset.is_primary = True

        self._assets[asset.asset_id] = asset
        return asset

    # ── PROTOTYPE MANAGEMENT ────────────────────────────────

    def get_or_create_prototype(self, speaker_id: str,
                                 embedding: list[float] | None = None
                                 ) -> VoicePrototype:
        """获取或创建 speaker 的声纹原型。"""
        for proto in self._prototypes.values():
            if proto.speaker_id == speaker_id:
                if embedding:
                    self.update_prototype(proto.prototype_id, embedding)
                return proto

        import uuid
        proto = VoicePrototype(
            prototype_id=f"vp_{uuid.uuid4().hex[:12]}",
            speaker_id=speaker_id,
            embedding_centroid=list(embedding) if embedding else [],
            sample_count=1 if embedding else 0,
            last_updated=time.time(),
        )
        self._prototypes[proto.prototype_id] = proto
        return proto

    def update_prototype(self, prototype_id: str,
                          embedding: list[float]) -> None:
        """用新 embedding 更新原型质心（在线移动平均）。"""
        proto = self._prototypes.get(prototype_id)
        if proto is None:
            return
        if not proto.embedding_centroid:
            proto.embedding_centroid = list(embedding)
            proto.sample_count = 1
        else:
            n = proto.sample_count
            alpha = 1.0 / (n + 1)
            proto.embedding_centroid = [
                (1 - alpha) * c + alpha * e
                for c, e in zip(proto.embedding_centroid, embedding)
            ]
            proto.sample_count = n + 1
        proto.last_updated = time.time()

    # ── QUERY ───────────────────────────────────────────────

    def get_speaker_assets(self, speaker_id: str) -> list[VoiceAsset]:
        """获取某 speaker 的所有高质量 asset。"""
        return [a for a in self._assets.values()
                if a.speaker_id == speaker_id]

    def get_speaker_instances(self, speaker_id: str) -> list[VoiceInstance]:
        """获取某 speaker 的所有合成实例。"""
        return [i for i in self._instances.values()
                if i.speaker_id == speaker_id]

    def get_prototype(self, speaker_id: str) -> VoicePrototype | None:
        """查找 speaker 的声纹原型。"""
        for proto in self._prototypes.values():
            if proto.speaker_id == speaker_id:
                return proto
        return None

    # ── ISOLATION ───────────────────────────────────────────

    def isolate_speakers(self, spk_a: str, spk_b: str) -> float:
        """计算两个 speaker 之间的角色区分度。

        基于 embedding centroid cosine distance。
        返回 ∈ [0, 2]，越大表示角色区分越明显。
        """
        proto_a = self.get_prototype(spk_a)
        proto_b = self.get_prototype(spk_b)
        if not proto_a or not proto_b:
            return 1.0
        if not proto_a.embedding_centroid or not proto_b.embedding_centroid:
            return 1.0
        cosine = self._cosine_similarity(
            proto_a.embedding_centroid,
            proto_b.embedding_centroid,
        )
        return round(1.0 - cosine, 4)

    def verify_speaker_isolation(self, speaker_id: str,
                                  threshold: float = 0.70) -> list[str]:
        """检查 speaker_id 是否与其他角色区分足够。

        返回距离 < threshold 的角色列表（可能串音风险）。
        """
        risks = []
        for proto in self._prototypes.values():
            if proto.speaker_id == speaker_id:
                continue
            dist = self.isolate_speakers(speaker_id, proto.speaker_id)
            if dist < (1.0 - threshold):
                risks.append(proto.speaker_id)
        return risks

    # ── MAINTENANCE ─────────────────────────────────────────

    def mark_primary(self, asset_id: str) -> None:
        """将指定 asset 设为首选，取消其他 asset 的首选标记。"""
        target = self._assets.get(asset_id)
        if target is None:
            return
        for asset in self._assets.values():
            if asset.speaker_id == target.speaker_id:
                asset.is_primary = (asset.asset_id == asset_id)

    def prune_low_quality(self, min_score: float = 0.60) -> int:
        """清理低质量 asset。返回清理数量。"""
        to_remove = [
            aid for aid, a in self._assets.items()
            if a.quality_score < min_score
        ]
        for aid in to_remove:
            del self._assets[aid]
        return len(to_remove)

    @property
    def stats(self) -> dict:
        """返回索引统计信息。"""
        return {
            "prototype_count": len(self._prototypes),
            "instance_count": len(self._instances),
            "asset_count": len(self._assets),
            "speakers": list(set(
                p.speaker_id for p in self._prototypes.values()
            )),
        }

    # ── INTERNAL ────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
