"""
Model Manager — 统一模型管理

确保所有模型（whisper、wav2vec2、ChatTTS、sentence-transformers 等）
统一存储在 Translate_video/models/ 下，不使用 ~/.cache/huggingface/ 默认缓存。

用法:
    from pipeline.model_manager import ModelManager

    ModelManager.ensure_hf_env()

    status = ModelManager.check("chattts")
    if not status.exists:
        ModelManager.download_chattts(progress_cb=lambda p, d, t: print(f"{p}%"))
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# models/ 目录（相对于项目根）
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
HF_CACHE_DIR = MODELS_DIR / "hf_cache"


@dataclass
class ModelEntry:
    id: str
    name: str
    repo_id: str                        # HuggingFace repo
    check_dir: Path                     # 检查这个目录是否存在来判断模型是否已下载
    size_gb: float = 0.0
    description: str = ""


@dataclass
class ModelStatus:
    id: str
    name: str
    exists: bool
    path: str
    size_gb: float
    size_mb: float = 0.0                # 实际占用磁盘大小（存在时填充）


class ModelManager:
    """统一模型管理。

    每个模型存储到 models/<名称>/ 独立目录（如 models/ChatTTS/），
    与现有结构（models/whisper/、models/wav2vec2/、models/Demucs/ 等）一致。
    """

    CHATTS_DIR = MODELS_DIR / "ChatTTS"

    KNOWN_MODELS: Dict[str, ModelEntry] = {
        "chattts": ModelEntry(
            id="chattts",
            name="ChatTTS (2noise/ChatTTS)",
            repo_id="2noise/ChatTTS",
            check_dir=MODELS_DIR / "ChatTTS",
            size_gb=2.37,
            description="离线中文 TTS 语音合成模型",
        ),
        "cosyvoice": ModelEntry(
            id="cosyvoice",
            name="CosyVoice 2.0 (FunAudioLLM/CosyVoice)",
            repo_id="",
            check_dir=MODELS_DIR / "CosyVoice2-0.5B",
            size_gb=2.5,
            description="离线 zero-shot TTS 语音合成 + 声音克隆模型",
        ),
    }

    @classmethod
    def ensure_hf_env(cls) -> None:
        """设置 HF_HOME 指向 models/hf_cache/（用于其他 HF 模型如 wav2vec2）。

        ChatTTS 使用独立目录 models/ChatTTS/，不受此影响。
        """
        HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR))

    @classmethod
    def check(cls, model_id: str) -> ModelStatus:
        """检查单个模型是否已下载。"""
        entry = cls.KNOWN_MODELS.get(model_id)
        if entry is None:
            return ModelStatus(
                id=model_id, name=model_id, exists=False, path="", size_gb=0, size_mb=0,
            )
        exists = entry.check_dir.is_dir()
        size_mb = 0.0
        if exists:
            size_mb = round(cls._dir_size_mb(entry.check_dir), 1)
        return ModelStatus(
            id=entry.id,
            name=entry.name,
            exists=exists,
            path=str(entry.check_dir),
            size_gb=entry.size_gb,
            size_mb=size_mb,
        )

    @classmethod
    def list_all(cls) -> List[ModelStatus]:
        """列出所有已知模型的状态。"""
        return [cls.check(mid) for mid in cls.KNOWN_MODELS]

    @classmethod
    def download_chattts(
        cls,
        progress_callback: Optional[Callable[[int, float, float], None]] = None,
    ) -> str:
        """下载 ChatTTS 模型到 models/ChatTTS/。

        使用 local_dir 直接下载到目标文件夹（非 HF cache 格式），
        方便管理和手动迁移。
        """
        from huggingface_hub import snapshot_download

        entry = cls.KNOWN_MODELS["chattts"]
        total_gb = entry.size_gb

        try:
            path = snapshot_download(
                repo_id=entry.repo_id,
                local_dir=str(cls.CHATTS_DIR),
                resume_download=True,
                max_workers=4,
            )
            if progress_callback:
                progress_callback(100, total_gb, total_gb)
            return path
        except Exception as e:
            if progress_callback:
                progress_callback(-1, 0, total_gb)
            raise RuntimeError(f"下载 ChatTTS 模型失败: {e}") from e

    @staticmethod
    def _dir_size_mb(path: Path) -> float:
        """计算目录磁盘占用（MB）。"""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except OSError:
            pass
        return total / (1024 * 1024)


# 模块导入时设置 HF_HOME（其他 HF 模型如 wav2vec2 使用）
ModelManager.ensure_hf_env()
