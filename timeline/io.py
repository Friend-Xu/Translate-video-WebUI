"""
Timeline IR 序列化 / 反序列化 / 版本迁移
"""

from __future__ import annotations

import json
import os

from .ir import TimelineIR

CURRENT_VERSION = "1.0"


def save_json(ir: TimelineIR, path: str) -> None:
    """将 TimelineIR 序列化写入 JSON 文件（原子写入）。"""
    data = ir.to_dict()
    data["version"] = CURRENT_VERSION

    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path: str) -> TimelineIR:
    """从 JSON 文件反序列化为 TimelineIR（含版本检测与迁移）。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("version", "1.0")
    if version != CURRENT_VERSION:
        data = migrate(data, version, CURRENT_VERSION)

    return TimelineIR.from_dict(data)


def migrate(data: dict, from_version: str, to_version: str) -> dict:
    """版本迁移框架 — 逐版本升级 data dict。
    当前仅 1.0 版本，无需实际迁移，保留接口为后续扩展。
    """
    return data
