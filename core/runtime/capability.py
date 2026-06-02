"""
Capability Registry — 模型/引擎资源画像注册表 (计划 §9, T6.1)

每个 Adapter 向 Registry 声明资源需求，Runtime Scheduler 据此决定
加载/卸载/驱逐/降级策略。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CapabilityEntry:
    capability_id: str
    stage: str = ""
    vram_mb: int = 0
    warmup_seconds: float = 0.0
    supports_multi_worker: bool = False
    can_fallback_cpu: bool = False
    supports_quantization: bool = False
    priority: int = 5
    depends_on: list[str] = field(default_factory=list)
    measured_vram_peak_mb: int = 0
    measured_warmup_ms: float = 0.0
    loaded: bool = False
    load_count: int = 0


class CapabilityRegistry:
    _instance: CapabilityRegistry | None = None

    def __new__(cls) -> CapabilityRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._entries: dict[str, CapabilityEntry] = {}
            cls._instance._init_defaults()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def _init_defaults(self) -> None:
        defaults = [
            CapabilityEntry(capability_id="asr.whisper", stage="extract",
                           vram_mb=2000, warmup_seconds=3.0,
                           supports_multi_worker=False, can_fallback_cpu=True,
                           supports_quantization=True, priority=8),
            CapabilityEntry(capability_id="asr.wav2vec2", stage="extract",
                           vram_mb=1500, warmup_seconds=5.0,
                           can_fallback_cpu=True, priority=5,
                           depends_on=["asr.whisper"]),
            CapabilityEntry(capability_id="speaker.pyannote", stage="extract",
                           vram_mb=1200, warmup_seconds=8.0,
                           can_fallback_cpu=True, priority=6),
            CapabilityEntry(capability_id="tts.chattts", stage="tts",
                           vram_mb=2500, warmup_seconds=10.0,
                           supports_multi_worker=True, priority=7),
            CapabilityEntry(capability_id="tts.cosyvoice", stage="tts",
                           vram_mb=3000, warmup_seconds=15.0, priority=6),
            CapabilityEntry(capability_id="tts.edge", stage="tts",
                           vram_mb=0, warmup_seconds=0.5,
                           supports_multi_worker=True, can_fallback_cpu=True, priority=3),
            CapabilityEntry(capability_id="tts.indextts", stage="tts",
                           vram_mb=2000, warmup_seconds=8.0, priority=5),
            CapabilityEntry(capability_id="emotion.minilm", stage="tts",
                           vram_mb=500, warmup_seconds=2.0,
                           can_fallback_cpu=True, priority=4),
            CapabilityEntry(capability_id="translate.llm", stage="translate",
                           vram_mb=0, warmup_seconds=0.0,
                           supports_multi_worker=True, can_fallback_cpu=True, priority=2),
            CapabilityEntry(capability_id="media.demucs", stage="extract",
                           vram_mb=1500, warmup_seconds=5.0,
                           can_fallback_cpu=True, priority=4),
        ]
        for entry in defaults:
            self._entries[entry.capability_id] = entry

    def register(self, entry: CapabilityEntry) -> None:
        self._entries[entry.capability_id] = entry

    def get(self, capability_id: str) -> CapabilityEntry | None:
        return self._entries.get(capability_id)

    def list_all(self) -> list[CapabilityEntry]:
        return list(self._entries.values())

    def list_by_stage(self, stage: str) -> list[CapabilityEntry]:
        return [e for e in self._entries.values() if e.stage == stage]

    def mark_loaded(self, capability_id: str, vram_peak_mb: int = 0) -> None:
        entry = self._entries.get(capability_id)
        if entry:
            entry.loaded = True
            entry.load_count += 1
            if vram_peak_mb:
                entry.measured_vram_peak_mb = max(entry.measured_vram_peak_mb, vram_peak_mb)

    def mark_unloaded(self, capability_id: str) -> None:
        entry = self._entries.get(capability_id)
        if entry:
            entry.loaded = False

    def total_loaded_vram_mb(self) -> int:
        return sum(e.measured_vram_peak_mb or e.vram_mb for e in self._entries.values() if e.loaded)

    def loaded_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.loaded)

    def to_dict(self) -> dict:
        return {
            "entries": [
                {"capability_id": e.capability_id, "stage": e.stage,
                 "vram_mb": e.vram_mb, "loaded": e.loaded,
                 "priority": e.priority, "can_fallback_cpu": e.can_fallback_cpu}
                for e in self._entries.values()
            ],
            "total_loaded_vram_mb": self.total_loaded_vram_mb(),
            "loaded_count": self.loaded_count(),
        }
