"""
WorkspaceResolver — 统一工作目录路径解析 + 生命周期状态机 (CLI Runtime 计划书 §7)

所有文件输出收束到 {video_dir}/{stem}_project/ 下。
v2: 增加 Draft/Processing/Reviewable/Frozen 生命周期状态管理。
"""
from __future__ import annotations
import json as _json
import os
import datetime as _dt


class WorkspaceResolver:
    """给定 video_path，解析所有标准工作子目录 + 管理生命周期状态。"""

    VALID_TRANSITIONS = {
        "draft": ["processing"],
        "processing": ["reviewable"],
        "reviewable": ["frozen", "processing"],  # 可回退重处理
        "frozen": ["reviewable"],                 # 解冻
    }

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

    # ── 生命周期状态管理 ─────────────────────────────────────

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.workspace_root, "project.json")

    def read_state(self) -> str:
        """读取当前生命周期状态。"""
        if not os.path.isfile(self.manifest_path):
            return "draft"
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return _json.load(f).get("state", "draft")

    def transition(self, new_state: str) -> bool:
        """尝试转换状态。合法则写入 project.json 并返回 True。"""
        current = self.read_state()
        allowed = self.VALID_TRANSITIONS.get(current, [])
        if new_state not in allowed:
            return False
        if os.path.isfile(self.manifest_path):
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            data["state"] = new_state
            data["updated_at"] = _dt.datetime.now().isoformat()
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                _json.dump(data, f, indent=2, ensure_ascii=False)
        return True

    def freeze(self) -> bool:
        """冻结 workspace — 标记为 frozen，记录时间戳。"""
        if not os.path.isfile(self.manifest_path):
            return False
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if data.get("state") not in ("reviewable",):
            return False
        data["state"] = "frozen"
        data["timeline_frozen_at"] = _dt.datetime.now().isoformat()
        data["updated_at"] = _dt.datetime.now().isoformat()
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2, ensure_ascii=False)
        return True

    def is_exportable(self) -> bool:
        """检查当前状态是否允许导出。"""
        return self.read_state() in ("reviewable", "frozen")
