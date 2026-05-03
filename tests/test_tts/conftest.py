"""
TTS 测试全局配置。提供公共 fixture 和 mock 工具。
"""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """提供临时目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_srt_content() -> str:
    """标准测试用 SRT 字幕内容"""
    return """1
00:00:01,000 --> 00:00:04,000
欢迎来到 Minecraft 模组介绍

2
00:00:05,000 --> 00:00:08,500
今天我们来试试这个超好玩的模组

3
00:00:09,000 --> 00:00:12,000
他可以让你的世界变得更加有趣
"""


@pytest.fixture
def sample_srt_path(temp_dir, sample_srt_content) -> str:
    """创建临时 SRT 文件并返回路径"""
    path = os.path.join(temp_dir, "test.srt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(sample_srt_content)
    return path


@pytest.fixture
def project_root() -> str:
    """项目根目录"""
    return str(Path(__file__).resolve().parents[2])


@pytest.fixture
def mock_tts_config():
    """标准测试用 TTS 配置"""
    from pipeline.tts_config import TTSConfig
    return TTSConfig(
        engine_type="edge",
        base_speed=30,
        max_speed=70,
        speed_tolerance=0.15,
        threading_workers=2,
        enable_caption=False,
        enable_openvoice=False,
    )
