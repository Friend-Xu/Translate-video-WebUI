"""
TASK 13 — Patch DAG Index. Dependency graph + partial replay.
"""
from __future__ import annotations

from timeline.patch.model import TimelinePatch


def build_dependency_graph(patches: list[TimelinePatch]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for i, p in enumerate(patches):
        deps = []
        p_targets = set(p.targets)
        for j in range(i):
            prev = patches[j]
            if p_targets & set(prev.targets):
                deps.append(prev.patch_id)
        graph[p.patch_id] = deps
    return graph


def find_affected_patches(patches: list[TimelinePatch], target_patch_id: str) -> list[str]:
    graph = build_dependency_graph(patches)
    return [pid for pid, deps in graph.items() if target_patch_id in deps]


def topological_order(patches: list[TimelinePatch]) -> list[TimelinePatch]:
    graph = build_dependency_graph(patches)
    in_degree = {p.patch_id: 0 for p in patches}
    for deps in graph.values():
        for d in deps:
            in_degree[d] = in_degree.get(d, 0) + 1
    queue = [pid for pid, deg in in_degree.items() if deg == 0]
    result = []
    id_map = {p.patch_id: p for p in patches}
    while queue:
        pid = queue.pop(0)
        if pid in id_map:
            result.append(id_map[pid])
        for neighbor in graph.get(pid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    return result
