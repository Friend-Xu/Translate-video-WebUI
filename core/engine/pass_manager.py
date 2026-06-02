"""
PassManager — Pass 调度器

拓扑排序执行已注册 Pass。支持依赖声明和循环检测。
"""
from __future__ import annotations
from collections import deque
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState


class PassManager:
    """Pass 调度器。

    Usage:
        pm = PassManager()
        pm.register(ASRToIRPass())
        pm.register(SemanticMergePass())
        final_state = pm.run(initial_state)
    """

    def __init__(self):
        self._passes: dict[str, TimelinePass] = {}
        self._order: list[str] = []
        self._config_resolver = None  # ConfigResolver | None — StageExecutor 注入

    def register(self, p: TimelinePass) -> None:
        if not p.name:
            raise ValueError("Pass 必须设置 name")
        self._passes[p.name] = p

    def run(self, state: TimelineProjectState) -> TimelineProjectState:
        self._resolve_order()
        current = state
        for name in self._order:
            self._configure_pass(name, current)
            current = self._passes[name].apply(current)
        return current

    def run_with_diff(
        self, state: TimelineProjectState
    ) -> tuple[TimelineProjectState, list[dict]]:
        """执行并返回每步 diff。每个 Pass 的 apply() 前调用 configure() 注入配置。(批次03 §五)"""
        self._resolve_order()
        current = state
        diffs = []
        for name in self._order:
            self._configure_pass(name, current)
            before_count = len(current.event_states)
            current = self._passes[name].apply(current)
            after_count = len(current.event_states)
            diffs.append({
                "pass": name,
                "events_before": before_count,
                "events_after": after_count,
                "delta": after_count - before_count,
            })
        return current, diffs

    def _configure_pass(self, name: str, state: TimelineProjectState) -> None:
        """在 apply() 前调用 pass.configure()，注入配置。(批次03 §五)"""
        resolver = self._config_resolver
        if resolver is None:
            return
        p = self._passes.get(name)
        if p is None:
            return
        slot_configs: dict[str, dict] = {}
        for slot in ("audio", "asr", "speaker", "translation", "tts",
                      "emotion", "semantic", "review"):
            slot_configs[slot] = resolver._global.get_slot_defaults(slot)
        p.configure(slot_configs)

    def _resolve_order(self) -> None:
        """Kahn 拓扑排序"""
        if self._order and len(self._order) == len(self._passes):
            return

        in_degree: dict[str, int] = {name: 0 for name in self._passes}
        children: dict[str, list[str]] = {name: [] for name in self._passes}

        for name, p in self._passes.items():
            for dep in p.depends_on:
                if dep not in self._passes:
                    raise ValueError(f"Pass '{name}' 依赖未注册的 '{dep}'")
                in_degree[name] += 1
                children[dep].append(name)

        queue = deque(n for n, d in in_degree.items() if d == 0)
        resolved = []

        while queue:
            name = queue.popleft()
            resolved.append(name)
            for child in children[name]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(resolved) != len(self._passes):
            remaining = set(self._passes) - set(resolved)
            raise ValueError(f"循环依赖检测: {remaining}")

        self._order = resolved

    def set_config_resolver(self, resolver) -> None:
        """设置配置解析器，用于在 Pass 执行前注入配置。

        StageExecutor 在每个阶段开始时调用此方法，
        确保本阶段的所有 Pass 都能接收到解析后的配置。
        """
        self._config_resolver = resolver

    def reset(self) -> None:
        """清空已注册的 Pass，准备复用。"""
        self._passes.clear()
        self._order.clear()
        self._config_resolver = None
