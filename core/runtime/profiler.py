"""
Runtime Profiler (CLI Runtime 计划书 §11)

对已完成 workspace 做全流程性能分析。
读取 checkpoint.json + project.json 时间戳，计算每阶段耗时分布。
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field


@dataclass
class ProfileResult:
    workspace: str = ""
    video: str = ""
    total_s: float = 0.0
    stages: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Workspace: {self.workspace}", f"Video: {self.video}", ""]
        lines.append(f"{'Stage':16s} {'Duration':>10s}  {'%':>6s}")
        lines.append("-" * 34)
        for s in self.stages:
            pct = f"{s['pct']:.0f}%" if s['pct'] > 0 else "--"
            lines.append(f"{s['name']:16s} {s['duration']:>10s}  {pct:>6s}")
        lines.append("-" * 34)
        lines.append(f"{'Total':16s} {self._fmt(self.total_s):>10s}")
        return "\n".join(lines)

    @staticmethod
    def _fmt(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        m, s = divmod(seconds, 60)
        return f"{int(m)}m{s:.0f}s"


def profile_workspace(workspace_dir: str) -> ProfileResult:
    """读 checkpoint.json 计算每阶段耗时。"""
    ck_path = os.path.join(workspace_dir, "checkpoint.json")
    manifest_path = os.path.join(workspace_dir, "project.json")

    result = ProfileResult(workspace=workspace_dir)

    manifest = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    result.video = manifest.get("video_path", "N/A")

    if not os.path.isfile(ck_path):
        return result

    with open(ck_path, "r", encoding="utf-8") as f:
        ck = json.load(f)

    steps = ck.get("steps", {})
    total = 0.0
    for name in ("extract", "translate", "tts", "export"):
        info = steps.get(name, {})
        started = info.get("started_at", "")
        completed = info.get("completed_at", "")
        dur = 0.0
        if started and completed:
            from datetime import datetime
            try:
                t0 = datetime.fromisoformat(started)
                t1 = datetime.fromisoformat(completed)
                dur = (t1 - t0).total_seconds()
            except Exception:
                pass
        total += dur
        result.stages.append({
            "name": name,
            "status": info.get("status", "unknown"),
            "duration": ProfileResult._fmt(dur),
            "seconds": dur,
            "pct": 0.0,
        })

    if total > 0:
        for s in result.stages:
            s["pct"] = s["seconds"] / total * 100
    result.total_s = total
    return result
