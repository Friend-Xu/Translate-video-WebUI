"""whisperx_local — 兼容 shim：真实代码位于 core/adapters/whisperx_local/。

通过 __path__ 重定向，让 `from whisperx_local.alignment import ...` 直接解析到新位置，
不触发 core/__init__.py 的重依赖链（对齐子进程需保持轻量）。
"""
import os

_pkg_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core", "adapters", "whisperx_local",
)
__path__ = [_pkg_dir]

from whisperx_local.alignment import align, load_align_model  # noqa: E402

__all__ = ["align", "load_align_model"]
