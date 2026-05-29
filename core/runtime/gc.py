"""
Workspace GC + Archive (CLI Runtime 计划书 §7)

GC: 清理过期 checkpoint、临时文件、可选 TTS 中间产物
Archive: 将完成项目打包为 .zip
"""
from __future__ import annotations
import glob as _glob
import os
import shutil
import time
from dataclasses import dataclass, field


@dataclass
class GCOperation:
    path: str = ""
    reason: str = ""
    size_bytes: int = 0
    action: str = "dry_run"

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024 / 1024


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total


def _find_tmp_files(workspace_dir: str) -> list[str]:
    found = []
    for pattern in ("*.tmp", "*_worker_stderr.log", "*.log.old"):
        for p in _glob.glob(os.path.join(workspace_dir, pattern)):
            found.append(p)
    for sub in ("01_extract", "02_translate", "03_tts", "04_output",
                "05_tts", "06_export"):
        for p in _glob.glob(os.path.join(workspace_dir, sub, "*.tmp")):
            found.append(p)
    return found


def collect_gc(workspace_dir: str, ttl_days: int = 7) -> list[GCOperation]:
    """扫描 workspace，返回可清理项列表（不执行删除）。"""
    ops: list[GCOperation] = []
    now = time.time()
    ttl = ttl_days * 86400

    for f in _find_tmp_files(workspace_dir):
        ops.append(GCOperation(
            path=f, reason="tmp file",
            size_bytes=_size(f), action="delete",
        ))

    snapshots_dir = os.path.join(workspace_dir, ".snapshots")
    if os.path.isdir(snapshots_dir):
        for entry in os.listdir(snapshots_dir):
            full = os.path.join(snapshots_dir, entry)
            if os.path.getmtime(full) < now - ttl:
                ops.append(GCOperation(
                    path=full, reason=f"stale snapshot (> {ttl_days}d)",
                    size_bytes=_size(full), action="delete",
                ))

    tts_dir = os.path.join(workspace_dir, "03_tts")
    if os.path.isdir(tts_dir):
        manifest_path = os.path.join(workspace_dir, "project.json")
        is_frozen = False
        if os.path.isfile(manifest_path):
            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                is_frozen = json.load(f).get("state") == "frozen"
        if is_frozen:
            for f in _glob.glob(os.path.join(tts_dir, "*.wav")):
                ops.append(GCOperation(
                    path=f, reason="frozen project, TTS intermediate",
                    size_bytes=_size(f), action="delete",
                ))

    return ops


def apply_gc(ops: list[GCOperation], dry_run: bool = True) -> tuple[int, int]:
    """执行清理。dry_run=True 只返回统计不删除。返回 (count, freed_bytes)。"""
    freed = 0
    count = 0
    for op in ops:
        if dry_run:
            freed += op.size_bytes
            count += 1
            continue
        try:
            if os.path.isfile(op.path):
                os.remove(op.path)
                freed += op.size_bytes
                count += 1
            elif os.path.isdir(op.path):
                shutil.rmtree(op.path)
                freed += op.size_bytes
                count += 1
        except OSError:
            pass
    return count, freed


def archive_workspace(workspace_dir: str, archives_root: str = "") -> str:
    """将 workspace 打包为 .zip，排除可重生成产物。"""
    import zipfile
    import datetime

    if not os.path.isdir(workspace_dir):
        return ""

    archives_root = archives_root or os.path.join(
        os.path.dirname(workspace_dir), "archives")
    os.makedirs(archives_root, exist_ok=True)

    ws_name = os.path.basename(workspace_dir)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(archives_root, f"{ws_name}_{ts}.zip")

    exclude_dirs = {".snapshots", "_embeddings", "03_tts", "05_tts"}
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(workspace_dir):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                for f in files:
                    if f.endswith((".tmp", ".log.old")):
                        continue
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, workspace_dir)
                    zf.write(full, arcname)
        return archive_path
    except Exception:
        return ""


def format_gc_summary(ops: list[GCOperation]) -> str:
    if not ops:
        return "Nothing to clean."
    total = sum(o.size_bytes for o in ops)
    lines = [f"{len(ops)} items, {total / 1024 / 1024:.1f}MB to free:", ""]
    for op in ops:
        lines.append(f"  [{op.action:6s}] {op.size_mb:6.1f}MB  {op.reason:40s}  {op.path}")
    return "\n".join(lines)
