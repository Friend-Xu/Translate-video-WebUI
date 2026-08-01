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


def build_pass_factory(args, video_path: str, ws_dir: str, lang: str, gcfg):
    """构建 pass 工厂 — cmd_run / cmd_stage / cmd_validate / cmd_export 共用。

    args 为 argparse Namespace 或任意支持 getattr 的对象 (兼容 tvw/main)。
    """
    from core.engine.pass_factory import create_pass_factory

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
