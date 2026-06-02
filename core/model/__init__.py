"""core/model — TRM (Translate-video Model Runtime System)

中心化模型仓库 + 项目级模型绑定层。

组件层次:
  registry.py   — ModelRegistry: 模型元数据注册表 (manifest.json + installed.json)
  downloader.py — MirrorDownloader: 纯 HTTP 镜像下载, 零 HF API
  store.py      — ModelStore: 运行时路径解析 + local_files_only 强制
  binding.py    — ProjectModelBinding: 项目→模型逻辑绑定
"""
from core.model.registry import ModelRegistry, ModelEntry, get_model_path, require_model

__all__ = [
    "ModelRegistry", "ModelEntry",
    "get_model_path", "require_model",
]
