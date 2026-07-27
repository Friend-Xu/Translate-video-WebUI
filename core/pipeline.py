"""
core/pipeline.py — Runtime API 统一入口 (设计文档 §3, §12.4)

CLI 和 WebUI 共享此模块。封装所有胶水逻辑：
  - transcript 加载
  - translate_fn 构建
  - Pass Factory 构建
  - WorkflowPolicy 构建
  - Orchestrator 执行
  - timeline.json 持久化
"""
from __future__ import annotations
import json as _json
import os
from pathlib import Path
from typing import Callable

from core.engine.workflow_orchestrator import WorkflowOrchestrator
from core.engine.pass_factory import create_pass_factory
from core.engine.event_bus import EventBus
from core.engine.runtime_event import RuntimeEvent, RuntimeEventType as RET
from core.config.workflow_policy import WorkflowPolicy, WorkflowStage
from core.config.global_config import GlobalConfig
from core.runtime.project_state import TimelineProjectState
from core.runtime.synthesis import SynthesisEngine
from core.runtime.workspace import WorkspaceResolver
from core.runtime.context import RuntimeContext

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 数据加载 ────────────────────────────────────────────

def load_transcript_data(workspace_dir: str) -> tuple:
    """从 workspace 加载 extract 阶段的 transcript + speaker_timeline 数据。"""
    extract_dir = os.path.join(workspace_dir, "01_extract")
    segments = None
    speaker_timeline = None

    transcript_path = os.path.join(extract_dir, "transcript.json")
    if os.path.isfile(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = _json.load(f)
        segments = transcript.get("segments", [])

    speaker_timeline_path = os.path.join(extract_dir, "speaker_timeline.json")
    if os.path.isfile(speaker_timeline_path):
        with open(speaker_timeline_path, "r", encoding="utf-8") as f:
            st_data = _json.load(f)
        speaker_timeline = [
            (t["speaker"], t["start"], t["end"], t.get("confidence", 0.5))
            for t in st_data.get("turns", [])
        ]

    return segments, speaker_timeline


# ── Policy ──────────────────────────────────────────────

def build_policy(
    target_lang: str = "zh",
    stages: list[str] | None = None,
) -> WorkflowPolicy:
    """根据目标语言和阶段列表构建 WorkflowPolicy。

    Args:
        target_lang: 目标语言
        stages: 阶段列表。None = bootstrap 预设。["all"] = quick_preset 全流程。
    """
    if stages and "all" in stages:
        return WorkflowPolicy.quick_preset(target_lang)
    if not stages:
        return WorkflowPolicy.bootstrap_preset(target_lang)

    full = WorkflowPolicy.default_preset(target_lang)
    requested = {WorkflowStage(s) for s in stages}
    for s in list(full.stages.keys()):
        if s not in requested:
            del full.stages[s]
    return full


# ── Pass Factory ─────────────────────────────────────────

def build_pass_factory(
    ctx: RuntimeContext,
    translate_fn: Callable[[str, str], str] | None,
    segments: list | None,
    speaker_timeline: list | None,
    output_path: str = "",
) -> Callable[[str], object | None]:
    """构建 core/ Pass 工厂。"""
    wsr = WorkspaceResolver(ctx.video_path)
    wsr.ensure_dirs()
    audio_path = wsr.extracted_audio_path

    return create_pass_factory(
        translate_fn=translate_fn,
        segments=segments,
        speaker_timeline=speaker_timeline,
        output_path=output_path or os.path.join(wsr.workspace_root, "02_translate", "machine.srt"),
        engine=ctx.engine,
        video_path=ctx.video_path,
        audio_path=audio_path,
        output_dir=wsr.workspace_root,
        workspace_dir=wsr.workspace_root,
    )


# ── 持久化 ──────────────────────────────────────────────

def persist_timeline(state: TimelineProjectState, workspace_dir: str) -> str:
    """将 Pipeline 输出按 v2.0 schema 持久化为 timeline.json。"""
    engine = SynthesisEngine()
    rendered = engine.render_all(state)
    speakers_data = engine.render_speakers(state)

    ir = state.ir
    project_info = {
        "schema_version": ir.schema_version,
        "ir_version": ir.ir_version,
        "source_video": ir.source_video,
        "audio_sample_rate": ir.audio_sample_rate,
        "language": ir.language,
        "total_duration": ir.total_duration,
    }

    timeline_data = {
        "schema_version": "2.0",
        "project": project_info,
        "events": rendered,
        "speakers": {s["id"]: s for s in speakers_data},
        "metadata": {
            "generated_by": "core/pipeline.py",
            "event_count": len(rendered),
            "speaker_count": len(speakers_data),
        },
    }

    tl_path = os.path.join(workspace_dir, "02_translate", "timeline.json")
    os.makedirs(os.path.dirname(tl_path), exist_ok=True)
    with open(tl_path, "w", encoding="utf-8") as f:
        _json.dump(timeline_data, f, ensure_ascii=False, indent=2)
    return tl_path


# ── 主入口 ──────────────────────────────────────────────

def run_pipeline(
    video_path: str,
    *,
    target_lang: str = "zh",
    engine: str = "chattts",
    model: str = "turbo",
    device: str = "cuda",
    compute_type: str = "float16",
    stages: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    skip_demucs: bool = False,
    enable_speaker_diarization: bool = True,
) -> TimelineProjectState:
    """运行 core/ Pipeline — CLI 和 WebUI 的统一入口。"""
    ctx = RuntimeContext(
        video_path=video_path,
        target_lang=target_lang,
        engine=engine,
        model=model,
        device=device,
        compute_type=compute_type,
        stages=stages or [],
        dry_run=dry_run,
        force=force,
        skip_demucs=skip_demucs,
        enable_speaker_diarization=enable_speaker_diarization,
    )

    bus = EventBus()
    bus.emit_now(RuntimeEvent(
        event_type=RET.WORKFLOW_STARTED,
        payload={"video": video_path, "stages": stages or ["bootstrap"], "lang": target_lang},
    ))

    # 1. 加载已有 transcript
    segments, speaker_timeline = load_transcript_data(ctx.workspace_dir)

    # 2. 翻译由 LLMTranslationPass 默认客户端承担 (config/translate.yaml)
    translate_fn = None

    # 3. 输出路径
    machine_srt = os.path.join(ctx.workspace_dir, "02_translate", "machine.srt")
    os.makedirs(os.path.dirname(machine_srt), exist_ok=True)

    # 4. 构建 Pass 工厂
    factory = build_pass_factory(ctx, translate_fn, segments, speaker_timeline, machine_srt)

    # 5. 构建策略
    policy = build_policy(target_lang, stages)

    # 6. 全局配置
    translate_cfg = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
    tts_cfg = os.path.join(PROJECT_ROOT, "config", "runtime_tts.yaml")
    global_config = GlobalConfig.from_legacy_yaml(
        translate_cfg_path=translate_cfg,
        tts_cfg_path=tts_cfg,
    )

    # 7. Dry-run
    if dry_run:
        bus.emit_now(RuntimeEvent(
            event_type=RET.STAGE_COMPLETED,
            message=f"Dry-run 完成。阶段: {[s.value for s in policy.stage_order()]}",
        ))
        from core.ir.project import TimelineProjectIR
        return TimelineProjectState(TimelineProjectIR(events={}, speakers={}))

    # 8. 执行
    orchestrator = WorkflowOrchestrator(
        policy=policy,
        global_config=global_config,
        pass_factory=factory,
    )
    state = orchestrator.run(video_path)

    # 9. 持久化 timeline.json
    timeline_path = persist_timeline(state, ctx.workspace_dir)
    bus.emit_now(RuntimeEvent(
        event_type=RET.WORKFLOW_COMPLETED,
        payload={
            "event_count": len(state.ir.events),
            "timeline_path": timeline_path,
            "workspace_dir": ctx.workspace_dir,
        },
    ))

    return state
