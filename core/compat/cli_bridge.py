"""
cli_bridge — CLI 参数 → core pass 工厂桥 (架构收束 P1)

tvw.py 与 main.py 的 argparse 参数通过这里单一映射为 create_pass_factory
的运行时槽位 — 两个 CLI 入口共用一套映射, 消灭各自维护的参数桥。
core → pipeline 单向依赖 (适配器模式本意)。
"""
from __future__ import annotations
import os

# 传给 create_pass_factory 的 caption 字段 (仅非 None 传入)
_CAPTION_FIELDS = (
    "caption_font", "caption_font_size", "caption_font_color",
    "caption_stroke_width", "caption_stroke_color", "caption_bg_color",
    "caption_alignment", "caption_position", "caption_max_lines",
    "caption_width_ratio",
)


def build_caption_config(args) -> dict:
    """从 CLI args 提取非 None 的字幕配置字段。"""
    return {
        attr: getattr(args, attr, None)
        for attr in _CAPTION_FIELDS
        if getattr(args, attr, None) is not None
    }


def apply_cli_slot_overrides(args, gcfg) -> None:
    """CLI 参数 → gcfg 槽位覆盖 (extract 参数桥, 架构收束 P2)。

    与 --config-overrides 同一落点 (apply_slot_overrides); CLI 显式 flag
    优先级更高 (在 config_overrides 之后调用)。args 无对应属性时跳过。
    """
    overrides: dict[str, dict] = {}

    asr: dict = {}
    for src, dst in (("model", "model"), ("device", "device"),
                     ("compute_type", "compute_type"),
                     ("num_workers", "num_workers")):
        val = getattr(args, src, None)
        if val is not None:
            asr[dst] = val
    if getattr(args, "skip_align", False):
        asr["alignment_enabled"] = False
    align_lang = getattr(args, "align_lang", None)
    if align_lang:
        asr["language"] = align_lang
    if asr:
        overrides["asr"] = asr

    audio: dict = {}
    if getattr(args, "skip_demucs", False):
        audio["skip_demucs"] = True
    if getattr(args, "skip_defect_check", False):
        audio["validate_defect"] = False
    if audio:
        overrides["audio"] = audio

    if overrides:
        gcfg.apply_slot_overrides(overrides)


def normalize_core_extract_files(state, extract_dir: str, video_name: str,
                                 skip_demucs: bool) -> None:
    """将 core LOAD+EXTRACT 产物映射为工作目录标准名 (架构收束 P2)。

    core 产物: {stem}_extracted.wav / demucs 子目录 {model}/{stem}/{vocals,no_vocals}.wav
    / v2 timeline.json; 后续步骤依赖的标准名: audio.wav / vocals.wav /
    instrumental.wav / source.srt (原文 SRT)。
    """
    import shutil
    import glob as _glob

    src = os.path.join(extract_dir, f"{video_name}_extracted.wav")
    dst = os.path.join(extract_dir, "audio.wav")
    if os.path.isfile(src) and not os.path.isfile(dst):
        shutil.move(src, dst)

    if not skip_demucs:
        # demucs 子目录 {model}/{audio_stem}/{vocals,no_vocals}.wav —
        # audio_stem 是输入音频名 (如 Test_JP_extracted), 不是视频名
        for pattern, dst_name in (("vocals.wav", "vocals.wav"),
                                  ("no_vocals.wav", "instrumental.wav")):
            matches = _glob.glob(os.path.join(extract_dir, "*", "*", pattern))
            if matches and not os.path.isfile(os.path.join(extract_dir, dst_name)):
                shutil.move(matches[0], os.path.join(extract_dir, dst_name))

    # source.srt ← v2 timeline.json (无译文时 SRTExportPass 回退原文)
    source_srt = os.path.join(extract_dir, "source.srt")
    if not os.path.isfile(source_srt):
        from core.passes.srt_export_pass import SRTExportPass
        SRTExportPass(output_path=source_srt).apply(state)


def build_pass_factory(args, video_path: str, ws_dir: str, lang: str, gcfg):
    """构建 pass 工厂 — cmd_run / cmd_stage / cmd_validate / cmd_export 共用。

    args 为 argparse Namespace 或任意支持 getattr 的对象 (兼容 tvw/main)。
    """
    from core.engine.pass_factory import create_pass_factory

    apply_cli_slot_overrides(args, gcfg)

    # 导入策略模块以触发装饰器注册
    import core.quality.logic_gate_strategy  # noqa: F401 — 注册 logic_gate
    import core.quality.xcomet_strategy      # noqa: F401 — 注册 xcomet
    from core.quality.protocol import create_strategy as create_quality_strategy

    stem = os.path.splitext(os.path.basename(video_path))[0]
    extract_dir = os.path.join(ws_dir, "01_extract")
    audio_path = os.path.join(extract_dir, f"{stem}_extracted.wav")
    vocals_path = os.path.join(extract_dir, f"{stem}_vocals.wav")

    quality_name = gcfg.project.translation.get("quality_strategy", "logic_gate")
    quality_strategy = create_quality_strategy(quality_name, gcfg)

    caption_config = build_caption_config(args)

    return create_pass_factory(
        translate_fn=None,
        target_lang=lang,
        video_path=video_path,
        audio_path=audio_path,
        output_dir=ws_dir,
        workspace_dir=ws_dir,
        engine=getattr(args, "engine", None) or "edge",
        quality_strategy=quality_strategy,
        num_workers=getattr(args, "num_workers", 1),
        enable_speaker_diarization=getattr(args, "enable_speaker_diarization", False),
        num_speakers=getattr(args, "num_speakers", 0),
        enable_emotion=getattr(args, "enable_emotion", False),
        verification_mode=getattr(args, "verification_mode", None),
        skip_demucs=getattr(args, "skip_demucs", False),
        caption_config=caption_config if caption_config else None,
    )
