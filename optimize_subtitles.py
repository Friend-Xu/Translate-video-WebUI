#!/usr/bin/env python3
"""
外挂字幕时间优化 — 独立脚本

用法:
    # 单语言优化
    python optimize_subtitles.py input.srt --output optimized.srt --lang zh

    # 双语优化
    python optimize_subtitles.py target.srt --source source.srt --mode bilingual --output merged.srt

    # 指定自定义参数
    python optimize_subtitles.py input.srt --min-duration 2.0 --reading-speed 3.5
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from pipeline.external_subtitle_optimizer import (
    optimize_srt,
    optimize_bilingual,
    load_ext_subtitle_config,
)


def main():
    parser = argparse.ArgumentParser(
        description="外挂字幕可读性时间优化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python optimize_subtitles.py input.srt -o optimized.srt --lang zh
  python optimize_subtitles.py target.srt --source source.srt --mode bilingual -o merged.srt
  python optimize_subtitles.py input.srt -o optimized.srt --min-duration 2.0
        """,
    )
    parser.add_argument("input", help="输入 SRT 文件路径（双语模式时为译文 SRT）")
    parser.add_argument("--output", "-o", required=True, help="输出 SRT 文件路径")
    parser.add_argument("--source", default=None, help="原文 SRT 路径（双语模式）")
    parser.add_argument("--lang", default="zh", help="语言代码 (zh/ja/ko/en/...)")
    parser.add_argument("--mode", default=None,
                        choices=["target_only", "source_only", "bilingual"],
                        help="输出模式（覆盖配置文件）")
    parser.add_argument("--config", default=None,
                        help="配置文件路径（默认 config/external_subtitle.yaml）")
    parser.add_argument("--min-duration", type=float, default=None,
                        help="最小显示时长（秒）")
    parser.add_argument("--reading-speed", type=float, default=None,
                        help="阅读速度（字符/秒）")
    parser.add_argument("--max-merge-gap", type=float, default=0.3,
                        help="合并判定间隙（秒，默认 0.3）")
    parser.add_argument("--inter-gap", type=float, default=0.05,
                        help="字幕间呼吸间隔（秒，默认 0.05）")
    parser.add_argument("--max-duration", type=float, default=10.0,
                        help="单条最大时长（秒，默认 10.0）")

    args = parser.parse_args()

    cfg = load_ext_subtitle_config(args.config)
    mode = args.mode or cfg.get("mode", "bilingual")

    if mode == "bilingual" and not args.source:
        print("[X] 双语模式需要 --source 指定原文 SRT")
        sys.exit(1)

    if mode == "source_only":
        print("[X] source_only 模式请直接将原文 SRT 作为 input 传入")
        sys.exit(1)

    kwargs = {
        "lang": args.lang,
        "min_duration": args.min_duration,
        "reading_speed": args.reading_speed,
        "max_merge_gap": args.max_merge_gap,
        "inter_gap": args.inter_gap,
        "max_duration": args.max_duration,
    }

    if mode == "bilingual":
        print(f"双语模式: 译文={args.input}  原文={args.source}")
        stats = optimize_bilingual(args.input, args.source, args.output, **kwargs)
    else:
        print(f"单语模式: {args.input}")
        stats = optimize_srt(args.input, args.output, **kwargs)

    print(f"\n[OK] 输出: {args.output}")
    print(f"  总条目:  {stats['total']}")
    print(f"  已调整:  {stats['adjusted']}")
    print(f"  已合并:  {stats['merged']}")
    print(f"  未改动:  {stats['total'] - stats['adjusted']}")


if __name__ == "__main__":
    main()
