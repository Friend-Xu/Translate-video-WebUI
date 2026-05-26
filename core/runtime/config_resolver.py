"""
ConfigResolver — 三级配置合并引擎 (定稿 §10.4)

实现:
  - deep_merge(): 深度合并算法（含 null 语义）
  - ConfigResolver.resolve_event_config(): Event > Speaker > Global 三级解析
  - serialize_event_config(): 差异化序列化（仅存储与解析结果的差异）

这是整个参数体系中调用频率最高的模块。每次 Patch 应用前、
Adapter 执行前、WebUI 渲染前都需要调用 resolve_event_config()。
"""
from __future__ import annotations
from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState
    from core.runtime.event_state import TimelineEventState
    from core.config.global_config import GlobalConfig


def deep_merge(base: dict, override: dict) -> None:
    """深度合并 override 到 base (原地修改 base)。

    规则:
      - override 中的普通值直接覆盖 base 中的对应键
      - override 中的 dict 递归合并到 base 中的对应 dict
      - override 中值为 null 的特殊处理: 删除 base 中的对应键（恢复继承）
      - base 中有但 override 中没有的键保持不变（惰性覆盖）

    这是整个参数体系最核心的算法。所有三级配置合并都依赖它。

    为什么原地修改而非返回新 dict？
      性能。在 1000+ 事件的流水线中，每次合并都创建新 dict 会导致
      大量 GC 压力。调用者如需保留原 base，应在调用前自行深拷贝。
    """
    for key, value in override.items():
        if value is None:
            # null 表示「删除此字段的事件级覆盖，恢复继承」
            base.pop(key, None)
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            # 嵌套 dict: 递归合并
            deep_merge(base[key], value)
        else:
            # 叶子值: 直接覆盖
            base[key] = value


class ConfigResolver:
    """三级配置解析器 — 实现 Event > Speaker > Global 优先级。

    用法:
        resolver = ConfigResolver(global_config)
        effective = resolver.resolve_event_config("evt_001", "asr", state)
        # effective["model"] 可能是事件级覆盖、说话人偏好、或全局默认
    """

    def __init__(self, global_config: "GlobalConfig"):
        self._global = global_config
        # LRU 缓存：避免对同一 (event_id, slot) 重复计算
        self._cache: dict[tuple, dict] = {}

    def resolve_event_config(
        self,
        event_id: str,
        slot: str,
        state: "TimelineProjectState",
    ) -> dict:
        """解析事件某槽位的最终运行时配置。

        三级合并: Event.config > Speaker.config > Global.config
        使用深度合并: 嵌套 dict 递归合并，叶子节点被高层覆盖。

        Returns:
            深拷贝的解析后配置 dict。调用者可安全修改。
        """
        # Layer 1: 全局默认配置（深拷贝，避免污染）
        resolved = self._global.get_slot_defaults(slot)

        event = state.get_event(event_id)
        if event is None:
            return resolved

        # Layer 2: 说话人配置（如果存在）
        speaker = self._get_speaker_for_event(event, state)
        if speaker is not None:
            speaker_config = getattr(speaker, 'config', None)
            if speaker_config:
                speaker_slot_config = speaker_config.get(slot, {})
                if speaker_slot_config:
                    deep_merge(resolved, speaker_slot_config)

        # Layer 3: 事件级覆盖（最高优先级）
        event_config = self._get_event_config(event, slot)
        if event_config:
            # 过滤 null 值（表示「恢复继承」）
            clean_config = {k: v for k, v in event_config.items() if v is not None}
            deep_merge(resolved, clean_config)
            # 处理 null 语义：显式删除被 null 覆盖的键
            for k, v in event_config.items():
                if v is None and k in resolved:
                    del resolved[k]

        return resolved

    def resolve_event_config_cached(
        self,
        event_id: str,
        slot: str,
        state: "TimelineProjectState",
    ) -> dict:
        """带缓存的配置解析。用于高频调用场景。

        缓存键为 (event_id, slot, config_hash)，在 patch 应用后自动失效。
        当前版本仅对同一 event_id+slot 做简单缓存。
        """
        event = state.get_event(event_id)
        if event is None:
            return self._global.get_slot_defaults(slot)

        # 通过 event 的 config 内容计算简易缓存键
        event_config = self._get_event_config(event, slot)
        cache_key = (event_id, slot, json_dumps_sorted(event_config))

        if cache_key in self._cache:
            return deepcopy(self._cache[cache_key])

        resolved = self.resolve_event_config(event_id, slot, state)
        self._cache[cache_key] = resolved
        return deepcopy(resolved)

    def invalidate_cache(self) -> None:
        """清空解析缓存（Patch 应用后调用）。"""
        self._cache.clear()

    @staticmethod
    def _get_event_config(event: "TimelineEventState", slot: str) -> dict:
        """从事件状态中安全提取 slot 的 config 子字段。"""
        slot_dict = getattr(event, slot, None)
        if slot_dict is None:
            return {}
        return slot_dict.get("config", {})

    @staticmethod
    def _get_speaker_for_event(
        event: "TimelineEventState", state: "TimelineProjectState"
    ):
        """获取事件对应的说话人节点。"""
        speaker_ref = getattr(event, 'speaker_ref', None)
        if speaker_ref is None:
            # 尝试从 speaker slot 读取
            speaker_slot = getattr(event, 'speaker', {})
            speaker_ref = speaker_slot.get("speaker_id")

        if speaker_ref is None:
            return None

        return state.ir.speakers.get(speaker_ref)


def serialize_event_config(
    event_state: "TimelineEventState",
    slot: str,
    resolved: dict,
) -> dict:
    """差异化序列化：仅存储与解析后有效配置的差异。

    为什么只存差异？
      对于 1000+ 片段的长视频，如果每个事件都存储全量配置
      (9 槽位 × 5-20 参数)，IR 文件体积将膨胀数十倍。
      差异化存储确保大多数事件 config 为空 dict。

    Args:
        event_state: 事件运行时状态
        slot: 槽位名
        resolved: 三级合并后的有效配置

    Returns:
        仅包含与 resolved 有差异的字段的 dict
    """
    slot_dict = getattr(event_state, slot, None)
    if slot_dict is None:
        return {}

    raw_config = slot_dict.get("config", {})
    if not raw_config:
        return {}

    diff = {}
    for key, value in raw_config.items():
        if value is None:
            # null 值：表示删除覆盖，不序列化
            continue
        if key in resolved:
            resolved_value = resolved.get(key)
            if isinstance(value, dict) and isinstance(resolved_value, dict):
                nested_diff = _dict_diff(value, resolved_value)
                if nested_diff:
                    diff[key] = nested_diff
            elif value != resolved_value:
                diff[key] = value
        else:
            # 全局配置中没有此键（可能是引擎专属参数）
            diff[key] = value

    return diff


def _dict_diff(override: dict, resolved: dict) -> dict:
    """计算 override 相对于 resolved 的差异（递归）。

    override 中有而 resolved 中无 或 值不同 → 进入差异。
    """
    diff = {}
    for key, value in override.items():
        if key not in resolved:
            diff[key] = value
        elif isinstance(value, dict) and isinstance(resolved[key], dict):
            nested = _dict_diff(value, resolved[key])
            if nested:
                diff[key] = nested
        elif value != resolved[key]:
            diff[key] = value
    return diff


def json_dumps_sorted(obj, default=None) -> str:
    """JSON 序列化（键排序），用于缓存键生成。"""
    import json
    return json.dumps(obj, sort_keys=True, default=default or str)
