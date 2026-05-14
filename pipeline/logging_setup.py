"""
系统级日志配置 — 统一的终端 + 文件日志输出。

所有模块通过 `get_logger(__name__)` 获取 logger，
终端格式简洁带时间戳，文件日志保留完整堆栈。

用法:
    from pipeline.logging_setup import setup_logging, get_logger
    setup_logging(project_root=PROJECT_ROOT)
    logger = get_logger(__name__)
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CONSOLE_FMT = logging.Formatter(
    "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
_FILE_FMT = logging.Formatter(
    "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_setup_done = False


def setup_logging(
    log_dir: Path | str | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> None:
    """配置系统级日志（幂等，多次调用不重复添加 handler）。"""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # 终端 handler (stderr — uvicorn 不会截获)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(console_level)
    ch.setFormatter(_CONSOLE_FMT)
    root.addHandler(ch)

    # 文件 handler
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "server.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(file_level)
        fh.setFormatter(_FILE_FMT)
        root.addHandler(fh)

    # 降低第三方库日志噪音
    for _name in ("asyncio", "uvicorn", "uvicorn.access", "urllib3", "huggingface_hub"):
        logging.getLogger(_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块 logger。"""
    return logging.getLogger(name)
