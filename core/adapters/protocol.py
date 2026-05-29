"""
AdapterProtocol — 统一适配器协议 (CLI Runtime 计划书 §5)

所有 core/adapters/ 下的适配器实现此协议，使 StageExecutor
和 WorkflowOrchestrator 能按 capability_id 调度，而非按文件名。

设计原则（Karpathy 指南）:
  - 只做项目实际需要的字段，不扩冲
  - 不定义输入/输出 schema（当前无消费者）
  - 不定义 lifecycle 状态机（当前无 warmup/eviction 需求）
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCategory(Enum):
    """适配器错误分类 — 用于 StageExecutor 做恢复决策。"""
    RETRYABLE = "retryable"    # GPU OOM / 临时故障，可重试
    DEGRADABLE = "degradable"  # GPU 不足可降级 CPU
    CONFIG = "config"          # 参数/配置错误，不可重试
    FATAL = "fatal"            # 适配器不支持当前输入，不可执行


@dataclass
class ResourceRequirement:
    """适配器资源需求声明。"""
    gpu: bool = False
    vram_mb: int = 0
    exclusive: bool = False   # 是否需独占 GPU


@dataclass
class AdapterCapability:
    """适配器能力声明 — StageExecutor 据此调度。"""
    capability_id: str        # "asr.whisper" / "separation.demucs" / "tts.chattts"
    display_name: str = ""
    resources: ResourceRequirement = field(default_factory=ResourceRequirement)
    failure_policy: str = "block"  # retry | degrade | skip | block


@dataclass
class AdapterResult:
    """适配器执行结果 — 统一输出契约。"""
    ok: bool
    data: Any = None
    error: str = ""
    error_category: ErrorCategory | None = None
    patches: list[Any] = field(default_factory=list)


class AdapterProtocol(ABC):
    """适配器协议基类。

    所有 adapter 必须实现 capability 属性和 execute 方法。
    configure / warmup / teardown 为可选钩子。
    """

    @property
    @abstractmethod
    def capability(self) -> AdapterCapability:
        """返回此适配器的能力声明。"""
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> AdapterResult:
        """统一执行入口。具体参数由各 adapter 自行定义。"""
        ...

    def configure(self, event_config: dict[str, Any] | None = None) -> None:
        """可选: 运行时配置注入。"""
        pass

    def warmup(self) -> None:
        """可选: 模型预热。"""
        pass

    def teardown(self) -> None:
        """可选: 资源释放。"""
        pass


# ── 适配器注册表 ────────────────────────────────────────────

class AdapterRegistry:
    """按 capability_id 索引的适配器注册表。

    Usage:
        registry = AdapterRegistry()
        registry.register(whisper_adapter)
        adapter = registry.find("asr.whisper")
    """

    def __init__(self):
        self._adapters: dict[str, AdapterProtocol] = {}

    def register(self, adapter: AdapterProtocol) -> None:
        self._adapters[adapter.capability.capability_id] = adapter

    def find(self, capability_id: str) -> AdapterProtocol | None:
        return self._adapters.get(capability_id)

    def list_ids(self) -> list[str]:
        return list(self._adapters.keys())
