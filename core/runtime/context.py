"""
RuntimeContext — 一次 Pipeline 执行的不可变上下文 (设计文档 §3.4)

统一 CLI 和 WebUI 的参数模型。所有运行时依赖通过 context 注入。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RuntimeContext:
    """一次 Pipeline 执行的完整上下文。"""
    video_path: str
    target_lang: str = "zh"
    engine: str = "chattts"
    model: str = "turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    stages: list[str] = field(default_factory=list)
    dry_run: bool = False
    force: bool = False
    skip_demucs: bool = False
    skip_align: bool = False
    skip_defect_check: bool = False
    enable_speaker_diarization: bool = True
    output_dir: str = ""
    workspace_dir: str = ""

    def __post_init__(self):
        if not self.workspace_dir:
            stem = Path(self.video_path).stem
            parent = Path(self.video_path).parent
            self.workspace_dir = str(parent / f"{stem}_project")
        if not self.output_dir:
            self.output_dir = self.workspace_dir
