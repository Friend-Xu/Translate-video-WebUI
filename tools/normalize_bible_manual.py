"""一次性迁移: 剔除 timeline.json bible 中的 manual 词条 (origin="manual")。

背景: L0 人工词典 (config/terms/*.json, 可达 20 万条) 曾全量随 bible 落盘,
撑大 timeline.json 至 30MB+, 每次编辑的 load/persist 秒级延迟 (HTTP 1.4s)。
修复后 manual 词条为配置级输入, 渲染时经 with_manual_glossary 实时合并,
落盘只保留 LLM 自动词条。此脚本把旧文件里的 manual 词条剥掉。

用法: .venv/Scripts/python.exe tools/normalize_bible_manual.py <timeline.json> [timeline.json.bak ...]
写回前自动备份为 <文件>.pre_manual_normalize.bak。

注意: 必须同时迁移 timeline.json 和 timeline.json.bak —
undo 从 bak 重放补丁链后全量 persist, 若只迁主文件, 下一次 undo
会把旧 bible 又从 bak 读回写进 timeline.json (30MB 复发)。
"""
from __future__ import annotations

import json
import os
import shutil
import sys


def normalize(path: str) -> tuple[int, int, int]:
    """返回 (剥离前 hotwords 数, 剥离 manual 数, 剥离后 hotwords 数)。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    bible = data.get("translation_bible")
    if not isinstance(bible, dict):
        return 0, 0, 0
    hotwords = bible.get("hotwords")
    if not isinstance(hotwords, list):
        return 0, 0, 0
    before = len(hotwords)
    kept = [h for h in hotwords if not (isinstance(h, dict) and h.get("origin") == "manual")]
    if len(kept) == before:
        return before, 0, before
    shutil.copy2(path, path + ".pre_manual_normalize.bak")
    bible["hotwords"] = kept
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return before, before - len(kept), len(kept)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    total_files = 0
    for path in argv[1:]:
        if not os.path.isfile(path):
            print(f"SKIP (不存在): {path}")
            continue
        before, removed, after = normalize(path)
        size = os.path.getsize(path)
        print(f"{path}: hotwords {before} -> {after} (剥 {removed}), 文件 {size/1024/1024:.1f} MB")
        total_files += 1
    print(f"完成: {total_files} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
