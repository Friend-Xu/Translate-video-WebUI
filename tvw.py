#!/usr/bin/env python3
"""tvw.py — Translate-video-WebUI 统一 CLI 入口 (CLI Runtime 计划书 §6)

  tvw run <video> [--lang zh] ...      完整管线 (委托 main.py)
  tvw run <video> --use-core ...        完整管线 (core/ WorkflowOrchestrator)
  tvw inspect <workspace>               查看 project.json + session + checkpoint
  tvw resume <workspace>                从最近 checkpoint 恢复执行
  tvw logs <workspace> [--stage]...     查看结构化日志
  tvw stage <stage> <workspace>         只跑单个阶段
  tvw validate <workspace>              只跑校验
  tvw export <workspace>                只跑导出
  tvw timeline show <workspace>         显示 Timeline IR 摘要
  tvw patch history <workspace>         显示补丁历史
  tvw rollback --to <checkpoint> <ws>   回退到指定 checkpoint
  tvw benchmark <capability>            适配器基准测试
  tvw profile <workspace>               workspace 性能分析
  tvw gc <workspace>                    清理 workspace
  tvw archive <workspace>               归档 workspace 为 .zip

全局选项:
  --json-output                         结构化 JSON 事件输出 (headless/WebUI 模式)
                                        每行以 RS (\\x1e) 前缀的 JSON 对象
JSON 事件格式:
  {"type":"stage_started","stage":"extract","ts":"..."}
  {"type":"stage_progress","stage":"tts","current_item":3,"total_items":10}
  {"type":"stage_completed","stage":"extract","message":"ok"}
  {"type":"workflow_completed","status":"completed","events":42}
  {"type":"workflow_failed","error":"..."}
  {"type":"log","level":"INFO","message":"..."}

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
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.isabs(sys.path[0]):
    sys.path[0] = ""

# ── JSON 输出工具 ──────────────────────────────────────────

_JSON_OUTPUT = False  # --json-output flag

def _json_out(obj: dict) -> None:
    """输出一行 RS 分隔的 JSON 到 stdout。仅在 --json-output 模式激活。"""
    if not _JSON_OUTPUT:
        return
    line = _json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(f"\x1e{line}\n")
    sys.stdout.flush()

def _json_error(message: str) -> None:
    """输出错误 JSON 事件并退出。"""
    _json_out({"type": "workflow_failed", "error": message, "ts": _now_iso()})
    sys.exit(1)

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """完整管线执行。

    无 --use-core: 委托 main.py
    有 --use-core: 直接调用 WorkflowOrchestrator (计划书 §10 统一 Runtime 入口)
    """
    if args.use_core:
        _run_core_pipeline(args)
    else:
        _run_legacy_pipeline(args)


def _run_legacy_pipeline(args) -> None:
    """Legacy 路径 — 委托 main.py。"""
    from main import main as _main_main
    _json_out({"type": "log", "level": "INFO", "message": "tvw run (legacy) → main.py", "ts": _now_iso()})
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
        _json_out({"type": "workflow_completed", "status": "completed", "ts": _now_iso()})
    except SystemExit as e:
        if e.code and e.code != 0:
            _json_error(f"main.py exited with code {e.code}")
        else:
            _json_out({"type": "workflow_completed", "status": "completed", "ts": _now_iso()})
    except Exception as e:
        _json_error(f"Legacy pipeline failed: {e}")
    finally:
        sys.argv = _orig


def _run_core_pipeline(args) -> None:
    """Core 路径 — WorkflowOrchestrator 执行 (计划书 §10)。"""
    from core.engine import WorkflowOrchestrator, ProgressReport
    from core.engine.pass_factory import create_pass_factory
    from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
    from core.config.global_config import GlobalConfig
    from core.runtime.session import SessionStore, SessionState

    _json_out({"type": "log", "level": "INFO", "message": "tvw run --use-core → WorkflowOrchestrator", "ts": _now_iso()})

    video_path = os.path.abspath(args.video)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    ws_dir = os.path.join(os.path.dirname(video_path) or ".", f"{stem}_project")
    extract_dir = os.path.join(ws_dir, "01_extract")
    os.makedirs(extract_dir, exist_ok=True)

    lang = args.lang or "zh"
    if args.stages:
        stages = [s.strip() for s in args.stages.split(",")]
    else:
        stages = ["load", "extract", "translate", "validate"]

    if args.bootstrap:
        # Bootstrap 预设 — 仅到 VALIDATE
        policy = WorkflowPolicy.bootstrap_preset(target_lang=lang)
    elif args.export_stage:
        # Export 预设 — 仅 TTS + EXPORT
        policy = WorkflowPolicy.export_preset(target_lang=lang)
        stages = ["tts", "export"]
        SessionStore.transition(ws_dir, SessionState.EXPORTING)
    else:
        policy = WorkflowPolicy.default_preset(target_lang=lang)

    gcfg = GlobalConfig()
    if args.engine:
        gcfg.tts_engine = args.engine
    if args.device:
        gcfg.device = args.device

    # ── 构建 translate_fn ─────────────────────────────────────
    # 新架构直接调用 LLM API，不通过 SRT 文件桥接。
    # LLMTranslationPass 已将事件渲染为标签化文本、解析 LLM 回复、
    # 通过 PatchEngine 写入 runtime state。
    def _translate_fn(tagged_text: str) -> str:
        """直接调 LLM API 翻译标签化文本。

        输入: "[evt_001] 今天天气真好\n[evt_002] 一起去散步吧"
        输出: "[evt_001] 今日は本当にいい天気ですね\n[evt_002] 一緒に散歩しましょう"
        """
        import yaml

        config_path = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}

        api_key = cfg.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            # 无 API key → mock translation
            from core.passes.llm_translation_pass import LLMTranslationPass
            return LLMTranslationPass._mock_translate(tagged_text)

        base_url = cfg.get("api_base_url", "") or "https://api.deepseek.com"
        model = cfg.get("model", "deepseek-chat")

        import requests as _requests
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "You are a subtitle translator. "
                    "Translate the following tagged text from the source language "
                    f"to {lang}. Preserve ALL [evt_NNN] tags exactly as-is. "
                    "Return ONLY the translated text with tags, no explanations."
                )},
                {"role": "user", "content": tagged_text},
            ],
            "temperature": 0.1,
            "max_tokens": 4000,
        }
        try:
            resp = _requests.post(
                f"{base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            from core.passes.llm_translation_pass import LLMTranslationPass
            return LLMTranslationPass._mock_translate(tagged_text)

    # ── 构建 Pass 工厂 ─────────────────────────────────────
    audio_path = os.path.join(extract_dir, f"{stem}_extracted.wav")
    vocals_path = os.path.join(extract_dir, f"{stem}_vocals.wav")

    # 选择质量把控策略 (用户可在 config/quality.yaml 中选择)
    # 导入策略模块以触发装饰器注册
    import core.quality.logic_gate_strategy  # noqa: F401 — 注册 logic_gate
    import core.quality.xcomet_strategy     # noqa: F401 — 注册 xcomet
    quality_name = gcfg.project.translation.get("quality_strategy", "logic_gate")
    from core.quality.protocol import create_strategy as create_quality_strategy
    quality_strategy = create_quality_strategy(quality_name, gcfg)

    pass_factory = create_pass_factory(
        translate_fn=_translate_fn,
        video_path=video_path,
        audio_path=audio_path,
        output_dir=ws_dir,
        workspace_dir=ws_dir,
        engine=args.engine or "edge",
        quality_strategy=quality_strategy,
    )

    orchestrator = WorkflowOrchestrator(
        policy=policy,
        global_config=gcfg,
    )
    orchestrator.set_pass_factory(pass_factory)

    def _progress(report: ProgressReport) -> None:
        _json_out({
            "type": "stage_progress",
            "stage": report.stage.value if hasattr(report.stage, 'value') else report.stage,
            "stage_label": report.stage_label,
            "current_item": getattr(report, "current_item", 0),
            "total_items": getattr(report, "total_items", 0),
            "percent": getattr(report, "percent", 0.0),
            "message": report.message,
            "ts": _now_iso(),
        })
        if not _JSON_OUTPUT:
            print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_progress)

    # EventBus 阶段事件
    from core.engine.event_bus import EventBus
    from core.engine.runtime_event import RuntimeEvent, RuntimeEventType as RET

    class _TvwSubscriber:
        def on_event(self, event: RuntimeEvent) -> None:
            ev = event.event_type
            if ev == RET.STAGE_STARTED:
                _json_out({"type": "stage_started", "stage": event.stage or "", "stage_label": event.stage_label or "", "ts": _now_iso()})
            elif ev == RET.STAGE_COMPLETED:
                _json_out({"type": "stage_completed", "stage": event.stage or "", "stage_label": event.stage_label or "", "message": event.message or "", "ts": _now_iso()})

    EventBus().subscribe(_TvwSubscriber())

    # 初始化 session
    try:
        SessionStore.transition(ws_dir, SessionState.BOOTSTRAPPING)
        SessionStore.save(ws_dir, video_path=video_path, current_stage="load")
    except Exception:
        pass

    try:
        state = orchestrator.run(video_path)
        events_count = len(state.event_states) if state and hasattr(state, 'event_states') else 0

        # 持久化 timeline.json 到 workspace
        _persist_timeline(state, ws_dir, video_path, lang)

        SessionStore.transition(ws_dir, SessionState.REVIEWABLE)
        _json_out({"type": "workflow_completed", "status": "completed", "events": events_count, "ts": _now_iso()})
        if not _JSON_OUTPUT:
            print(f"  [OK] Core Pipeline 完成 ({events_count} events)")
    except Exception as e:
        try:
            SessionStore.transition(ws_dir, SessionState.FAILED)
        except Exception:
            pass
        _json_error(f"Core pipeline failed: {e}")
        if not _JSON_OUTPUT:
            print(f"  [X] Core Pipeline 失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_inspect(args) -> None:
    """查看 workspace 状态。"""
    from core.runtime.session import SessionStore, SessionState

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

    session = SessionStore.load(ws_dir)

    print(f"Workspace: {ws_dir}")

    if session:
        icon = {"draft":"[..]","bootstrapping":"[>>]","reviewable":"[R ]",
                "validated":"[V ]","exporting":"[>>]","completed":"[OK]","failed":"[XX]"}.get(session.session_state, "[??]")
        print(f"Session: {icon} {session.session_state.value}")
        print(f"Video: {session.video_path or manifest.get('video_path', 'N/A') if manifest else 'N/A'}")
        print(f"Current Stage: {session.current_stage or '-'}")
        print(f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(session.updated_at))}")
        if session.patch_head:
            print(f"Patch Head: {session.patch_head}")
        if session.validation_status:
            print(f"Validation: {session.validation_status}")
        if session.export_status:
            print(f"Export: {session.export_status}")
    elif manifest:
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
    from core.engine.event_bus import EventBus
    from core.engine.runtime_event import RuntimeEventType as RET
    from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
    from core.config.global_config import GlobalConfig
    from core.runtime.session import SessionStore, SessionState

    valid_stages = {s.value for s in WorkflowStage}
    if args.stage_name not in valid_stages:
        msg = f"未知阶段: {args.stage_name}. 有效值: {', '.join(sorted(valid_stages))}"
        if _JSON_OUTPUT:
            _json_error(msg)
        else:
            print(f"[ERROR] {msg}", file=sys.stderr)
            sys.exit(1)

    stage = WorkflowStage(args.stage_name)
    policy = WorkflowPolicy.single_stage(stage)
    orchestrator = WorkflowOrchestrator(policy=policy, global_config=GlobalConfig())

    _json_out({"type": "stage_started", "stage": args.stage_name, "ts": _now_iso()})

    def _progress(report: ProgressReport) -> None:
        _json_out({
            "type": "stage_progress",
            "stage": report.stage.value if hasattr(report.stage, 'value') else report.stage,
            "stage_label": report.stage_label,
            "message": report.message,
            "ts": _now_iso(),
        })
        if not _JSON_OUTPUT:
            print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_progress)

    SessionStore.transition(ws_dir, SessionState.BOOTSTRAPPING)

    try:
        state = orchestrator.run(ws_dir)
        SessionStore.transition(ws_dir, SessionState.REVIEWABLE)
        _json_out({"type": "stage_completed", "stage": args.stage_name, "message": "ok", "ts": _now_iso()})
        if not _JSON_OUTPUT:
            print(f"  [OK] Stage '{args.stage_name}' 完成")
    except RuntimeError as e:
        SessionStore.transition(ws_dir, SessionState.FAILED)
        _json_error(f"阶段失败: {e}")
        if not _JSON_OUTPUT:
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
    from core.runtime.capability import CapabilityRegistry

    if args.capability == "all":
        capabilities = ["asr.whisper", "tts.chattts"]
    else:
        capabilities = [args.capability]

    for cap in capabilities:
        result = run_benchmark(cap, audio=args.audio, text=args.text,
                               device=args.device, iterations=args.iterations)
        print(format_result(result))

    if args.show_caps:
        reg = CapabilityRegistry()
        print("\n[Capability Registry]")
        for e in reg.list_all():
            loaded = "LOADED" if e.loaded else "idle"
            print(f"  {e.capability_id:25s}  stage={e.stage:10s}  vram={e.vram_mb:5d}MB  {loaded}")


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


# ═══════════════════════════════════════════════════════════
# T1.2-1.6: 新增命令 (CLI 完备化)
# ═══════════════════════════════════════════════════════════

def cmd_resume(args) -> None:
    """从最近 checkpoint 恢复执行。"""
    ws_dir = _find_workspace(args.workspace)

    from core.runtime.session import SessionStore, SessionState
    from core.engine import WorkflowOrchestrator, ProgressReport
    from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
    from core.config.global_config import GlobalConfig

    session = SessionStore.load(ws_dir)
    if session is None:
        print("[ERROR] 此 workspace 无 session 记录，无法恢复。请使用 `tvw stage` 重新执行", file=sys.stderr)
        sys.exit(1)

    current_stage = session.current_stage
    if not current_stage:
        print("[ERROR] session 未记录当前阶段，无法恢复", file=sys.stderr)
        sys.exit(1)

    stage = WorkflowStage(current_stage)
    print(f"从 stage '{current_stage}' 恢复 (on {ws_dir})")

    policy = WorkflowPolicy.single_stage(stage)
    orchestrator = WorkflowOrchestrator(policy=policy, global_config=GlobalConfig())

    def _progress(report: ProgressReport) -> None:
        print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_progress)
    SessionStore.transition(ws_dir, SessionState.BOOTSTRAPPING)

    try:
        orchestrator.run(ws_dir)
        SessionStore.transition(ws_dir, SessionState.REVIEWABLE)
        print(f"  [OK] 恢复完成")
    except RuntimeError as e:
        SessionStore.transition(ws_dir, SessionState.FAILED)
        print(f"  [X] 恢复失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_logs(args) -> None:
    """查看结构化日志。"""
    ws_dir = _find_workspace(args.workspace)
    log_path = os.path.join(ws_dir, "pipeline.log")
    if not os.path.isfile(log_path):
        print("(无日志文件)", file=sys.stderr)
        return

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [line.rstrip() for line in f]

    # filter by stage
    if args.stage:
        stage_tag = f"[{args.stage.upper()}]" if not args.stage.startswith("[") else args.stage
        lines = [l for l in lines if stage_tag in l]

    # filter by level
    if args.level:
        level_v = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        min_v = level_v.get(args.level.upper(), 0)
        filtered = []
        for l in lines:
            lv = 20
            if "[DEBUG]" in l: lv = 10
            elif "[WARN" in l: lv = 30
            elif "[ERROR]" in l: lv = 40
            if lv >= min_v:
                filtered.append(l)
        lines = filtered

    # tail
    if args.tail and args.tail > 0:
        lines = lines[-args.tail:]

    for line in lines:
        print(line)


def cmd_timeline_show(args) -> None:
    """显示 Timeline IR 摘要。"""
    ws_dir = _find_workspace(args.workspace)
    tl_path = os.path.join(ws_dir, "01_extract", "timeline.json")
    if not os.path.isfile(tl_path):
        print("[ERROR] 未找到 timeline.json", file=sys.stderr)
        sys.exit(1)

    with open(tl_path, "r", encoding="utf-8") as f:
        tl = _json.load(f)

    meta = tl.get("metadata", {})
    print(f"Timeline: {tl.get('schema_version', '?')}  "
          f"{meta.get('event_count', '?')} events, "
          f"{meta.get('speaker_count', '?')} speakers")

    events = tl.get("events", [])
    if args.event_id:
        events = [e for e in events if e.get("id") == args.event_id]
        if not events:
            print(f"(no event matching '{args.event_id}')")
            return

    for evt in events:
        sid = evt.get("id", "?")
        spk = evt.get("speaker", "-")
        text = evt.get("text", "")[:80]
        tr = evt.get("translation", "")
        if isinstance(tr, dict):
            tr = tr.get("text", "") or ""
        start = evt.get("start", 0)
        end = evt.get("end", 0)
        mark = ""
        if evt.get("confidence", 1.0) < 0.7:
            mark = " [LOW-CONF]"
        if evt.get("review_status", "") == "flagged":
            mark += " [FLAGGED]"
        print(f"  {sid:10s}  {start:6.1f}-{end:6.1f}  [{spk:6s}]  {text[:60]:60s}{mark}")
        if tr:
            print(f"  {'':10s}  {'':14s}  [译]       {tr[:60]}")


def cmd_patch_history(args) -> None:
    """显示补丁历史。"""
    ws_dir = _find_workspace(args.workspace)
    patch_path = os.path.join(ws_dir, "01_extract", "timeline_patches.json")
    if not os.path.isfile(patch_path):
        print("(无 patch 日志)", file=sys.stderr)
        return

    with open(patch_path, "r", encoding="utf-8") as f:
        patches = _json.load(f)

    if not isinstance(patches, list):
        patches = patches.get("patches", [])

    limit = args.limit or 20
    patches = patches[-limit:]

    for i, p in enumerate(patches):
        op = p.get("opcode") or p.get("op", "?")
        tid = p.get("targets", [p.get("target_id", "?")])[0] if isinstance(p.get("targets"), list) else p.get("target_id", "?")
        author = p.get("author", "?")
        ts = p.get("timestamp", "?")
        reason = p.get("reason", "")
        if reason:
            reason = f" ({', '.join(reason) if isinstance(reason, list) else reason})"
        print(f"  {op:20s}  {tid:10s}  {author:8s}  {ts}{reason}")


def cmd_rollback(args) -> None:
    """回退到指定的 checkpoint。"""
    ws_dir = _find_workspace(args.workspace)

    from core.runtime.rollback import RollbackManager
    from core.runtime.snapshot import SnapshotManager

    snap_mgr = SnapshotManager(ws_dir)
    snapshots = snap_mgr.list_snapshots()
    if not snapshots:
        print("[ERROR] 无可用的快照", file=sys.stderr)
        sys.exit(1)

    target_id = args.to
    if target_id not in {s.id for s in snapshots}:
        print(f"[ERROR] 未找到快照: {target_id}", file=sys.stderr)
        names = [s.id for s in snapshots[:5]]
        print(f"可用: {', '.join(names)}")
        sys.exit(1)

    # dry-run 预览
    target = next(s for s in snapshots if s.id == target_id)
    print(f"即将回退到: {target_id} (created {time.strftime('%Y-%m-%d %H:%M', time.localtime(target.created_at))})")
    affected = target.affected_events or ["?"]
    print(f"影响事件: {', '.join(affected[:10])}{'...' if len(affected) > 10 else ''}")

    if not args.force:
        print("\n[Dry-run] 使用 --force 实际执行回退。回退不可逆。")
        return

    mgr = RollbackManager(ws_dir)
    result = mgr.restore(target_id)
    if result:
        print(f"  [OK] 已回退到 {target_id}")
    else:
        print(f"  [ERROR] 回退失败", file=sys.stderr)
        sys.exit(1)


def _persist_timeline(state, ws_dir: str, video_path: str, lang: str) -> str:
    """将 TimelineProjectState 持久化为 timeline.json，供 WebUI 读取。"""
    import json as _json_mod
    extract_dir = os.path.join(ws_dir, "01_extract")
    os.makedirs(extract_dir, exist_ok=True)
    tl_path = os.path.join(extract_dir, "timeline.json")

    events = []
    speakers = {}
    for es in state.event_states.values():
        evt = {
            "id": es.id,
            "start": es.start,
            "end": es.end,
            "text": es.ir.text_ref,
            "source": es.ir.source,
        }
        # translation
        trans = es.translation
        if isinstance(trans, dict):
            evt["translation"] = trans
        elif isinstance(trans, str) and trans:
            evt["translation"] = {"text": trans}
        else:
            evt["translation"] = {}
        # speaker
        spk = es.speaker
        if isinstance(spk, dict) and spk.get("speaker_id"):
            evt["speaker"] = spk["speaker_id"]
            sid = spk["speaker_id"]
            if sid not in speakers:
                speakers[sid] = {"id": sid, "label": sid}
        # confidence
        evt["confidence"] = es.provenance.get("confidence", 1.0)
        # review status
        evt["review_status"] = es.review.get("review_status", "pending")
        events.append(evt)

    timeline = {
        "schema_version": "2.0",
        "metadata": {
            "event_count": len(events),
            "speaker_count": len(speakers),
            "source_video": video_path,
            "language": lang,
            "generated_at": _now_iso(),
        },
        "events": events,
        "speakers": speakers,
    }
    with open(tl_path, "w", encoding="utf-8") as f:
        _json_mod.dump(timeline, f, ensure_ascii=False, indent=2)
    return tl_path


def main():
    parser = argparse.ArgumentParser(
        description="tvw — Translate-video-WebUI CLI Runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json-output", action="store_true",
                        help="结构化 JSON 事件输出 (headless/WebUI 模式)")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # ── run ──
    p_run = sub.add_parser("run", help="完整管线执行")
    p_run.add_argument("video", help="视频文件路径")
    p_run.add_argument("--lang", default=None, help="源语言 (en/ja/zh)")
    p_run.add_argument("--engine", default="edge", help="TTS 引擎")
    p_run.add_argument("--model", default="turbo", help="Whisper 模型")
    p_run.add_argument("--device", default="cuda", help="计算设备")
    p_run.add_argument("--compute-type", default="float16", help="计算精度")
    p_run.add_argument("--use-core", action="store_true", help="使用 core/ WorkflowOrchestrator 执行")
    p_run.add_argument("--bootstrap", action="store_true",
                       help="仅执行 Bootstrap (LOAD→EXTRACT→TRANSLATE→VALIDATE), TTS/Export 推迟")
    p_run.add_argument("--export-stage", action="store_true",
                       help="仅执行 Export (TTS→EXPORT), 依赖 Bootstrap 已完成")
    p_run.add_argument("--stages", default=None,
                       help="指定阶段列表, 逗号分隔 (默认: load,extract,translate,validate)")
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
    p_bench.add_argument("--show-caps", action="store_true", help="显示 Capability Registry 快照")

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

    # ── resume ──
    p_resume = sub.add_parser("resume", help="从最近 checkpoint 恢复执行")
    p_resume.add_argument("workspace", help="workspace 目录")

    # ── logs ──
    p_logs = sub.add_parser("logs", help="查看结构化日志")
    p_logs.add_argument("workspace", help="workspace 目录")
    p_logs.add_argument("--stage", default="", help="按阶段过滤")
    p_logs.add_argument("--level", default="INFO", help="最低日志级别")
    p_logs.add_argument("--tail", type=int, default=0, help="只显示最后 N 行")

    # ── timeline show ──
    p_tl = sub.add_parser("timeline", help="Timeline IR 操作")
    p_tl = sub.add_parser("timeline", help="Timeline IR 操作 (show)")
    p_tl.add_argument("action", nargs="?", default="show", choices=["show"], help="操作")
    p_tl.add_argument("workspace", help="workspace 目录")
    p_tl.add_argument("--event-id", default="", help="按事件 ID 过滤")

    # ── patch history ──
    p_patch = sub.add_parser("patch", help="Patch 操作 (history)")
    p_patch.add_argument("action", nargs="?", default="history", choices=["history"], help="操作")
    p_patch.add_argument("workspace", help="workspace 目录")
    p_patch.add_argument("--limit", type=int, default=20, help="显示最近 N 个")

    # ── rollback ──
    p_rb = sub.add_parser("rollback", help="回退到指定 checkpoint")
    p_rb.add_argument("--to", required=True, help="目标 checkpoint ID")
    p_rb.add_argument("workspace", help="workspace 目录")
    p_rb.add_argument("--force", action="store_true", help="实际执行回退 (默认 dry-run)")

    args = parser.parse_args()
    global _JSON_OUTPUT
    _JSON_OUTPUT = getattr(args, "json_output", False)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    _dispatch = {
        "run": cmd_run,
        "inspect": cmd_inspect,
        "resume": cmd_resume,
        "logs": cmd_logs,
        "stage": cmd_stage,
        "validate": cmd_validate,
        "export": cmd_export,
        "timeline": cmd_timeline_show,
        "patch": cmd_patch_history,
        "rollback": cmd_rollback,
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
