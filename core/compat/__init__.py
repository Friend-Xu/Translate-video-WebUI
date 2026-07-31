"""
core/compat — Legacy Pipeline 兼容桥接层 (计划 §11)
"""
from core._compat_module import (
    compat_setup_logging, compat_load_checkpoint,
    compat_resolve_prompt_variables, compat_get_lang_labels,
    compat_model_manager, compat_detect_env,
    compat_chattts_factory, compat_calc_chattts_workers,
    compat_preflight_analyze, compat_mux_video_audio,
    compat_optimize_external_srt, compat_load_ext_subtitle_config,
    compat_validate_workspace,
    compat_decode_exit_code, compat_is_native_crash,
)
