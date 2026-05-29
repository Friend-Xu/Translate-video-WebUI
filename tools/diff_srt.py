#!/usr/bin/env python3
"""语义级 SRT diff 工具 (批次12 §2.3)

按容忍度分级比较两个 SRT 文件:
  - 时间戳 ±100ms 内视为等价
  - 文本编辑距离 < 5% 视为等价
  - 行数差异 > 5% 视为 FAIL

Usage:
    .venv/Scripts/python tools/diff_srt.py old.srt new.srt
    .venv/Scripts/python tools/diff_srt.py old.srt new.srt --time-tolerance 150
    .venv/Scripts/python tools/diff_srt.py old.srt new.srt --json
"""
from __future__ import annotations

import argparse
import json
import sys


def levenshtein_ratio(a: str, b: str) -> float:
    """归一化 Levenshtein 距离比率 (0.0 = 完全不同, 1.0 = 完全相同)。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    m, n = len(a), len(b)
    if m > n:
        a, b = b, a
        m, n = n, m

    prev = list(range(m + 1))
    for j in range(1, n + 1):
        curr = [j] + [0] * m
        for i in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[i] = min(prev[i] + 1, curr[i - 1] + 1, prev[i - 1] + cost)
        prev = curr

    return 1.0 - (prev[m] / max(m, n))


def parse_srt(content: str) -> list[dict]:
    """解析 SRT 文本为条目列表。"""
    entries = []
    blocks = content.strip().replace("\r\n", "\n").split("\n\n")

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        index_line = lines[0].strip()
        time_line = lines[1].strip()
        text = "\n".join(lines[2:]).strip()

        if not index_line.isdigit():
            continue
        if "-->" not in time_line:
            continue

        try:
            index = int(index_line)
            times = time_line.split("-->")
            start_ms = _timestamp_to_ms(times[0].strip())
            end_ms = _timestamp_to_ms(times[1].strip())
        except (ValueError, IndexError):
            continue

        entries.append({
            "index": index,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
        })

    return entries


def _timestamp_to_ms(ts: str) -> int:
    parts = ts.replace(",", ":").split(":")
    return int(parts[0]) * 3600000 + int(parts[1]) * 60000 + \
           int(parts[2]) * 1000 + int(parts[3])


def diff_srt_semantic(
    old: list[dict],
    new: list[dict],
    time_tolerance_ms: int = 100,
    content_tolerance: float = 0.05,
    line_count_tolerance: float = 0.05,
) -> dict:
    """按容忍度分级 diff 两个 SRT 条目列表。"""
    old_map = {e["index"]: e for e in old}
    new_map = {e["index"]: e for e in new}

    old_indices = set(old_map.keys())
    new_indices = set(new_map.keys())

    result = {
        "ok_count": 0,
        "time_diff": 0,
        "content_diff": 0,
        "missing": len(old_indices - new_indices),
        "extra": len(new_indices - old_indices),
        "total_old": len(old),
        "total_new": len(new),
        "passed": True,
        "details": [] as list,
    }

    for idx in sorted(old_indices & new_indices):
        oe = old_map[idx]
        ne = new_map[idx]

        time_ok = (
            abs(oe["start_ms"] - ne["start_ms"]) <= time_tolerance_ms
            and abs(oe["end_ms"] - ne["end_ms"]) <= time_tolerance_ms
        )
        if time_ok:
            result["ok_count"] += 1
        else:
            result["time_diff"] += 1

        sim = levenshtein_ratio(oe["text"], ne["text"])
        if sim < (1.0 - content_tolerance):
            result["content_diff"] += 1
            result["details"].append({
                "index": idx,
                "old_text": oe["text"][:100],
                "new_text": ne["text"][:100],
                "similarity": round(sim, 4),
            })

    if old and abs(result["total_new"] - result["total_old"]) / result["total_old"] > line_count_tolerance:
        result["passed"] = False
    if result["content_diff"] > 0:
        result["passed"] = False

    return result


def main():
    parser = argparse.ArgumentParser(description="语义级 SRT diff 工具")
    parser.add_argument("old_srt", help="旧路径 (基准) SRT 文件")
    parser.add_argument("new_srt", help="新路径 (core/) SRT 文件")
    parser.add_argument("--time-tolerance", type=int, default=100,
                        help="时间戳容忍度 (ms), 默认 100")
    parser.add_argument("--content-tolerance", type=float, default=0.05,
                        help="文本编辑距离容忍度, 默认 0.05")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    try:
        with open(args.old_srt, "r", encoding="utf-8") as f:
            old_content = f.read()
    except (FileNotFoundError, Exception) as e:
        print(f"错误: 无法读取 {args.old_srt}: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        with open(args.new_srt, "r", encoding="utf-8") as f:
            new_content = f.read()
    except (FileNotFoundError, Exception) as e:
        print(f"错误: 无法读取 {args.new_srt}: {e}", file=sys.stderr)
        sys.exit(2)

    old_entries = parse_srt(old_content)
    new_entries = parse_srt(new_content)

    result = diff_srt_semantic(
        old_entries, new_entries,
        time_tolerance_ms=args.time_tolerance,
        content_tolerance=args.content_tolerance,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"基准 SRT: {args.old_srt} ({result['total_old']} 行)")
        print(f"新 SRT:   {args.new_srt} ({result['total_new']} 行)")
        print()
        print(f"  时间等价: {result['ok_count']}")
        print(f"  时间差异: {result['time_diff']}  (> {args.time_tolerance}ms)")
        print(f"  内容差异: {result['content_diff']}  (> {args.content_tolerance * 100:.0f}% 编辑距离)")
        print(f"  缺失行:   {result['missing']}")
        print(f"  多余行:   {result['extra']}")
        print()
        if result["passed"]:
            print("结果: PASS")
        else:
            print("结果: FAIL")
            for d in result.get("details", []):
                print(f"\n  [{d['index']}] sim={d['similarity']:.3f}")
                print(f"    旧: {d['old_text']}")
                print(f"    新: {d['new_text']}")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
