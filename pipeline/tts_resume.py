"""
断点续传模块 — ResumeManager

基于输出文件存在性判断处理状态，消除独立的 JSON 状态文件。
每次运行默认全新，不再有跨运行的状态残留。
"""

from __future__ import annotations

import os
import glob
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class ResumeState:
    """运行时错误追踪（仅内存，不持久化）"""
    error_subtitles: List[Dict[str, Any]] = field(default_factory=list)
    total_subs: int = 0


class ResumeManager:
    """断点续传管理器。

    通过检查输出视频段文件 (TTS_{start}_{end}.mp4) 是否存在来判断已处理状态。
    enable_resume=True 时跳过已存在的输出文件，默认不跳过（全新运行）。
    """

    def __init__(self, video_output_dir: str = ""):
        self.video_output_dir = video_output_dir
        self.state = ResumeState()

    def is_processed(self, start: int, end: int) -> bool:
        """检查 TTS_{start}_{end}.mp4 是否已存在。"""
        if not self.video_output_dir:
            return False
        output_path = os.path.join(self.video_output_dir, f"TTS_{start}_{end}.mp4")
        return os.path.isfile(output_path)

    def mark_processed(self, start: int, end: int):
        """输出文件由 slow_down_video_to_file 写入，此处为 no-op。"""
        pass

    def save(self):
        """不再需要持久化状态文件。"""
        pass

    def add_error(self, start: int, end: int, text: str, error: str):
        self.state.error_subtitles.append({
            "start": start,
            "end": end,
            "text": text,
            "error": error,
        })

    def reset(self):
        self.state = ResumeState()

    def clear_outputs(self):
        """删除所有已生成的视频段文件（对应 --force）。"""
        if not self.video_output_dir or not os.path.isdir(self.video_output_dir):
            return
        for f in glob.glob(os.path.join(self.video_output_dir, "TTS_*.mp4")):
            os.remove(f)
