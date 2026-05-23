"""
Pipeline 共享日志配置。

每个模块通过 `get_logger(__name__)` 获取 logger，
输出格式 `[LEVEL] module: message`，兼容前端 LogPanel 的级别解析。
"""

from __future__ import annotations

import io
import logging
import sys


_PIPELINE_LOGGER = "pipeline"


def _configure_root() -> None:
    """配置 pipeline 根 logger（只执行一次）。"""
    root = logging.getLogger(_PIPELINE_LOGGER)
    if root.handlers:
        return

    utf8_stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    handler = logging.StreamHandler(utf8_stderr)
    handler.setFormatter(logging.Formatter(
        "[%(levelname)-5s] %(name)s: %(message)s"
    ))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    root.propagate = False


_configure_root()


def get_logger(name: str) -> logging.Logger:
    """获取 pipeline 子模块 logger。

    Args:
        name: 通常传 __name__ (如 "pipeline.tts_timing")

    Returns:
        配置好的 Logger 实例
    """
    return logging.getLogger(name)
