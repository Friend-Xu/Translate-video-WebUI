"""
DependencyGraph — Segment 间依赖关系图 (Chapter 12 §12.5.2)

用途:
  1. 计算 patch 影响范围
  2. 确定局部重算窗口
  3. 检测循环依赖

依赖规则:
  - temporal: 时间上相邻的 segments (前/后各 1)
  - speaker: 同 speaker_id 的 segments
  - semantic: embedding 相似度 > 0.7 的相邻 segments
  - structural: split/merge 父子关系
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.project_state import TimelineProjectState


@dataclass
class DependencyEdge:
    """依赖边。"""
    upstream_id: str
    downstream_id: str
    relation: str          # "temporal" | "speaker" | "semantic" | "structural"
    strength: float        # 0.0-1.0


class DependencyGraph:
    """Segment 间依赖关系图。"""

    def __init__(self):
        self.edges: dict[str, list[DependencyEdge]] = {}
        self.reverse: dict[str, list[DependencyEdge]] = {}
        self._invalidated: set[str] = set()

    # ── build ───────────────────────────────────────────

    def build(self, state: TimelineProjectState) -> None:
        """从当前 state 构建完整依赖图。"""
        self.edges.clear()
        self.reverse.clear()
        self._invalidated.clear()

        sorted_events = state.sorted_events()

        for i, es in enumerate(sorted_events):
            eid = es.id

            # temporal: 相邻 (前/后各 1)
            if i > 0:
                gap = es.start - sorted_events[i - 1].end
                strength = max(0.0, 1.0 - abs(gap) / 5.0)
                self._add_edge(sorted_events[i - 1].id, eid, "temporal", strength)
            if i < len(sorted_events) - 1:
                gap = sorted_events[i + 1].start - es.end
                strength = max(0.0, 1.0 - abs(gap) / 5.0)
                self._add_edge(eid, sorted_events[i + 1].id, "temporal", strength)

            # speaker: 同 speaker_id
            spk = es.speaker_ref or es.speaker.get("speaker_id", "")
            if spk:
                for j, other in enumerate(sorted_events):
                    if j <= i:
                        continue
                    other_spk = other.speaker_ref or other.speaker.get("speaker_id", "")
                    if other_spk == spk:
                        self._add_edge(eid, other.id, "speaker", 0.8)

            # semantic: embedding 共享时标记弱依赖
            sem = es.semantic
            if sem.get("embedding_ref") and i < len(sorted_events) - 1:
                next_sem = sorted_events[i + 1].semantic
                if next_sem.get("embedding_ref"):
                    self._add_edge(eid, sorted_events[i + 1].id, "semantic", 0.7)

            # structural: split/merge 父子
            derivs = es.derivatives
            for merged_id in derivs.get("_merged_from", []):
                self._add_edge(merged_id, eid, "structural", 1.0)
            if "_split_from" in derivs:
                self._add_edge(derivs["_split_from"], eid, "structural", 1.0)

    def _add_edge(self, upstream: str, downstream: str, relation: str, strength: float) -> None:
        edge = DependencyEdge(upstream, downstream, relation, strength)
        self.edges.setdefault(upstream, []).append(edge)
        self.reverse.setdefault(downstream, []).append(edge)

    # ── query ───────────────────────────────────────────

    def get_downstream(self, segment_id: str, depth: int = 1) -> set[str]:
        """BFS 获取下游依赖 segments。"""
        visited: set[str] = set()
        current = {segment_id}
        for _ in range(depth):
            nxt: set[str] = set()
            for sid in current:
                for edge in self.edges.get(sid, []):
                    if edge.downstream_id not in visited:
                        nxt.add(edge.downstream_id)
            if not nxt:
                break
            visited.update(nxt)
            current = nxt
        return visited

    def get_upstream(self, segment_id: str, depth: int = 1) -> set[str]:
        """BFS 获取上游依赖 segments。"""
        visited: set[str] = set()
        current = {segment_id}
        for _ in range(depth):
            nxt: set[str] = set()
            for sid in current:
                for edge in self.reverse.get(sid, []):
                    if edge.upstream_id not in visited:
                        nxt.add(edge.upstream_id)
            if not nxt:
                break
            visited.update(nxt)
            current = nxt
        return visited

    def get_affected_range(
        self, segment_id: str, upstream_depth: int = 1, downstream_depth: int = 2,
    ) -> set[str]:
        """受影响范围 = self + upstream + downstream。"""
        affected = {segment_id}
        affected.update(self.get_upstream(segment_id, upstream_depth))
        affected.update(self.get_downstream(segment_id, downstream_depth))
        return affected

    # ── invalidation ────────────────────────────────────

    def invalidate(self, segment_id: str, max_depth: int = 3) -> list[str]:
        """标记 segment 失效，级联传播到下游。返回被级联失效的 IDs。"""
        self._invalidated.add(segment_id)
        cascaded: list[str] = []
        current = {segment_id}
        for _ in range(max_depth):
            nxt: set[str] = set()
            for sid in current:
                for edge in self.edges.get(sid, []):
                    if edge.strength > 0.5 and edge.downstream_id not in self._invalidated:
                        self._invalidated.add(edge.downstream_id)
                        cascaded.append(edge.downstream_id)
                        nxt.add(edge.downstream_id)
            if not nxt:
                break
            current = nxt
        return cascaded

    def is_invalidated(self, segment_id: str) -> bool:
        return segment_id in self._invalidated

    def clear_invalidation(self) -> None:
        self._invalidated.clear()

    def get_invalidated(self) -> list[str]:
        return list(self._invalidated)

    # ── prune ───────────────────────────────────────────

    def pruned(self, max_depth: int = 5) -> "DependencyGraph":
        """返回剪枝后的图（限制传播深度）。"""
        pruned = DependencyGraph()
        pruned.edges = dict(self.edges)
        pruned.reverse = dict(self.reverse)
        pruned._invalidated = set(self._invalidated)
        for eid in list(pruned.edges.keys()):
            deep = pruned.get_downstream(eid, depth=max_depth + 1)
            too_deep = pruned.get_downstream(eid, depth=999) - deep
            pruned.edges[eid] = [
                e for e in pruned.edges.get(eid, [])
                if e.downstream_id not in too_deep
            ]
        return pruned
