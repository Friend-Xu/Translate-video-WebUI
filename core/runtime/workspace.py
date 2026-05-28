"""
WorkspaceResolver — 统一工作目录路径解析

所有文件输出收束到 {video_dir}/{stem}_project/ 下:
  01_extract/    提取阶段 (transcript, audio, demucs, timeline)
  02_translate/  翻译阶段 (srt, log, quality report)
  03_tts/        TTS 阶段 (音频片段)
  04_output/     最终输出 (dubbed.mp4)
  .snapshots/    运行时快照
  _embeddings/   声纹嵌入
"""
from __future__ import annotations
import os


class WorkspaceResolver:
    """给定 video_path，解析所有标准工作子目录。"""

    def __init__(self, video_path: str):
        self.video_path = video_path
        stem = os.path.splitext(os.path.basename(video_path))[0]
        self.workspace_root = os.path.join(os.path.dirname(video_path) or ".", f"{stem}_project")
        self.stem = stem

    @property
    def extract_dir(self) -> str:
        return os.path.join(self.workspace_root, "01_extract")

    @property
    def translate_dir(self) -> str:
        return os.path.join(self.workspace_root, "02_translate")

    @property
    def tts_dir(self) -> str:
        return os.path.join(self.workspace_root, "03_tts")

    @property
    def output_dir(self) -> str:
        return os.path.join(self.workspace_root, "04_output")

    @property
    def snapshots_dir(self) -> str:
        return os.path.join(self.workspace_root, ".snapshots")

    @property
    def embeddings_dir(self) -> str:
        return os.path.join(self.workspace_root, "_embeddings")

    @property
    def transcript_path(self) -> str:
        return os.path.join(self.extract_dir, "transcript.json")

    @property
    def vad_segments_path(self) -> str:
        return os.path.join(self.extract_dir, "vad_segments.json")

    @property
    def timeline_path(self) -> str:
        return os.path.join(self.extract_dir, "timeline.json")

    @property
    def extracted_audio_path(self) -> str:
        return os.path.join(self.extract_dir, f"{self.stem}_extracted.wav")

    @property
    def machine_srt_path(self) -> str:
        return os.path.join(self.translate_dir, "machine.srt")

    def tts_segment_path(self, segment_id: str, engine: str) -> str:
        return os.path.join(self.tts_dir, f"{segment_id}_{engine}.wav")

    def ensure_dirs(self) -> None:
        for d in [self.extract_dir, self.translate_dir, self.tts_dir,
                   self.output_dir, self.snapshots_dir, self.embeddings_dir]:
            os.makedirs(d, exist_ok=True)
