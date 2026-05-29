#!/usr/bin/env python3
"""
tvw.py — Translate-video-WebUI 统一 CLI 入口 (CLI Runtime 计划书 §6)

命令族:
  tvw run <video> [--lang zh] ...      完整管线 (委托 main.py)
  tvw inspect <workspace>               查看 project.json + stage 进度
  tvw stage <stage> <workspace>         只跑单个阶段
  tvw validate <workspace>              只跑校验
  tvw export <workspace>                只跑导出

用法:
  tvw run source_file/video.mp4 --lang zh
  tvw inspect source_file/video_project/
  tvw stage translate source_file/video_project/
"""
from __future__ import annotations
import argparse
import json as _json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.isabs(sys.path[0]):
    sys.path[0] = ""


def _find_workspace(video_or_ws: str) -> str:
    """智能解析 workspace 路径: 可以直接给 workspace 目录或视频路径。"""
    path = os.path.abspath(video_or_ws)
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "project.json")):
            return path
        stem = os.path.splitext(os.path.basename(path))[0]
        ws = os.path.join(os.path.dirname(path), f"{stem}_project")
        if os.path.isdir(ws):
            return ws
    if os.path.isfile(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        ws = os.path.join(os.path.dirname(path), f"{stem}_project")
        if os.path.isdir(ws):
            return ws
    print(f"[ERROR] 找不到 workspace: {video_or_ws}", file=sys.stderr)
    sys.exit(1)


def cmd_run(args) -> None:
    """完整管线执行 — 委托 main.py。"""
    from main import main as _main_main
    _orig = sys.argv[:]
    try:
        sys.argv = ["main.py", os.path.abspath(args.video)]
        if args.lang:
            sys.argv.extend(["--lang", args.lang])
        if args.engine:
            sys.argv.extend(["--engine", args.engine])
        if args.model:
            sys.argv.extend(["--model", args.model])
        if args.device:
            sys.argv.extend(["--device", args.device])
        if args.compute_type:
            sys.argv.extend(["--compute-type", args.compute_type])
        if args.use_core:
            sys.argv.append("--use-core")
        if args.skip_extract:
            sys.argv.append("--skip-extract")
        if args.skip_translate:
            sys.argv.append("--skip-translate")
        if args.skip_tts:
            sys.argv.append("--skip-tts")
        if args.skip_demucs:
            sys.argv.append("--skip-demucs")
        if args.skip_align:
            sys.argv.append("--skip-align")
        if args.force:
            sys.argv.append("--force")
        _main_main()
    finally:
        sys.argv = _orig


def cmd_inspect(args) -> None:
    """查看 workspace 状态。"""
    ws_dir = _find_workspace(args.workspace)

    manifest_path = os.path.join(ws_dir, "project.json")
    manifest = None
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = _json.load(f)

    ck_path = os.path.join(ws_dir, "checkpoint.json")
    checkpoint = None
    if os.path.isfile(ck_path):
        with open(ck_path, "r", encoding="utf-8") as f:
            checkpoint = _json.load(f)

    print(f"Workspace: {ws_dir}")

    if manifest:
        state = manifest.get("state", "draft")
        print(f"State: {state}")
        print(f"Video: {manifest.get('video_path', 'N/A')}")
        print(f"Updated: {manifest.get('updated_at', 'N/A')}")
        print()
        pipeline = manifest.get("pipeline", {})
        print("Stages:")
        stage_order = ["extract", "translate", "validate", "tts", "export"]
        for s in stage_order:
            status = pipeline.get(s, "not_configured")
            icon = {"completed": "[OK]", "pending": "[..]", "failed": "[XX]", "running": "[>>]"}.get(status, "[??]")
            print(f"  {icon} {s:12s}  {status}")

    print()
    existing_dirs = []
    for d in sorted(os.listdir(ws_dir)):
        full = os.path.join(ws_dir, d)
        if os.path.isdir(full):
            count = len([f for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))])
            existing_dirs.append(f"  {d}/ ({count} files)")
    if existing_dirs:
        print("Files:")
        for d_entry in existing_dirs:
            print(d_entry)

    if checkpoint:
        steps = checkpoint.get("steps", {})
        if steps:
            print()
            print("Checkpoint:")
            for name, info in steps.items():
                st = info.get("status", "unknown")
                ts = info.get("completed_at", "")
                print(f"  {name}: {st}  {ts}")


def cmd_stage(args) -> None:
    """执行单个阶段。"""
    ws_dir = _find_workspace(args.workspace)

    from core.engine import WorkflowOrchestrator, ProgressReport
    from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
    from core.config.global_config import GlobalConfig

    valid_stages = {s.value for s in WorkflowStage}
    if args.stage_name not in valid_stages:
        print(f"[ERROR] 未知阶段: {args.stage_name}. 有效值: {', '.join(sorted(valid_stages))}", file=sys.stderr)
        sys.exit(1)

    stage = WorkflowStage(args.stage_name)
    policy = WorkflowPolicy.single_stage(stage)
    orchestrator = WorkflowOrchestrator(policy=policy, global_config=GlobalConfig())

    def _progress(report: ProgressReport) -> None:
        print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_progress)

    video = ws_dir
    try:
        state = orchestrator.run(video)
        print(f"  [OK] Stage '{args.stage_name}' 完成")
    except RuntimeError as e:
        print(f"  [X] 阶段失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_validate(args) -> None:
    """只跑校验阶段。"""
    ws_dir = _find_workspace(args.workspace)

    from core.engine import WorkflowOrchestrator, ProgressReport
    from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
    from core.config.global_config import GlobalConfig

    policy = WorkflowPolicy.single_stage(WorkflowStage.VALIDATE)
    orchestrator = WorkflowOrchestrator(policy=policy, global_config=GlobalConfig())

    def _progress(report: ProgressReport) -> None:
        print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_progress)

    try:
        orchestrator.run(ws_dir)
        print(f"  [OK] 校验完成")
    except RuntimeError as e:
        print(f"  [X] 校验失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_export(args) -> None:
    """只跑导出阶段。"""
    ws_dir = _find_workspace(args.workspace)

    manifest_path = os.path.join(ws_dir, "project.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = _json.load(f)
        state = manifest.get("state", "")
        if state == "draft":
            print("[ERROR] Workspace 状态为 'draft'，请先完成 bootstrap 阶段", file=sys.stderr)
            sys.exit(1)

    from core.engine import WorkflowOrchestrator, ProgressReport
    from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
    from core.config.global_config import GlobalConfig

    policy = WorkflowPolicy.single_stage(WorkflowStage.EXPORT)
    orchestrator = WorkflowOrchestrator(policy=policy, global_config=GlobalConfig())

    def _progress(report: ProgressReport) -> None:
        print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_progress)

    try:
        orchestrator.run(ws_dir)
        dubbed = os.path.join(ws_dir, "06_export", "dubbed.mp4")
        if os.path.isfile(dubbed):
            sz = os.path.getsize(dubbed) / 1024 / 1024
            print(f"  [OK] 导出完成: {dubbed} ({sz:.1f}MB)")
        else:
            print(f"  [OK] 导出完成")
    except RuntimeError as e:
        print(f"  [X] 导出失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_benchmark(args) -> None:
    """适配器性能基准。"""
    from core.adapters.benchmark import run_benchmark, format_result

    if args.capability == "all":
        capabilities = ["asr.whisper", "tts.chattts"]
    else:
        capabilities = [args.capability]

    for cap in capabilities:
        result = run_benchmark(cap, audio=args.audio, text=args.text,
                               device=args.device, iterations=args.iterations)
        print(format_result(result))


def cmd_profile(args) -> None:
    """workspace 性能分析。"""
    from core.runtime.profiler import profile_workspace
    ws_dir = _find_workspace(args.workspace)
    result = profile_workspace(ws_dir)
    print(result.summary())


def cmd_gc(args) -> None:
    """workspace 垃圾回收。"""
    from core.runtime.gc import collect_gc, apply_gc, format_gc_summary
    ws_dir = _find_workspace(args.workspace)
    ops = collect_gc(ws_dir, ttl_days=args.ttl)
    print(format_gc_summary(ops))
    if ops and not args.force:
        print("\n[Dry-run] 使用 --force 实际执行删除")
        return
    if ops and args.force:
        count, freed = apply_gc(ops, dry_run=False)
        print(f"\n已清理 {count} 项, 释放 {freed / 1024 / 1024:.1f}MB")


def cmd_archive(args) -> None:
    """归档 workspace。"""
    from core.runtime.gc import archive_workspace
    ws_dir = _find_workspace(args.workspace)
    path = archive_workspace(ws_dir)
    if path:
        sz = os.path.getsize(path) / 1024 / 1024
        print(f"已归档: {path} ({sz:.1f}MB)")
    else:
        print("[ERROR] 归档失败", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="tvw — Translate-video-WebUI CLI Runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # ── run ──
    p_run = sub.add_parser("run", help="完整管线执行")
    p_run.add_argument("video", help="视频文件路径")
    p_run.add_argument("--lang", default=None, help="源语言 (en/ja/zh)")
    p_run.add_argument("--engine", default="edge", help="TTS 引擎")
    p_run.add_argument("--model", default="turbo", help="Whisper 模型")
    p_run.add_argument("--device", default="cuda", help="计算设备")
    p_run.add_argument("--compute-type", default="float16", help="计算精度")
    p_run.add_argument("--use-core", action="store_true", help="使用 core/ PassManager 翻译")
    p_run.add_argument("--skip-extract", action="store_true")
    p_run.add_argument("--skip-translate", action="store_true")
    p_run.add_argument("--skip-tts", action="store_true")
    p_run.add_argument("--skip-demucs", action="store_true")
    p_run.add_argument("--skip-align", action="store_true")
    p_run.add_argument("--force", action="store_true")

    # ── inspect ──
    p_inspect = sub.add_parser("inspect", help="查看 workspace 状态")
    p_inspect.add_argument("workspace", help="workspace 目录或视频路径")

    # ── stage ──
    p_stage = sub.add_parser("stage", help="执行单个阶段")
    p_stage.add_argument("stage_name", help="阶段名 (load/extract/translate/validate/tts/export)")
    p_stage.add_argument("workspace", help="workspace 目录")

    # ── validate ──
    p_validate = sub.add_parser("validate", help="只跑校验")
    p_validate.add_argument("workspace", help="workspace 目录")

    # ── export ──
    p_export = sub.add_parser("export", help="只跑导出")
    p_export.add_argument("workspace", help="workspace 目录")

    # ── benchmark ──
    p_bench = sub.add_parser("benchmark", help="适配器性能基准测试")
    p_bench.add_argument("capability", nargs="?", default="all",
                         help="适配器 capability_id (asr.whisper/tts.chattts/all)")
    p_bench.add_argument("--audio", default="", help="测试音频路径 (asr 需要)")
    p_bench.add_argument("--text", default="你好世界", help="测试文本 (tts 需要)")
    p_bench.add_argument("--device", default="cuda", help="计算设备")
    p_bench.add_argument("--iterations", type=int, default=3, help="重复次数")

    # ── profile ──
    p_profile = sub.add_parser("profile", help="workspace 性能分析")
    p_profile.add_argument("workspace", help="workspace 目录")

    # ── gc ──
    p_gc = sub.add_parser("gc", help="清理 workspace")
    p_gc.add_argument("workspace", help="workspace 目录")
    p_gc.add_argument("--ttl", type=int, default=7, help="snapshot 保留天数 (默认 7)")
    p_gc.add_argument("--force", action="store_true", help="实际执行删除 (默认 dry-run)")

    # ── archive ──
    p_arch = sub.add_parser("archive", help="归档 workspace 为 .zip")
    p_arch.add_argument("workspace", help="workspace 目录")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    _dispatch = {
        "run": cmd_run,
        "inspect": cmd_inspect,
        "stage": cmd_stage,
        "validate": cmd_validate,
        "export": cmd_export,
        "benchmark": cmd_benchmark,
        "profile": cmd_profile,
        "gc": cmd_gc,
        "archive": cmd_archive,
    }
    handler = _dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
