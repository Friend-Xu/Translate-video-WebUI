#!/usr/bin/env python3
"""
Translate Video — 一站式翻译管线

基于项目现有成熟模块编排：
  extract_subtitles.py  → 字幕提取 + 强制对齐（指定 --lang 时自动启用 wav2vec2）
  SRT_Translator        → 翻译
  TermReplacer          → 术语替换
  TtsPipeline           → TTS 合成 + 视频合并（新管线）

用法:
    python main.py <视频路径> [--lang en] [--engine chattts] [--skip-tts]

参数与 translate_video.py、extract_subtitles.py 保持一致。
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

# 防 CUDA 碎片化：PyTorch 2.0+ expandable segments 允许内存段动态伸缩，
# 配合 max_split_size_mb 防止大块被切碎后无法归还。
# 必须在 torch 首次导入前设置（ChatTTS / pipeline 模块内懒加载 torch）。
if os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128"

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
        ├── 01_extract/    ← 提取阶段
        ├── 02_translate/  ← 翻译阶段
        ├── 03_tts/        ← TTS 片段
        └── 04_output/     ← 最终输出

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
        "tts_dir": os.path.join(ws, "03_tts"),
        "output_dir": os.path.join(ws, "04_output"),
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
        "dubbed_mp4": os.path.join(ws, "04_output", "dubbed.mp4"),
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
    """创建初始 project.json。"""
    now = datetime.datetime.now().isoformat()
    data = {
        "version": 1,
        "video_path": video.replace("\\", "/"),
        "created_at": now,
        "updated_at": now,
        "pipeline": {"extract": "pending", "translate": "pending", "tts": "pending"},
        "files": {},
    }
    _save_manifest(video, data)
    return data


def _manifest_set_step(video: str, step: str, status: str) -> None:
    """更新管线步骤状态。"""
    ws = _workspace_dir(video)
    path = os.path.join(ws, "project.json")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
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
    data["files"].update(file_map)
    _save_manifest(video, data)


def _ensure_workspace(video: str) -> None:
    """创建工作目录（所有 4 个子目录 + project.json）。"""
    ws = _workspace_dir(video)
    for sub in ("01_extract", "02_translate", "03_tts", "04_output"):
        os.makedirs(os.path.join(ws, sub), exist_ok=True)
    if not os.path.isfile(os.path.join(ws, "project.json")):
        _create_manifest(video)


def _rename_extract_files(extract_dir: str, video_name: str) -> None:
    """将 extract_subtitles 产出的文件重命名为工作目录标准名。"""
    import shutil
    file_map = {
        f"{video_name}.srt": "source.srt",
        f"{video_name}.json": "transcript.json",
        f"{video_name}.wav": "audio.wav",
        f"{video_name}_(Vocals).wav": "vocals.wav",
        f"{video_name}_(Instrumental).wav": "instrumental.wav",
        f"{video_name}_vad_segments.json": "vad_segments.json",
    }
    for old_name, new_name in file_map.items():
        src = os.path.join(extract_dir, old_name)
        if os.path.isfile(src):
            dst = os.path.join(extract_dir, new_name)
            if src != dst:
                shutil.move(src, dst)


def step_extract(video: str, lang: str | None, model: str, device: str,
                  compute_type: str = "float16",
                  backup_dir: str = "", skip_defect_check: bool = False,
                  skip_demucs: bool = False, skip_align: bool = False,
                  align_lang: str | None = None, num_workers: int = 1,
                  force: bool = False,
                  checkpoint: PipelineCheckpoint | None = None) -> None:
    """步骤 1: 委托 extract_subtitles.py 完成全流程。

    含缺陷检测(N1.5)、音频提取(N2)、背景乐提取(N2.5)、
    VAD+转录(N3)、wav2vec2 对齐(N3.5，指定 --lang 时启用)、
    JSON→SRT(N4)。
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
    })

    if ck.is_step_done("extract") and not force:
        print("\n[1/3] 字幕提取 — 已完成 (checkpoint)，跳过")
        return

    print("\n[1/3] 字幕提取...")
    ck.start_step("extract")
    ck.save()
    script = os.path.join(PROJECT_ROOT, "extract_subtitles.py")
    cmd = [
        sys.executable, script,
        video,
        "--out-dir", extract_dir,
        "--model", model,
        "--device", device,
        "--compute-type", compute_type,
    ]
    if lang:
        cmd.extend(["--lang", lang])
    if skip_defect_check:
        cmd.append("--skip-defect-check")
    if skip_demucs:
        cmd.append("--skip-demucs")
    if skip_align:
        cmd.append("--skip-align")
    if align_lang:
        cmd.extend(["--align-lang", align_lang])
    if num_workers > 1:
        cmd.extend(["--num-workers", str(num_workers)])

    # 子进程 UTF-8 输出兼容（Windows GBK 终端）
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"  运行: extract_subtitles.py")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    if result.returncode != 0:
        ck.fail_step("extract", f"subprocess exit code {result.returncode}",
                       error_type="APPLICATION")
        ck.save()
        print(f"[X] 字幕提取失败 (code={result.returncode})")
        sys.exit(result.returncode)

    # 标准化文件名
    _rename_extract_files(extract_dir, name)

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
    })
    print("  [OK] 字幕提取完成")


def step_translate(video: str, srt_path: str, force: bool, backup_dir: str = "",
                   checkpoint: PipelineCheckpoint | None = None,
                   skip_semantic_validation: bool = False,
                   skip_naturalness_check: bool = False) -> str:
    """步骤 2: 翻译 + 术语替换。

    输出到工作目录 02_translate/machine.srt。
    """
    target = os.path.dirname(video)
    name = os.path.splitext(os.path.basename(video))[0]
    ws = workspace_paths(video)
    output = ws["machine_srt"] if ws else os.path.join(target, f"{name}_project", "02_translate", "machine.srt")

    ws_dir = _workspace_dir(video)
    ck = checkpoint or PipelineCheckpoint.load(ws_dir)

    # 验证输出文件是否存在（用户可能删了部分文件希望重跑）
    ck.verify_files({"machine_srt": output})

    if ck.is_step_done("translate") and not force:
        print(f"  [OK] 翻译已完成 (checkpoint)，跳过")
        _manifest_set_step(video, "translate", "completed")
        _manifest_set_files(video, {"machine_srt": "02_translate/machine.srt"})
        return output

    # Fallback: old file-existence check (backward compat, no checkpoint yet)
    if os.path.isfile(output) and not force and not ck.is_step_done("translate"):
        print(f"  [OK] 翻译文件已存在: {output}")
        _manifest_set_step(video, "translate", "completed")
        _manifest_set_files(video, {"machine_srt": "02_translate/machine.srt"})
        return output

    print("\n[2/3] 字幕翻译 + 术语替换...")
    ck.start_step("translate")
    ck.save()

    sys.path.insert(0, PROJECT_ROOT)

    from SRT.SRT_Translator import SRTTranslator

    translator = SRTTranslator()
    if skip_semantic_validation:
        translator.semantic_check = False
    if skip_naturalness_check:
        translator.naturalness_check = False
    auto_srt, pending = translator.translate(srt_path)

    if pending:
        ck.fail_step("translate", "manual review pending", error_type="USER")
        ck.save()
        print(f"\n[!] 有 {getattr(translator.log, 'manual_pending', '?')} 组需人工翻译")
        print(f"  待翻文件: {pending}")
        print("  请完成人工翻译后重新运行")
        sys.exit(0)

    # 将翻译结果移到工作目录
    if os.path.isfile(auto_srt) and auto_srt != output:
        import shutil
        os.makedirs(os.path.dirname(output), exist_ok=True)
        shutil.move(auto_srt, output)

    if os.path.isfile(output):

        from pipeline.checkpoint import _file_sha256
        ck.complete_step("translate", output_hashes={"machine_srt": _file_sha256(output)})
        ck.save()
    else:
        ck.fail_step("translate", "no output file produced", error_type="APPLICATION")
        ck.save()
        print(f"  [OK] 翻译完成: {auto_srt}")
        return auto_srt

    print(f"  [OK] 翻译 + 术语替换完成: {output}")

    # 将翻译日志统一移到 02_translate/ 目录
    _translate_dir = os.path.dirname(output)
    _src_base = os.path.splitext(srt_path)[0]
    for _log_suffix in ["-translate-log.json", "-translate-io-log.json",
                        "-translate-semantic-flagged.json", "-prompt-manifest.json"]:
        _log_src = _src_base + _log_suffix
        _log_dst = os.path.join(_translate_dir, os.path.basename(_log_src))
        if os.path.isfile(_log_src) and _log_src != _log_dst:
            import shutil as _shutil
            _shutil.move(_log_src, _log_dst)

    _manifest_set_step(video, "translate", "completed")
    _manifest_set_files(video, {
        "machine_srt": "02_translate/machine.srt",
        "translate_log": "02_translate/source-translate-log.json",
        "translate_io_log": "02_translate/source-translate-io-log.json",
        "translate_semantic_flagged": "02_translate/source-translate-semantic-flagged.json",
        "prompt_manifest": "02_translate/source-prompt-manifest.json",
    })
    if backup_dir:
        backup_step("02_translate", [output], backup_dir)

    # 多维翻译质量评估 (step 2.5)
    try:
        from pipeline.quality_assessor import QualityAssessor
        ws = workspace_paths(video)
        if ws:
            qa_cfg = _load_translate_cfg_field("quality_assessment", {})
            if qa_cfg.get("enabled", True):
                assessor = QualityAssessor(
                    ws_dir=ws["workspace"],
                    semantic_threshold=qa_cfg.get("dimensions", {}).get("semantic", {}).get("threshold", 0.70),
                    naturalness_threshold=qa_cfg.get("dimensions", {}).get("naturalness", {}).get("threshold", 3.0),
                    naturalness_enabled=qa_cfg.get("dimensions", {}).get("naturalness", {}).get("enabled", True),
                    source_lang=_load_translate_cfg_field("source_lang", "auto"),
                )
                assessor.run()
                _manifest_set_files(video, {
                    "quality_report": "02_translate/quality_report.json",
                })
    except Exception as e:
        print(f"  [WARN] QualityAssessor 运行失败 (non-fatal): {e}")

    return output


def _load_translate_cfg_field(field: str, default=None):
    """从 translate.yaml 读取单个配置字段"""
    import yaml as _yaml
    cfg_path = os.path.join(os.path.dirname(__file__), "config", "translate.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = _yaml.safe_load(f)
        return cfg.get("translate", {}).get(field, default)
    except Exception:
        return default


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

    print(f"\n[3/3] TTS 语音合成 + 视频合并 ({engine})...")
    ck.start_step("tts")
    ck.save()

    from pipeline.tts_config import TTSConfig, EDGE_VOICE_MAP

    cfg = TTSConfig.from_yaml(config_path) if config_path and os.path.isfile(config_path) else TTSConfig()

    cfg.engine_type = engine

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

    # 运行新管线
    from pipeline.tts_pipeline import TtsPipeline

    pipeline = TtsPipeline(cfg)
    try:
        pipeline.run(
            video_path=video,
            instrumental_path=instrumental,
            translated_srt_path=srt_translated,
            source_srt_path=srt_source,
        )
    finally:
        pipeline.cleanup()

    if os.path.isfile(final_output):
        sz = os.path.getsize(final_output)
        from pipeline.checkpoint import _file_sha256
        ck.complete_step("tts", output_hashes={"dubbed_mp4": _file_sha256(final_output)})
        ck.save()
        print(f"  [OK] 最终视频: {final_output} ({sz/1024/1024:.1f}MB)")
    else:
        ck.fail_step("tts", "final output not produced", error_type="APPLICATION")
        ck.save()
        print(f"  [OK] TTS 合成完成（最终视频路径: {final_output}）")
    _manifest_set_step(video, "tts", "completed")
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
    parser.add_argument("--engine", default="edge", choices=["edge", "chattts", "cosyvoice"],
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
                        choices=["auto", "zero_shot", "cross_lingual"],
                        help="CosyVoice TTS 合成模式 (auto/zero_shot/cross_lingual)")
    parser.add_argument("--cosyvoice-tts-lang", default=None,
                        help="CosyVoice TTS 语言标签 (zh/en/ja/ko/yue)")
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
    parser.add_argument("--skip-semantic-validation", action="store_true",
                        help="翻译完成后跳过语义校验")
    parser.add_argument("--skip-naturalness-check", action="store_true",
                        help="翻译完成后跳过自然度检查 (PPL)")
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
                         force=args.force, checkpoint=ck)
        else:
            print("[1/3] 字幕提取 — 已跳过 (--skip-extract)")

        # 确定原始 SRT 路径
        srt_source = guess_source_srt(video)
        if not srt_source:
            print("[X] 找不到字幕文件。请先执行字幕提取或指定正确路径。")
            sys.exit(1)

        # ── 步骤 2: 翻译 ──
        srt_translated = srt_source
        if not args.skip_translate:
            srt_translated = step_translate(video, srt_source, force=args.force, backup_dir=args.backup_dir,
                                              checkpoint=ck,
                                              skip_semantic_validation=args.skip_semantic_validation,
                                              skip_naturalness_check=args.skip_naturalness_check)
        else:
            print("[2/3] 翻译 — 已跳过 (--skip-translate)")
            existing = guess_translated_srt(video)
            if existing:
                srt_translated = existing
                print(f"  使用已有翻译: {os.path.basename(existing)}")

        # ── 步骤 3: TTS ──
        # 翻译环节是纯 CPU 操作，但 TTS 需要大量 GPU 显存。
        # 提前释放 PyTorch CUDA 缓存池碎片，确保 ChatTTS 模型加载时有充足连续显存。
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        import gc; gc.collect()

        if not args.skip_tts:
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
