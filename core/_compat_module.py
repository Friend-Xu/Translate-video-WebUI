"""
core/compat — Legacy Pipeline 兼容桥接层 (计划 §11)

不重写旧模块，只在 core/ 和 pipeline/SRT 之间提供统一的适配入口。
导入此模块的文件不直接引用 pipeline/ 或 SRT/。
"""

from __future__ import annotations


# ── Logging ─────────────────────────────────────────────────────

def compat_setup_logging(log_dir=None):
    """Legacy 日志初始化桥接。"""
    from pipeline.logging_setup import setup_logging, get_logger as _gl
    lg = _gl("compat")
    if log_dir:
        setup_logging(log_dir=log_dir)
    return lg


# ── Checkpoint ──────────────────────────────────────────────────

def compat_load_checkpoint(workspace_dir: str) -> dict | None:
    """从旧 workspace 加载 checkpoint。"""
    try:
        import json, os
        ck = os.path.join(workspace_dir, "checkpoint.json")
        if not os.path.isfile(ck):
            return None
        with open(ck, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── Translation ─────────────────────────────────────────────────

def compat_resolve_prompt_variables(video_path: str, target_lang: str) -> dict:
    """解析翻译提示变量。"""
    from SRT.SRT_Translator import resolve_prompt_variables
    return resolve_prompt_variables(video_path, target_lang)


def compat_get_lang_labels() -> dict:
    from SRT.SRT_Translator import _LANG_LABELS
    return dict(_LANG_LABELS)


# ── Model Manager ───────────────────────────────────────────────

def compat_model_manager():
    from pipeline.model_manager import ModelManager
    return ModelManager


def compat_detect_env():
    from pipeline.env_detect import detect_env, assess_model_fit
    return detect_env, assess_model_fit


# ── TTS ─────────────────────────────────────────────────────────

def compat_chattts_factory():
    from pipeline.tts_chattts import ChatTTSEngine
    return ChatTTSEngine


def compat_calc_chattts_workers():
    from pipeline.tts_pipeline import calc_chattts_workers
    return calc_chattts_workers


# ── Media ───────────────────────────────────────────────────────

def compat_preflight_analyze(video_path: str):
    from pipeline.media_preflight import analyze as _a
    return _a(video_path)


def compat_mux_video_audio(*args, **kwargs):
    from pipeline.media_preflight import mux_video_audio as _m
    return _m(*args, **kwargs)


# ── External subtitle ───────────────────────────────────────────

def compat_optimize_external_srt(chinese_srt: str, source_srt: str, **kw):
    from pipeline.external_subtitle_optimizer import optimize_for_subtitle_bilingual
    return optimize_for_subtitle_bilingual(chinese_srt, source_srt, **kw)


def compat_load_ext_subtitle_config():
    from pipeline.external_subtitle_optimizer import load_ext_subtitle_config
    return load_ext_subtitle_config()


# ── Schema validation ───────────────────────────────────────────

def compat_validate_workspace(workspace_dir: str) -> dict:
    from pipeline.schema_validator import validate_workspace as _vw
    return _vw(workspace_dir)


# ── Process status ──────────────────────────────────────────────

def compat_decode_exit_code(rc: int) -> str:
    from pipeline.ntstatus import decode_exit_code
    return decode_exit_code(rc)


def compat_is_native_crash(rc: int) -> bool:
    from pipeline.ntstatus import is_native_crash
    return is_native_crash(rc)
