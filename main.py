#!/usr/bin/env python3
"""
Translate Video — 一站式翻译管线 (core/ WorkflowOrchestrator 统一驱动)

三个 stage 全部委托 core 编排器:
  extract   → LOAD+EXTRACT passes (缺陷检测/音频/分离/VAD/ASR/对齐/说话人)
  translate → TRANSLATE passes (bible + 逐句 + xCOMET 质量闭环)
  TTS       → TTS+EXPORT passes (配音 + 字幕渲染 + 视频合并)

用法:
    python main.py <视频路径> [--lang en] [--engine chattts] [--skip-tts]
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import subprocess
import sys
import time

from pipeline.logger import get_logger
logger = get_logger("main")

# 防 CUDA 碎片化：PyTorch 2.0+ expandable segments 允许内存段动态伸缩，
# 配合 max_split_size_mb 防止大块被切碎后无法归还。
# 必须在 torch 首次导入前设置（ChatTTS / pipeline 模块内懒加载 torch）。
if os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128"

# 禁用 PyTorch CUDA 缓存分配器，强制使用裸 cudaMalloc。
# CTranslate2 (faster-whisper) 和 ChatTTS 都使用裸 cudaMalloc，
# PyTorch 的 CUDACachingAllocator 与其在同一 CUDA 上下文中冲突，
# 在 Windows 上导致 STATUS_HEAP_CORRUPTION (0xC0000374)。
os.environ.setdefault("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")

# Windows GBK terminal fix
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", write_through=True)


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Python 把脚本目录作为绝对路径加入 sys.path[0]。
# 后续 import 链中的 pyarrow C 扩展会触发 importlib._fill_cache 扫描
# sys.path 上的绝对路径，在 D: 盘上碰到 WinError 6714。
# 将 sys.path[0] 替换为空字符串（CWD，相对路径），功能等价但安全。
if sys.path and os.path.isabs(sys.path[0]):
    sys.path[0] = ""


from pipeline.checkpoint import PipelineCheckpoint, StepState


def backup_step(label: str, paths: list[str], backup_root: str) -> None:
    """将关键中间产物备份到带标签和时间戳的目录。"""
    import shutil
    ts = time.strftime("%H%M%S")
    dest = os.path.join(backup_root, f"{ts}_{label}")
    os.makedirs(dest, exist_ok=True)
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        base = os.path.basename(p)
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(dest, base), dirs_exist_ok=True)
        else:
            shutil.copy2(p, os.path.join(dest, base))
    print(f"  [备份] {label} → {dest}")


def setup_hf_env() -> None:
    """配置 HuggingFace 环境（镜像站 + 本地缓存）。

    强制覆盖所有模型缓存路径到项目本地 models/ 目录，避免
    ~/.cache/huggingface 和项目目录之间分裂导致重复下载。
    """
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    hf_home = os.path.join(PROJECT_ROOT, "models", "hf_cache")
    os.environ["HF_HOME"] = hf_home
    os.environ["TRANSFORMERS_CACHE"] = hf_home
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = hf_home
    os.makedirs(hf_home, exist_ok=True)

    os.environ["TORCH_HOME"] = os.path.join(PROJECT_ROOT, "models")
    os.makedirs(os.path.join(PROJECT_ROOT, "models", "hub", "checkpoints"), exist_ok=True)


def workspace_paths(video_path: str) -> dict | None:
    """返回视频翻译工作目录的各路径（标准化结构）。

    工作目录布局::

        {video_dir}/{stem}_project/
        ├── project.json
        ├── checkpoint.json
        ├── 01_extract/    ← 媒体抽取 + ASR
        ├── 02_translate/  ← 翻译 + 质量评估
        ├── 03_speaker/    ← 说话人分离 + 声线映射
        ├── 04_patch/      ← 补丁历史
        ├── 05_tts/        ← TTS 片段
        └── 06_export/     ← 最终导出

    如果工作目录不存在则返回 None。
    """
    target = os.path.dirname(video_path)
    name = os.path.splitext(os.path.basename(video_path))[0]
    ws = os.path.join(target, f"{name}_project")
    if not os.path.isdir(ws):
        return None

    return {
        "workspace": ws,
        "extract_dir": os.path.join(ws, "01_extract"),
        "translate_dir": os.path.join(ws, "02_translate"),
        "speaker_dir": os.path.join(ws, "03_speaker"),
        "patch_dir": os.path.join(ws, "04_patch"),
        "tts_dir": os.path.join(ws, "05_tts"),
        "output_dir": os.path.join(ws, "06_export"),
        # 标准文件名
        "source_srt": os.path.join(ws, "01_extract", "source.srt"),
        "transcript_json": os.path.join(ws, "01_extract", "transcript.json"),
        "audio_wav": os.path.join(ws, "01_extract", "audio.wav"),
        "vocals_wav": os.path.join(ws, "01_extract", "vocals.wav"),
        "instrumental_wav": os.path.join(ws, "01_extract", "instrumental.wav"),
        "vad_segments": os.path.join(ws, "01_extract", "vad_segments.json"),
        "machine_srt": os.path.join(ws, "02_translate", "machine.srt"),
        "reviewed_srt": os.path.join(ws, "02_translate", "reviewed.srt"),
        "translate_log": os.path.join(ws, "02_translate", "translate-log.json"),
        "timeline": os.path.join(ws, "01_extract", "timeline.json"),
        "timeline_translated": os.path.join(ws, "02_translate", "timeline.json"),
        "speaker_timeline": os.path.join(ws, "03_speaker", "speaker_timeline.json"),
        "speaker_map": os.path.join(ws, "03_speaker", "speaker_map.json"),
        "patch_log": os.path.join(ws, "04_patch", "timeline_patches.json"),
        "dubbed_mp4": os.path.join(ws, "06_export", "dubbed.mp4"),
    }


def guess_source_srt(video_path: str) -> str | None:
    """从工作目录获取源语言 SRT 路径。"""
    ws = workspace_paths(video_path)
    if ws and os.path.isfile(ws["source_srt"]):
        return ws["source_srt"]
    return None


def guess_translated_srt(video_path: str) -> str | None:
    """从工作目录获取翻译后 SRT 路径。reviewed > machine。"""
    ws = workspace_paths(video_path)
    if ws:
        if os.path.isfile(ws["reviewed_srt"]):
            return ws["reviewed_srt"]
        if os.path.isfile(ws["machine_srt"]):
            return ws["machine_srt"]
    return None




def _workspace_dir(video: str) -> str:
    """返回视频对应的工作目录路径。"""
    target = os.path.dirname(video)
    name = os.path.splitext(os.path.basename(video))[0]
    return os.path.join(target, f"{name}_project")


def load_manifest(workspace_dir: str) -> dict | None:
    """读取工作目录的 project.json。"""
    path = os.path.join(workspace_dir, "project.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(video: str, data: dict) -> None:
    """写入 project.json。"""
    ws = _workspace_dir(video)
    path = os.path.join(ws, "project.json")
    data["updated_at"] = datetime.datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _create_manifest(video: str) -> dict:
    """创建初始 project.json（v2 schema, 含生命周期状态）。"""
    now = datetime.datetime.now().isoformat()
    data = {
        "version": 2,
        "state": "draft",
        "video_path": video.replace("\\", "/"),
        "created_at": now,
        "updated_at": now,
        "pipeline": {"extract": "pending", "translate": "pending", "tts": "pending"},
        "files": {},
        "timeline_frozen_at": None,
    }
    _save_manifest(video, data)
    return data


def _manifest_ensure_v2(data: dict) -> dict:
    """旧格式 manifest (v1: 无 version/pipeline/state) 显式迁移到 v2 schema。

    保留已有字段 (video_path/runtime_state/files)，补齐 v2 生命周期键；
    步骤状态初始 pending，由 PipelineCheckpoint 控制实际重跑。
    """
    if "pipeline" not in data:
        data["version"] = 2
        data["state"] = "draft"
        data["pipeline"] = {"extract": "pending", "translate": "pending", "tts": "pending"}
        data.setdefault("files", {})
        data.setdefault("timeline_frozen_at", None)
        data.setdefault("created_at", "")
        data.setdefault("updated_at", "")
    return data


def _manifest_set_step(video: str, step: str, status: str) -> None:
    """更新管线步骤状态。"""
    ws = _workspace_dir(video)
    path = os.path.join(ws, "project.json")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = _manifest_ensure_v2(data)
    data["pipeline"][step] = status
    _save_manifest(video, data)


def _manifest_set_files(video: str, file_map: dict) -> None:
    """批量更新 file 清单（相对路径）。"""
    ws = _workspace_dir(video)
    path = os.path.join(ws, "project.json")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = _manifest_ensure_v2(data)
    data["files"].update(file_map)
    _save_manifest(video, data)


def _ensure_workspace(video: str) -> None:
    """创建工作目录（所有 4 个子目录 + project.json）。"""
    ws = _workspace_dir(video)
    for sub in ("01_extract", "02_translate", "03_tts", "04_output"):
        os.makedirs(os.path.join(ws, sub), exist_ok=True)
    if not os.path.isfile(os.path.join(ws, "project.json")):
        _create_manifest(video)


def _normalize_core_extract_files(state, extract_dir: str, video_name: str,
                                  skip_demucs: bool) -> None:
    """core LOAD+EXTRACT 产物 → 工作目录标准名 (实现见 core/compat/cli_bridge)。"""
    from core.compat.cli_bridge import normalize_core_extract_files
    normalize_core_extract_files(state, extract_dir, video_name, skip_demucs)


def step_extract(video: str, lang: str | None, model: str, device: str,
                  compute_type: str = "float16",
                  backup_dir: str = "", skip_defect_check: bool = False,
                  skip_demucs: bool = False, skip_align: bool = False,
                  align_lang: str | None = None, num_workers: int = 1,
                  enable_speaker_diarization: bool = False,
                  force: bool = False,
                  checkpoint: PipelineCheckpoint | None = None) -> None:
    """步骤 1 (core): WorkflowOrchestrator LOAD+EXTRACT (架构收束 P2)。

    缺陷检测、音频提取、背景乐分离、VAD+ASR、wav2vec2 对齐、说话人分离
    统一由 core passes 执行, persist v2 timeline.json (唯一事实源)。
    extract_subtitles.py 已退役。
    """
    ws_dir = _workspace_dir(video)
    ck = checkpoint or PipelineCheckpoint.load(ws_dir)

    name = os.path.splitext(os.path.basename(video))[0]
    extract_dir = os.path.join(os.path.dirname(video), f"{name}_project", "01_extract")

    # 验证输出文件是否存在（用户可能删了部分文件希望重跑）
    ck.verify_files({
        "source_srt": os.path.join(extract_dir, "source.srt"),
        "audio_wav": os.path.join(extract_dir, "audio.wav"),
        "vocals_wav": os.path.join(extract_dir, "vocals.wav"),
        "instrumental_wav": os.path.join(extract_dir, "instrumental.wav"),
        "transcript_json": os.path.join(extract_dir, "transcript.json"),
        "vad_segments": os.path.join(extract_dir, "vad_segments.json"),
        "timeline": os.path.join(extract_dir, "timeline.json"),
    })

    if ck.is_step_done("extract") and not force:
        print("\n[1/3] 字幕提取 — 已完成 (checkpoint)，跳过")
        return

    logger.info("[STAGE] [1/4] 字幕提取 + 语音识别开始")
    print("\n[1/3] 字幕提取...")
    ck.start_step("extract")
    ck.save()

    from types import SimpleNamespace
    from core.engine import WorkflowOrchestrator
    from core.config.workflow_policy import WorkflowPolicy
    from core.config.global_config import GlobalConfig
    from core.compat.cli_bridge import build_pass_factory
    from core.runtime.timeline_io import persist_state

    target_lang = lang or "zh"
    policy = WorkflowPolicy.extract_only_preset(target_lang=target_lang)
    gcfg = GlobalConfig()

    args = SimpleNamespace(
        model=model, device=device, compute_type=compute_type,
        num_workers=num_workers, skip_demucs=skip_demucs,
        skip_defect_check=skip_defect_check, skip_align=skip_align,
        align_lang=align_lang, engine=None, num_speakers=0,
        enable_speaker_diarization=enable_speaker_diarization,
        enable_emotion=False, verification_mode=None,
        caption_font=None, caption_font_size=None, caption_font_color=None,
        caption_stroke_width=None, caption_stroke_color=None,
        caption_bg_color=None, caption_alignment=None, caption_position=None,
        caption_max_lines=None, caption_width_ratio=None,
    )
    pass_factory = build_pass_factory(args, video, ws_dir, target_lang, gcfg)

    orchestrator = WorkflowOrchestrator(policy=policy, global_config=gcfg)
    orchestrator.set_pass_factory(pass_factory)

    def _orchestrator_progress(report) -> None:
        print(f"  [{report.stage_label}] {report.message}")

    orchestrator.set_progress_callback(_orchestrator_progress)

    try:
        state = orchestrator.run(video)
    except Exception as exc:
        logger.error(f"WorkflowOrchestrator 提取失败: {exc}")
        print(f"  [X] 字幕提取失败: {exc}")
        ck.fail_step("extract", str(exc), error_type="APPLICATION")
        ck.save()
        sys.exit(1)

    # persist v2 timeline.json (唯一事实源, GUI 可读)
    persist_state(state, ws_dir, video, target_lang,
                  project_id=os.path.basename(ws_dir))

    # 产物标准名适配 (后续步骤依赖 audio.wav/vocals.wav/instrumental.wav/source.srt)
    _normalize_core_extract_files(state, extract_dir, name, skip_demucs)

    ws = workspace_paths(video)

    # 如果未跳过 Demucs 但没有产出 instrumental.wav，提前警告
    if not skip_demucs and not os.path.isfile(ws["instrumental_wav"]):
        print("[WARN] Demucs 背景乐分离未生成 instrumental.wav，后续 TTS 步骤将不使用背景音乐")

    # Record output hashes for change detection
    file_map = {
        "source_srt": ws["source_srt"],
        "transcript_json": ws["transcript_json"],
        "audio_wav": ws["audio_wav"],
        "vocals_wav": ws["vocals_wav"],
        "instrumental_wav": ws["instrumental_wav"],
        "vad_segments": ws["vad_segments"],
        "timeline": ws["timeline"],
    }
    from pipeline.checkpoint import _file_sha256
    output_hashes = {k: _file_sha256(p) for k, p in file_map.items() if os.path.isfile(p)}
    ck.complete_step("extract", output_hashes=output_hashes)
    ck.save()

    if backup_dir:
        backup_step("01_extract", [extract_dir], backup_dir)
    _manifest_set_step(video, "extract", "completed")
    _manifest_set_files(video, {
        "source_srt": "01_extract/source.srt",
        "transcript": "01_extract/transcript.json",
        "audio": "01_extract/audio.wav",
        "vocals": "01_extract/vocals.wav",
        "instrumental": "01_extract/instrumental.wav",
        "vad_segments": "01_extract/vad_segments.json",
        "timeline": "01_extract/timeline.json",
    })
    print("  [OK] 字幕提取完成")


def _load_target_lang() -> str:
    """从 config/translate.yaml 读目标语言 (与旧路径一致), 无配置显式默认 zh。"""
    translate_yaml = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
    if not os.path.isfile(translate_yaml):
        return "zh"
    import yaml as _yaml
    with open(translate_yaml, "r", encoding="utf-8") as _f:
        _tc = _yaml.safe_load(_f) or {}
    _tl = (_tc.get("translate") or {}).get("target_lang", "")
    return _tl if _tl else "zh"


def step_translate_core(video: str, force: bool = False) -> str:
    """步骤 2 (core 默认): 使用 WorkflowOrchestrator 驱动翻译 + SRT 导出。(批次02 §四第二步)

    CLI 默认路径 (Phase 4 收敛): 新引擎 (bible + 逐句 + 质量闭环)。
    完成后 persist v2 到 01_extract/timeline.json (唯一事实源, GUI 编辑可读译文)。
    """
    from core.engine import WorkflowOrchestrator
    from core.engine.pass_factory import create_pass_factory
    from core.config import WorkflowPolicy
    from core.engine.progress import ProgressReport

    ws_dir = _workspace_dir(video)
    ws = workspace_paths(video) or {}
    ck = PipelineCheckpoint.load(ws_dir)

    if ck.is_step_done("translate_core") and not force:
        print("\n[2/3] 翻译 (core) — 已完成 (checkpoint)，跳过")
        return ws.get("machine_srt") or os.path.join(ws_dir, "02_translate", "machine.srt")

    logger.info("[STAGE] [2/4] WorkflowOrchestrator 翻译开始")
    print("\n[2/3] 翻译 (WorkflowOrchestrator)...")
    ck.start_step("translate_core")
    ck.save()

    # 读取 transcript 数据
    transcript_path = os.path.join(ws_dir, "01_extract", "transcript.json")
    speaker_timeline_path = os.path.join(ws_dir, "01_extract", "speaker_timeline.json")

    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)
    segments = transcript.get("segments", [])
    source_lang = transcript.get("language", "")

    speaker_timeline = None
    if os.path.exists(speaker_timeline_path):
        with open(speaker_timeline_path, "r", encoding="utf-8") as f:
            st_data = json.load(f)
        speaker_timeline = [
            (t["speaker"], t["start"], t["end"], t.get("confidence", 0.5))
            for t in st_data.get("turns", [])
        ]

    # 目标语言从 translate.yaml 读 (CLI 切默认后保持一致), 驱动 policy + 翻译 pass
    target_lang = _load_target_lang()

    # 翻译由 LLMTranslationPass 默认客户端承担 (config/translate.yaml),
    # 无 key 时响亮报错并置人工审核, 不再静默 mock。
    # 构建 Pass 工厂（闭包注入运行时依赖）
    machine_srt = os.path.join(ws_dir, "02_translate", "machine.srt")
    os.makedirs(os.path.dirname(machine_srt), exist_ok=True)
    audio_path = os.path.join(ws_dir, "01_extract", "audio.wav")
    # 质量策略按配置选择 (translate.yaml verification_mode: logic_gate|xcomet →
    # GlobalConfig gate.mode); quality_check 与 refine_translation 共用, 保证重翻闭环判定一致
    from core.quality.protocol import create_strategy
    from core.config.global_config import GlobalConfig as _GC
    # from_legacy_yaml 默认路径为空串 (不读 yaml) — 显式传 config 路径
    global_config = _GC.from_legacy_yaml("config/translate.yaml", "config/tts.yaml")
    gate_mode = global_config.project.translation.get("gate", {}).get("mode", "xcomet")
    factory = create_pass_factory(
        translate_fn=None,
        target_lang=target_lang,
        segments=segments,
        speaker_timeline=speaker_timeline,
        output_path=machine_srt,
        video_path=video,
        audio_path=audio_path,
        workspace_dir=ws_dir,
        quality_strategy=create_strategy(gate_mode),
    )

    # 构建编排器（CLI 专用: EXTRACT 阶段用注入的提取产物建事件, 不重跑 ASR;
    # TRANSLATE 含质量闭环 (quality_check + refine_translation);
    # 去掉 TTS 阶段, CLI 翻译步骤只产出译文 + SRT)
    policy = WorkflowPolicy.quick_preset(target_lang)
    from core.config.workflow_policy import StageConfig, WorkflowStage
    policy.stages[WorkflowStage.EXTRACT] = StageConfig(
        stage=WorkflowStage.EXTRACT,
        passes=["asr_to_ir", "segmentation", "semantic_merge"],
    )
    policy.stages[WorkflowStage.TRANSLATE] = StageConfig(
        stage=WorkflowStage.TRANSLATE,
        passes=["preprocess_translation", "translate", "quality_check",
                "refine_translation"],
    )
    policy.stages.pop(WorkflowStage.TTS, None)
    # 续跑场景 (v2 timeline 已有事件): 跳过 EXTRACT, 直接走翻译链 —
    # asr_to_ir 无条件重建会丢已加载译文, 且对空 words 事件切分产生坏段
    tl_path_check = os.path.join(ws_dir, "01_extract", "timeline.json")
    if os.path.isfile(tl_path_check):
        with open(tl_path_check, "r", encoding="utf-8") as f:
            _tl_data = json.load(f)
        if _tl_data.get("events"):
            policy.stages.pop(WorkflowStage.EXTRACT, None)
    global_config = _GC.from_legacy_yaml("config/translate.yaml", "config/tts.yaml")
    orchestrator = WorkflowOrchestrator(
        policy=policy,
        global_config=global_config,
        pass_factory=factory,
    )

    # 进度回调：CLI 格式化输出 + [JSON] 结构化行供 WebUI 消费 (批次11 §阶段A)
    def _orchestrator_progress(report: ProgressReport) -> None:
        print(f"  [{report.stage_label}] {report.message}")
        json_line = json.dumps(report.to_dict(), ensure_ascii=False)
        print(f"[JSON] {json_line}")

    orchestrator.set_progress_callback(_orchestrator_progress)

    try:
        state = orchestrator.run(video)
    except RuntimeError as e:
        logger.error(f"WorkflowOrchestrator 失败: {e}")
        print(f"  [X] 编排器执行失败: {e}")
        ck.fail_step("translate_core", str(e))
        ck.save()
        raise

    print(f"  PassManager 完成: {len(state.ir.events)} events")
    print(f"  SRT 导出: {machine_srt}")

    # 导出 timeline_v2.json (02_translate, GUI SRT 桥接优先读)
    from core.runtime import SynthesisEngine
    synth = SynthesisEngine()
    rendered = synth.render_all(state)
    timeline_v2_path = os.path.join(ws_dir, "02_translate", "timeline_v2.json")
    with open(timeline_v2_path, "w", encoding="utf-8") as f:
        json.dump(rendered, f, ensure_ascii=False, indent=2)

    # Phase 4 收敛: persist v2 到 01_extract/timeline.json (唯一事实源, GUI 编辑可读译文)
    from core.runtime.timeline_io import persist_state
    persist_state(state, ws_dir, video, source_lang,
                  project_id=os.path.basename(ws_dir))

    ck.complete_step("translate_core")
    ck.save()
    print("  [OK] 翻译 (core) 完成")
    return machine_srt




def step_tts(
    video: str,
    srt_source: str,
    srt_translated: str,
    engine: str,
    config_path: str | None,
    caption_config_path: str | None,
    force: bool,
    backup_dir: str = "",
    skip_demucs: bool = False,
    caption_font: str | None = None,
    caption_font_size_mode: str | None = None,
    caption_font_size: int | None = None,
    caption_font_color: str | None = None,
    caption_stroke_width: float | None = None,
    caption_stroke_color: str | None = None,
    caption_bg_color: str | None = None,
    caption_alignment: str | None = None,
    caption_position: str | None = None,
    caption_max_lines: int | None = None,
    caption_max_font_size: int | None = None,
    caption_font_size_factor: float | None = None,
    caption_width_ratio: float | None = None,
    no_optimize_subtitles: bool = False,
    voice_clone_engine: str | None = None,
    voice_clone_device: str | None = None,
    vram_limit: int | None = None,
    clone_concurrency: int | None = None,
    cosyvoice_mode: str | None = None,
    cosyvoice_model_version: str | None = None,
    cosyvoice_model_path: str | None = None,
    cosyvoice_tts_model_version: str | None = None,
    cosyvoice_tts_model_path: str | None = None,
    cosyvoice_tts_prompt_audio: str | None = None,
    cosyvoice_tts_prompt_text: str | None = None,
    cosyvoice_tts_mode: str | None = None,
    cosyvoice_tts_lang: str | None = None,
    enable_emotion: bool | None = None,
) -> None:
    """步骤 3: TTS 合成 + 视频合并（新管线 TtsPipeline）

    支持 edge / chattts / cosyvoice 引擎，GPU 编码自动检测，
    自动合并视频段输出最终文件。
    """
    ws = workspace_paths(video)
    if not ws:
        print("[X] 工作目录不存在，请先执行字幕提取")
        sys.exit(1)

    ws_dir = _workspace_dir(video)
    ck = PipelineCheckpoint.load(ws_dir)

    instrumental = ws["instrumental_wav"] if os.path.isfile(ws["instrumental_wav"]) else None
    final_output = ws["dubbed_mp4"]

    # 验证输出文件是否存在（用户可能删了部分文件希望重跑）
    ck.verify_files({"dubbed_mp4": final_output})

    if ck.is_step_done("tts") and not force:
        print(f"\n[3/3] TTS 合成 [OK] 已完成 (checkpoint)，跳过")
        _manifest_set_step(video, "tts", "completed")
        return

    # Fallback: old file-existence check
    if os.path.isfile(final_output) and not force and not ck.is_step_done("tts"):
        print(f"\n[3/3] TTS 合成 [OK] 最终视频已存在: {final_output}")
        _manifest_set_step(video, "tts", "completed")
        return

    if not instrumental:
        if skip_demucs:
            print(f"\n[3/3] [INFO] Demucs 已跳过，不使用背景音乐")
        else:
            print()
            print(f"[WARN] [3/3] 找不到伴奏文件: {ws['instrumental_wav']}，将不使用背景音乐继续合成（可加 --skip-demucs 消除此警告）")

    logger.info("[STAGE] [3/4] TTS 语音合成开始")
    print(f"\n[3/3] TTS 语音合成 + 视频合并 ({engine})...")
    ck.start_step("tts")
    ck.save()

    from pipeline.tts_config import TTSConfig, EDGE_VOICE_MAP

    cfg = TTSConfig.from_yaml(config_path) if config_path and os.path.isfile(config_path) else TTSConfig()

    cfg.engine_type = engine
    if enable_emotion is not None:
        cfg.enable_emotion = enable_emotion

    # 目标语言：从 translate.yaml 读取并写入 TTSConfig（驱动 EdgeTTS 语音自动选择）
    translate_yaml = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
    if os.path.isfile(translate_yaml):
        try:
            import yaml as _yaml
            with open(translate_yaml, "r", encoding="utf-8") as _f:
                _tc = _yaml.safe_load(_f) or {}
            _tl = (_tc.get("translate") or {}).get("target_lang", "")
            if _tl:
                cfg.target_lang = _tl
                # __post_init__ already ran in from_yaml() / TTSConfig(); re-apply auto voice
                if cfg.voice == "zh-CN-XiaoxiaoNeural" and _tl in EDGE_VOICE_MAP:
                    cfg.voice = EDGE_VOICE_MAP[_tl]
        except Exception:
            pass

    # ── 音色克隆 CLI 覆盖 ──
    if voice_clone_engine is not None:
        cfg.voice_clone_engine = voice_clone_engine
        if voice_clone_engine != "none":
            cfg.enable_openvoice = True  # 向后兼容旧标志
    if voice_clone_device is not None:
        cfg.voice_clone_device = voice_clone_device
    if vram_limit is not None:
        cfg.voice_clone_vram_limit_mb = vram_limit
    if clone_concurrency is not None:
        cfg.voice_clone_concurrency = clone_concurrency
    if cosyvoice_mode is not None:
        cfg.cosyvoice_mode = cosyvoice_mode
    if cosyvoice_model_version is not None:
        cfg.cosyvoice_model_version = cosyvoice_model_version
    if cosyvoice_model_path is not None:
        cfg.cosyvoice_model_path = cosyvoice_model_path
    if cosyvoice_tts_model_version is not None:
        cfg.cosyvoice_tts_model_version = cosyvoice_tts_model_version
    if cosyvoice_tts_model_path is not None:
        cfg.cosyvoice_tts_model_path = cosyvoice_tts_model_path
    if cosyvoice_tts_prompt_audio is not None:
        cfg.cosyvoice_tts_prompt_audio = cosyvoice_tts_prompt_audio
    if cosyvoice_tts_prompt_text is not None:
        cfg.cosyvoice_tts_prompt_text = cosyvoice_tts_prompt_text
    if cosyvoice_tts_mode is not None:
        cfg.cosyvoice_tts_mode = cosyvoice_tts_mode
    if cosyvoice_tts_lang is not None:
        cfg.cosyvoice_tts_lang = cosyvoice_tts_lang

    # ── 字幕配置: CaptionConfig 文件 > 单独 CLI args（后者覆盖） ──
    if caption_config_path and os.path.isfile(caption_config_path):
        from pipeline.caption_config import CaptionConfig
        caption_cfg = CaptionConfig.from_yaml(caption_config_path)
        cfg.apply_caption_overrides(caption_cfg)

    if caption_font:
        cfg.caption_font = caption_font
    if caption_font_size_mode:
        cfg.caption_font_size_mode = caption_font_size_mode
    if caption_font_size is not None:
        cfg.caption_font_size = caption_font_size
    if caption_font_color:
        cfg.caption_font_color = caption_font_color
    if caption_stroke_width is not None:
        cfg.caption_stroke_width = caption_stroke_width
    if caption_stroke_color:
        cfg.caption_stroke_color = caption_stroke_color
    if caption_bg_color:
        cfg.caption_bg_color = caption_bg_color
    if caption_alignment:
        cfg.caption_alignment = caption_alignment
    if caption_position:
        cfg.caption_position = caption_position
    if caption_max_lines is not None:
        cfg.caption_max_lines = caption_max_lines
    if caption_max_font_size is not None:
        cfg.caption_max_font_size = caption_max_font_size
    if caption_font_size_factor is not None:
        cfg.caption_font_size_factor = caption_font_size_factor
    if caption_width_ratio is not None:
        cfg.caption_width_ratio = caption_width_ratio
    if no_optimize_subtitles:
        cfg.enable_subtitle_optimization = False
    cfg.enable_merge = True
    cfg.final_output_path = final_output
    cfg.output_dir = ws["tts_dir"]
    cfg.video_output_dir = os.path.join(ws["tts_dir"], "video")

    # GPU 编码器自动检测（含 preset 调整）
    from pipeline.gpu_detect import apply_best_encoder_to_config, _ENCODER_PRESETS
    apply_best_encoder_to_config(cfg)
    if cfg.video_codec in _ENCODER_PRESETS:
        cfg.video_preset = _ENCODER_PRESETS[cfg.video_codec]  # 兼容硬件编码器 preset
        print(f"  [GPU 检测] codec={cfg.video_codec} preset={cfg.video_preset}")

    # force 模式下清除上次的输出视频段，确保全新生成
    if force:
        import glob
        video_dir = cfg.video_output_dir
        if os.path.isdir(video_dir):
            removed = 0
            for f in glob.glob(os.path.join(video_dir, "TTS_*.mp4")):
                os.remove(f)
                removed += 1
            if removed:
                print(f"  [force] 已清除 {removed} 个旧视频段")

    # 运行 TtsPipeline（ChatTTS CUDA 隔离由持久子进程 chattts_worker.py 处理）
    from pipeline.tts_pipeline import TtsPipeline

    pipeline = TtsPipeline(cfg)
    tts_failed = False
    tts_error_msg = ""
    try:
        pipeline.run(
            video_path=video,
            instrumental_path=instrumental,
            translated_srt_path=srt_translated,
            source_srt_path=srt_source,
        )
    except Exception as exc:
        tts_failed = True
        tts_error_msg = f"{type(exc).__name__}: {exc}"
        import traceback
        traceback.print_exc()
    finally:
        pipeline.cleanup()

    if tts_failed:
        ck.fail_step("tts", tts_error_msg, error_type="APPLICATION")
        ck.save()
        print(f"\n[X] TTS 合成失败: {tts_error_msg}")
        print(f"  [checkpoint] TTS 已标记为失败，视频段保留在 {cfg.video_output_dir}/")
        print(f"  [checkpoint] 重启后可断点续传 (已处理的片段会自动跳过)")
        _manifest_set_step(video, "tts", "failed")
        sys.exit(1)
    elif os.path.isfile(final_output):
        sz = os.path.getsize(final_output)
        from pipeline.checkpoint import _file_sha256
        ck.complete_step("tts", output_hashes={"dubbed_mp4": _file_sha256(final_output)})
        ck.save()
        print(f"  [OK] 最终视频: {final_output} ({sz/1024/1024:.1f}MB)")
        _manifest_set_step(video, "tts", "completed")
    else:
        ck.fail_step("tts", "final output not produced", error_type="APPLICATION")
        ck.save()
        print(f"\n[X] TTS 合成未生成最终视频")
        print(f"  [checkpoint] TTS 已标记为失败，重启后可断点续传")
        _manifest_set_step(video, "tts", "failed")
        sys.exit(1)
    _manifest_set_files(video, {"dubbed": "04_output/dubbed.mp4"})
    if backup_dir:
        backup_step("03_tts_done", [final_output], backup_dir)


def export_external_srt(video: str, srt_source: str, srt_translated: str,
                         mode: str | None, config_path: str | None) -> None:
    """导出外挂字幕优化版。"""
    from pipeline.external_subtitle_optimizer import (
        optimize_srt, optimize_bilingual, load_ext_subtitle_config,
    )

    cfg = load_ext_subtitle_config(config_path)
    mode = mode or cfg.get("mode", "bilingual")
    out_dir = os.path.join(os.path.dirname(video),
                           f"{os.path.splitext(os.path.basename(video))[0]}_project",
                           "04_output")

    print(f"\n[+] 外挂字幕优化 ({mode})...")

    if mode == "target_only":
        out_path = os.path.join(out_dir, "optimized.srt")
        stats = optimize_srt(srt_translated, out_path, lang=_detect_srt_lang(srt_translated))
        print(f"  译文版: {out_path}")
    elif mode == "source_only":
        out_path = os.path.join(out_dir, "optimized.source.srt")
        stats = optimize_srt(srt_source, out_path, lang=_detect_srt_lang(srt_source))
        print(f"  原文版: {out_path}")
    else:  # bilingual
        out_path = os.path.join(out_dir, "optimized.bilingual.srt")
        lang = _detect_srt_lang(srt_translated)
        stats = optimize_bilingual(srt_translated, srt_source, out_path, lang=lang)
        print(f"  双语版: {out_path}")

    print(f"  总{stats['total']}条 调整{stats['adjusted']}条 合并{stats['merged']}条")


def _detect_srt_lang(srt_path: str) -> str:
    """从 SRT 文件内容推测语言代码。"""
    from pipeline.external_subtitle_optimizer import parse_srt, detect_script
    entries = parse_srt(srt_path)
    if not entries:
        return "zh"
    script = detect_script(entries[0]["text"])
    return {"cjk": "zh", "latin": "en", "arabic": "ar"}.get(script, "zh")


def main():
    setup_hf_env()

    parser = argparse.ArgumentParser(
        description="Translate Video — 一站式翻译管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py video.mp4
  python main.py video.mp4 --lang ja                # 日语 + wav2vec2 对齐
  python main.py video.mp4 --engine chattts          # 离线 TTS
  python main.py video.mp4 --lang ja --engine chattts --skip-translate
  python main.py video.mp4 --skip-tts                # 只做字幕提取+翻译
        """,
    )

    parser.add_argument("video", help="源视频文件路径")
    parser.add_argument("--lang", default=None,
                        help="视频源语言代码，指定后自动启用 wav2vec2 对齐 (en/ja/zh)")
    parser.add_argument("--model", default="turbo",
                        help="whisper 模型大小 (tiny/base/small/medium/turbo/large-v3)")
    parser.add_argument("--device", default="cuda",
                        help="计算设备 (cuda/cpu)")
    parser.add_argument("--compute-type", default="float16",
                        help="计算精度 (float16/int8_float16/int8/float32)")
    parser.add_argument("--engine", default="edge", choices=["edge", "chattts", "cosyvoice", "indextts"],
                        help="TTS 引擎 (默认 edge)")
    parser.add_argument("--config", help="TTS YAML 配置文件路径")
    parser.add_argument("--caption-config", default=None,
                        help="字幕渲染配置文件路径 (YAML 格式)")
    parser.add_argument("--voice-clone-engine", default=None,
                        choices=["openvoice", "cosyvoice", "none"],
                        help="音色克隆引擎 (openvoice/cosyvoice/none, 覆盖配置文件)")
    parser.add_argument("--voice-clone-device", default=None,
                        choices=["auto", "cuda:0", "cpu"],
                        help="克隆推理设备")
    parser.add_argument("--vram-limit", type=int, default=None,
                        help="显存上限(MB), 0=自动检测")
    parser.add_argument("--clone-concurrency", type=int, default=None,
                        help="音色克隆并发数")
    parser.add_argument("--cosyvoice-mode", default=None,
                        choices=["local", "docker"],
                        help="CosyVoice 运行模式 (local/docker)")
    parser.add_argument("--cosyvoice-model-version", default=None,
                        choices=["v2", "v3"],
                        help="CosyVoice 模型版本 (v2/v3)")
    parser.add_argument("--cosyvoice-model-path", default=None,
                        help="CosyVoice 模型 checkpoint 路径")
    parser.add_argument("--cosyvoice-tts-model-version", default=None,
                        choices=["v2", "v3"],
                        help="CosyVoice TTS 模型版本 (v2/v3)")
    parser.add_argument("--cosyvoice-tts-model-path", default=None,
                        help="CosyVoice TTS 模型 checkpoint 路径")
    parser.add_argument("--cosyvoice-tts-prompt-audio", default=None,
                        help="CosyVoice TTS 参考说话人音频路径")
    parser.add_argument("--cosyvoice-tts-prompt-text", default=None,
                        help="CosyVoice TTS 参考音频转录文本")
    parser.add_argument("--cosyvoice-tts-mode", default=None,
                        help="CosyVoice TTS 合成模式 (固定 cross_lingual)")
    parser.add_argument("--cosyvoice-tts-lang", default=None,
                        help="CosyVoice TTS 语言标签 (zh/en/ja/ko/yue)")
    parser.add_argument("--enable-emotion", action="store_true", default=None,
                        help="启用情感分析 (仅 ChatTTS). 不传则使用配置文件值")
    parser.add_argument("--skip-extract", action="store_true",
                        help="跳过字幕提取")
    parser.add_argument("--skip-defect-check", action="store_true",
                        help="跳过音频缺陷检测 (NODE 1.5)")
    parser.add_argument("--skip-demucs", action="store_true",
                        help="跳过 Demucs 人声分离 (NODE 2.5)")
    parser.add_argument("--skip-align", action="store_true",
                        help="跳过 wav2vec2 强制对齐 (即使指定了 --lang)")
    parser.add_argument("--align-lang", default=None,
                        help="wav2vec2 对齐语言（默认跟随 --lang）")
    parser.add_argument("--num-workers", type=int, default=1,
                        help="whisper 并发 worker 数 (1=串行, 2~4=并行)")
    parser.add_argument("--enable-speaker-diarization", action="store_true",
                        help="启用说话人分离 (pyannote, 默认关闭)")
    parser.add_argument("--verification-mode", default=None,
                        choices=["joint_formula", "logic_gate"],
                        help="闭环验证模式: joint_formula (联合公式) | logic_gate (逻辑门控)")
    parser.add_argument("--skip-translate", action="store_true",
                        help="跳过翻译")
    parser.add_argument("--skip-tts", action="store_true",
                        help="跳过 TTS 合成")
    parser.add_argument("--force", action="store_true",
                        help="强制重新执行所有步骤")
    parser.add_argument("--backup-dir", default="",
                        help="步骤备份目录（如 debug_backups），每一步自动保存副本")
    parser.add_argument("--caption-font", default=None,
                        help="字幕字体文件路径")
    parser.add_argument("--caption-font-size-mode", default=None,
                        choices=["adaptive", "fixed"],
                        help="字号模式 adaptive（自适应）| fixed（固定）")
    parser.add_argument("--caption-font-size", type=int, default=None,
                        help="字幕字号（像素）")
    parser.add_argument("--caption-font-color", default=None,
                        help="字幕字体颜色")
    parser.add_argument("--caption-stroke-width", type=float, default=None,
                        help="字幕描边宽度")
    parser.add_argument("--caption-stroke-color", default=None,
                        help="字幕描边颜色")
    parser.add_argument("--caption-bg-color", default=None,
                        help="字幕背景色 (rgba格式)")
    parser.add_argument("--caption-alignment", default=None,
                        help="字幕对齐方式 center/left/right")
    parser.add_argument("--caption-position", default=None,
                        help="字幕位置 bottom/top")
    parser.add_argument("--caption-max-lines", type=int, default=None,
                        help="字幕最大行数 (默认 2)")
    parser.add_argument("--caption-max-font-size", type=int, default=None,
                        help="字幕最大字号 px (0=自动)")
    parser.add_argument("--caption-font-size-factor", type=float, default=None,
                        help="字号缩放因子 (默认 0.030)")
    parser.add_argument("--caption-width-ratio", type=float, default=None,
                        help="字幕宽度比例 (默认 0.85)")
    parser.add_argument("--no-optimize-subtitles", action="store_true",
                        help="禁用字幕拆分优化")
    parser.add_argument("--export-external-srt", action="store_true",
                        help="流水线完成后输出外挂字幕优化版")
    parser.add_argument("--bootstrap", action="store_true",
                        help="仅运行 Bootstrap 阶段 (extract + translate + validate)，"
                             "完成后暂停不执行 TTS/导出")
    parser.add_argument("--ext-srt-mode", default=None,
                        choices=["target_only", "source_only", "bilingual"],
                        help="外挂字幕输出模式（覆盖配置文件）")
    parser.add_argument("--ext-srt-config", default=None,
                        help="外挂字幕配置文件路径")

    args = parser.parse_args()
    video = os.path.abspath(args.video)

    if not os.path.isfile(video):
        print(f"错误: 视频不存在: {video}")
        sys.exit(1)

    t_start = time.time()
    print(f"\n  视频: {video}")
    print(f"  语言: {args.lang or '自动检测'}")
    print(f"  TTS:  {args.engine}\n")

    # ── 创建工作目录 ──
    _ensure_workspace(video)

    # ── 断点续传: 加载/创建 checkpoint ──
    ws_dir = _workspace_dir(video)
    ck = PipelineCheckpoint.load(ws_dir)

    # Clean .tmp residue from previous crash
    ck.clean_tmp_files(ws_dir)
    for sub in ("01_extract", "02_translate", "03_tts", "04_output"):
        ck.clean_tmp_files(os.path.join(ws_dir, sub))

    # Detect and fix stale 'running' states
    crashed_steps = ck.recover_from_crash()
    if crashed_steps:
        print(f"  [checkpoint] 检测到上次崩溃，将重新执行: {', '.join(crashed_steps)}")

    # First run: record video fingerprint
    if not ck.video_hash:
        ck.init_from_video(video)
    elif ck.check_video_changed(video):
        print("  [checkpoint] 源视频已变更，所有步骤将重新执行")
        ck.init_from_video(video)
        for step in ("extract", "translate", "tts"):
            ck.steps[step] = StepState()

    ck.save()

    # Build CLI params fingerprint for change detection
    _cli_params = {k: v for k, v in vars(args).items() if v is not None and v is not False}
    _cli_params.pop("video", None)

    try:
        # ── 步骤 1: 字幕提取 ──
        # extract_subtitles.py 包含: 缺陷检测 → 音频提取 → VAD → 转录 → 对齐 → SRT
        if not args.skip_extract:
            step_extract(video, lang=args.lang, model=args.model, device=args.device,
                         compute_type=args.compute_type,
                         backup_dir=args.backup_dir, skip_defect_check=args.skip_defect_check,
                         skip_demucs=args.skip_demucs, skip_align=args.skip_align,
                         align_lang=args.align_lang, num_workers=args.num_workers,
                         enable_speaker_diarization=args.enable_speaker_diarization,
                         force=args.force, checkpoint=ck)
        else:
            print("[1/3] 字幕提取 — 已跳过 (--skip-extract)")

        # 确定原始 SRT 路径
        srt_source = guess_source_srt(video)
        if not srt_source:
            print("[X] 找不到字幕文件。请先执行字幕提取或指定正确路径。")
            sys.exit(1)

        # ── 步骤 2: 翻译 ──
        # core 新引擎 (bible + 逐句 + 质量闭环) — SRT_Translator 已退役 (架构收束 P3)
        srt_translated = srt_source
        if not args.skip_translate:
            srt_translated = step_translate_core(video, force=args.force)
        else:
            print("[2/3] 翻译 — 已跳过 (--skip-translate)")
            existing = guess_translated_srt(video)
            if existing:
                srt_translated = existing
                print(f"  使用已有翻译: {os.path.basename(existing)}")

        # ── 步骤 3: TTS ──
        # 翻译阶段全部 CPU（质量门控 + xCOMET），
        # ChatTTS 运行在独立子进程中，无需主进程 CUDA 清理。

        if args.bootstrap:
            print("\n[3/3] TTS 合成 — 已跳过 (--bootstrap, Bootstrap 阶段完成)")
            _manifest_set_step(video, "tts", "bootstrap_only")
            # 标记为 Reviewable，等待用户确认后再导出
            ws = workspace_paths(video)
            if ws:
                from core.runtime.workspace import WorkspaceResolver
                wr = WorkspaceResolver(video)
                wr.transition("reviewable")
        elif not args.skip_tts:
            step_tts(
                video,
                srt_source=srt_source,
                srt_translated=srt_translated,
                engine=args.engine,
                config_path=args.config,
                caption_config_path=args.caption_config,
                force=args.force,
                backup_dir=args.backup_dir,
                skip_demucs=args.skip_demucs,
                caption_font=args.caption_font,
                caption_font_size_mode=args.caption_font_size_mode,
                caption_font_size=args.caption_font_size,
                caption_font_color=args.caption_font_color,
                caption_stroke_width=args.caption_stroke_width,
                caption_stroke_color=args.caption_stroke_color,
                caption_bg_color=args.caption_bg_color,
                caption_alignment=args.caption_alignment,
                caption_position=args.caption_position,
                caption_max_lines=args.caption_max_lines,
                caption_max_font_size=args.caption_max_font_size,
                caption_font_size_factor=args.caption_font_size_factor,
                caption_width_ratio=args.caption_width_ratio,
                no_optimize_subtitles=args.no_optimize_subtitles,
                voice_clone_engine=args.voice_clone_engine,
                voice_clone_device=args.voice_clone_device,
                vram_limit=args.vram_limit,
                clone_concurrency=args.clone_concurrency,
                cosyvoice_mode=args.cosyvoice_mode,
                cosyvoice_model_version=args.cosyvoice_model_version,
                cosyvoice_model_path=args.cosyvoice_model_path,
                cosyvoice_tts_model_version=args.cosyvoice_tts_model_version,
                cosyvoice_tts_model_path=args.cosyvoice_tts_model_path,
                cosyvoice_tts_prompt_audio=args.cosyvoice_tts_prompt_audio,
                cosyvoice_tts_prompt_text=args.cosyvoice_tts_prompt_text,
                cosyvoice_tts_mode=args.cosyvoice_tts_mode,
                cosyvoice_tts_lang=args.cosyvoice_tts_lang,
                enable_emotion=args.enable_emotion,
            )
        else:
            print("[3/3] TTS 合成 — 已跳过 (--skip-tts)")

        # ── 外挂字幕优化导出 ──
        if args.export_external_srt:
            export_external_srt(
                video, srt_source, srt_translated,
                mode=args.ext_srt_mode, config_path=args.ext_srt_config,
            )

        elapsed = time.time() - t_start
        print(f"\n{'='*50}")
        print(f"[OK] 全部完成! 耗时: {elapsed/60:.1f} 分钟")
        print(f"{'='*50}")

    except KeyboardInterrupt:
        print("\n[!] 用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[X] 流程失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
