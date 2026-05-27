"""
Model Registry — 中心化模型注册表 (TRM Phase 1)

独立于下载/缓存的纯数据层。manifest.json 是唯一真相来源，
installed.json 记录当前本地已安装状态。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_DIR = PROJECT_ROOT / "models" / "registry"
RUNTIME_DIR = PROJECT_ROOT / "models" / "runtime"


@dataclass
class ModelEntry:
    """单个模型的元数据定义。

    runtime_path 是相对于 models/runtime/ 的路径，例如 "whisper-turbo"。
    实际运行时路径 = RUNTIME_DIR / runtime_path。
    """
    id: str
    name: str
    version: str
    type: str                          # asr | alignment | vad | speaker | tts | voice_clone | semantic | ppl | emotion | punctuation | separation | cloud
    engine: str                        # faster-whisper | wav2vec2 | silero | pyannote | chattts | cosyvoice | indextts | openvoice | edgetts | demucs | minilm | qwen2 | punctuate | emotion2vec
    runtime_path: str                  # "whisper-turbo", "chattts", etc.
    check_files: tuple[str, ...] = ()
    size_gb: float = 0.0
    vram_gb: float = 0.0
    description: str = ""
    mirrors: list[str] = field(default_factory=list)
    download_format: str = ""          # tar.zst | zip | raw | torch_hub | cloud
    repo_id: str = ""                  # 原始 HF repo_id（仅用于镜像下载 URL 拼接，不用 HF API）
    torch_hub_repo: str = ""
    torch_hub_model: str = ""
    fallback_paths: list[str] = field(default_factory=list)

    @property
    def full_runtime_path(self) -> Path:
        return RUNTIME_DIR / self.runtime_path

    @property
    def category(self) -> str:
        type_category = {
            "asr": "subtitle", "alignment": "subtitle", "vad": "subtitle",
            "speaker": "subtitle", "separation": "subtitle", "emotion": "subtitle",
            "semantic": "translate", "ppl": "translate", "punctuation": "translate",
            "tts": "tts", "voice_clone": "tts",
            "cloud": "tts",
        }
        return type_category.get(self.type, "subtitle")


class ModelRegistry:
    """中心化模型注册表 — 从 manifest.json 加载，安装状态存 installed.json。"""

    _manifest: dict[str, ModelEntry] = {}
    _installed: dict[str, dict] = {}
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._loaded:
            return
        cls._load_manifest()
        cls._load_installed()
        cls._loaded = True

    @classmethod
    def _load_manifest(cls) -> None:
        import json
        manifest_path = REGISTRY_DIR / "manifest.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for raw in data.get("models", []):
                entry = ModelEntry(
                    id=raw["id"],
                    name=raw["name"],
                    version=raw.get("version", "1.0.0"),
                    type=raw["type"],
                    engine=raw["engine"],
                    runtime_path=raw["runtime_path"],
                    check_files=tuple(raw.get("check_files", [])),
                    size_gb=raw.get("size_gb", 0.0),
                    vram_gb=raw.get("vram_gb", 0.0),
                    description=raw.get("description", ""),
                    mirrors=raw.get("download", {}).get("mirrors", []),
                    download_format=raw.get("download", {}).get("format", ""),
                    repo_id=raw.get("repo_id", ""),
                    torch_hub_repo=raw.get("download", {}).get("torch_hub_repo", ""),
                    torch_hub_model=raw.get("download", {}).get("torch_hub_model", ""),
                    fallback_paths=raw.get("fallback_paths", []),
                )
                cls._manifest[entry.id] = entry
        else:
            cls._manifest = {}

    @classmethod
    def _load_installed(cls) -> None:
        import json
        installed_path = REGISTRY_DIR / "installed.json"
        if installed_path.is_file():
            cls._installed = json.loads(installed_path.read_text(encoding="utf-8"))
        else:
            cls._installed = {}

    @classmethod
    def reload(cls) -> None:
        cls._loaded = False
        cls._manifest.clear()
        cls._installed.clear()
        cls._ensure_loaded()

    @classmethod
    def get(cls, model_id: str) -> Optional[ModelEntry]:
        cls._ensure_loaded()
        return cls._manifest.get(model_id)

    @classmethod
    def list_all(cls) -> list[ModelEntry]:
        cls._ensure_loaded()
        return list(cls._manifest.values())

    @classmethod
    def list_by_type(cls, type: str) -> list[ModelEntry]:
        cls._ensure_loaded()
        return [e for e in cls._manifest.values() if e.type == type]

    @classmethod
    def list_by_category(cls, category: str) -> list[ModelEntry]:
        cls._ensure_loaded()
        return [e for e in cls._manifest.values() if e.category == category]

    @classmethod
    def resolve_path(cls, model_id: str) -> Optional[Path]:
        """返回模型运行时路径。优先 installed.json 中的实际路径，fallback 到 manifest runtime_path。"""
        cls._ensure_loaded()
        installed = cls._installed.get(model_id)
        if installed and installed.get("path"):
            return Path(installed["path"])
        entry = cls._manifest.get(model_id)
        if entry:
            return entry.full_runtime_path
        return None

    @classmethod
    def is_installed(cls, model_id: str) -> bool:
        cls._ensure_loaded()
        entry = cls._manifest.get(model_id)
        if entry is None:
            return False
        installed = cls._installed.get(model_id)
        if installed and installed.get("status") == "installed":
            actual_path = Path(installed.get("path", entry.full_runtime_path))
            return cls._verify_files(actual_path, entry.check_files)
        return False

    @classmethod
    def mark_installed(cls, model_id: str, version: str, path: str | None = None) -> None:
        import json
        cls._ensure_loaded()
        entry = cls._manifest.get(model_id)
        actual_path = path or (str(entry.full_runtime_path) if entry else "")
        cls._installed[model_id] = {
            "status": "installed",
            "version": version,
            "path": actual_path,
            "installed_at": "",
        }
        installed_path = REGISTRY_DIR / "installed.json"
        installed_path.write_text(json.dumps(cls._installed, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def scan_existing(cls) -> dict[str, list[str]]:
        """扫描 models/runtime/ 下实际存在的模型，返回 {id: [missing_files], ...}。

        用于生成初始 installed.json 或诊断。
        """
        cls._ensure_loaded()
        result: dict[str, list[str]] = {}
        for model_id, entry in cls._manifest.items():
            path = entry.full_runtime_path
            missing = cls._missing_files(path, entry.check_files)
            result[model_id] = missing
            if not missing:
                cls._installed[model_id] = {
                    "status": "installed",
                    "version": entry.version,
                    "path": str(path),
                }
        return result

    @classmethod
    def _verify_files(cls, path: Path, check_files: tuple[str, ...]) -> bool:
        if not path.exists():
            return False
        return len(cls._missing_files(path, check_files)) == 0

    @staticmethod
    def _missing_files(path: Path, check_files: tuple[str, ...]) -> list[str]:
        missing = []
        for pattern in check_files:
            if "*" in pattern:
                matches = list(path.glob(pattern))
                if not matches:
                    missing.append(pattern)
            else:
                if not (path / pattern).exists():
                    if not Path(pattern).exists():
                        missing.append(pattern)
        return missing


# 常用便捷访问
def get_model_path(model_id: str) -> Optional[Path]:
    return ModelRegistry.resolve_path(model_id)


def require_model(model_id: str) -> Path:
    path = ModelRegistry.resolve_path(model_id)
    if path is None:
        raise RuntimeError(f"未知模型: {model_id}")
    if not ModelRegistry.is_installed(model_id):
        raise RuntimeError(
            f"模型未安装: {model_id}\n"
            f"请运行: python -m core.model download {model_id}"
        )
    return path
