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
    function: str                       # 模型功能描述（如"语音识别/转写"）
    category: str                       # 分类: subtitle | translate | tts
    repo_id: str                        # HuggingFace repo (空字符串=不可下载)
    check_dir: Path                     # 模型存储目录（主目录）
    torch_hub_repo: str = ""            # torch.hub repo (如 facebookresearch/demucs)
    torch_hub_model: str = ""           # torch.hub model name
    direct_urls: tuple = ()             # 直接下载 URL（支持多个镜像，按顺序尝试）
    check_files: tuple = ()             # 关键文件列表（相对 check_dir），全部缺失则判定未安装
    fallback_dirs: tuple = ()           # 回退查找目录（如 torch.hub 缓存位置）
    size_gb: float = 0.0
    vram_gb: float = 0.0               # 推理时需要的显存 (0=云端)
    description: str = ""
    ignore_patterns: tuple = ()         # snapshot_download 忽略模式 (排除无用文件)


@dataclass
class ModelStatus:
    id: str
    name: str
    function: str = ""
    category: str = ""
    exists: bool = False
    partial: bool = False               # 目录在但关键文件缺失（可重新下载修复）
    path: str = ""
    size_gb: float = 0.0
    size_mb: float = 0.0
    vram_gb: float = 0.0
    downloadable: bool = False


class ModelManager:
    """统一模型管理。

    每个模型存储到 models/<名称>/ 独立目录（如 models/ChatTTS/），
    与现有结构（models/whisper/、models/wav2vec2/、models/Demucs/ 等）一致。
    """

    CHATTS_DIR = MODELS_DIR / "ChatTTS"
    COSYVOICE2_DIR = MODELS_DIR / "CosyVoice2-0.5B"
    COSYVOICE3_DIR = MODELS_DIR / "CosyVoice3-0.5B"

    # snapshot_download 默认忽略模式（排除冗余导出/缓存/文档）
    DEFAULT_IGNORE_PATTERNS: tuple = (
        "*.cache.pt",           # 重复的缓存权重
        "*.batch.onnx",         # batch tokenizer 变体
        "*.fp16.zip",           # 压缩 ONNX 导出
        "*.fp32.zip",
        "*.fp32.onnx",          # ONNX 导出（推理不需要）
        "*.int8.onnx",
        "*.md",                 # 文档
        "*.png",                # 图片
        "*.jpg",
        "._____temp",           # modelscope 临时文件
        "._____temp/*",
        ".msc",                 # modelscope 元数据
        ".mv",
        "asset",                # 非必要资源
    )

    # ── 按流水线阶段分类的模型注册表 ──────────────────────────
    # category: subtitle | translate | tts
    # vram_gb:  推理时峰值显存 (0=云端/无需本地GPU)
    # repo_id:  空字符串 = 不支持 ModelManager 下载 (自动缓存或手动安装)

    KNOWN_MODELS: Dict[str, ModelEntry] = {
        # ── 字幕提取 ────────────────────────────────────────
        "whisper-turbo": ModelEntry(
            id="whisper-turbo",
            name="faster-whisper large-v3-turbo",
            function="语音识别/转写 — 多语言字幕提取",
            category="subtitle",
            repo_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            check_dir=MODELS_DIR / "whisper" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
            check_files=("model.bin", "snapshots"),
            size_gb=1.6,
            vram_gb=2.5,
            description="Whisper large-v3 turbo 模型，CTranslate2 加速，推荐用于语音转字幕",
        ),
        "whisper-medium": ModelEntry(
            id="whisper-medium",
            name="faster-whisper medium",
            function="语音识别/转写 — 轻量多语言字幕提取",
            category="subtitle",
            repo_id="Systran/faster-whisper-medium",
            check_dir=MODELS_DIR / "whisper" / "models--Systran--faster-whisper-medium",
            check_files=("model.bin", "snapshots"),
            size_gb=1.5,
            vram_gb=1.5,
            description="Whisper medium 模型，速度更快但精度略低于 turbo",
        ),
        "demucs": ModelEntry(
            id="demucs",
            name="Demucs htdemucs",
            function="人声/伴奏分离 — Demucs 4源分离 (人声/鼓/贝斯/其他)",
            category="subtitle",
            repo_id="",
            torch_hub_repo="facebookresearch/demucs",
            torch_hub_model="htdemucs",
            direct_urls=(
                "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th",
                "https://gh.con.sh/https://github.com/facebookresearch/demucs/releases/download/v4.0/955717e8-8726e21a.th",
            ),
            check_dir=MODELS_DIR / "Demucs" / "hub" / "checkpoints",
            check_files=("*.th",),
            fallback_dirs=(MODELS_DIR / "hub" / "checkpoints",),  # 旧版缓存兼容
            size_gb=0.08,
            vram_gb=0.5,
            description="Hybrid Transformer Demucs，torch.hub 自动下载到 models/Demucs/",
        ),
        "silero-vad": ModelEntry(
            id="silero-vad",
            name="Silero VAD",
            function="语音活动检测 — 自动切分语音片段",
            category="subtitle",
            repo_id="",
            check_dir=MODELS_DIR / "vad",
            check_files=("silero_vad.jit", "silero_vad.onnx"),
            size_gb=0.001,
            vram_gb=0.1,
            description="Silero VAD 模型，内置 ONNX/JIT，无需额外下载",
        ),
        "wav2vec2": ModelEntry(
            id="wav2vec2",
            name="wav2vec2 时间轴对齐",
            function="时间轴对齐 — 字级别精准对齐 (日语/英语/中文等)",
            category="subtitle",
            repo_id="",                    # 各语言模型由 transformers 按需下载到 hf_cache
            check_dir=MODELS_DIR / "wav2vec2",
            check_files=("ja/model.safetensors", "en_bak/model.safetensors"),
            size_gb=2.4,
            vram_gb=1.5,
            description="wav2vec2 多语言对齐模型，存储于 wav2vec2/ 子目录中，按需下载",
        ),

        # ── 翻译 ────────────────────────────────────────────
        "minilm-semantic": ModelEntry(
            id="minilm-semantic",
            name="MiniLM 语义校验",
            function="语义相似度校验 — 跨语言翻译质量验证",
            category="translate",
            repo_id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            check_dir=MODELS_DIR / "sentence-transformers" / "paraphrase-multilingual-MiniLM-L12-v2",
            check_files=("model.safetensors", "pytorch_model.bin"),
            size_gb=0.46,
            vram_gb=0.5,
            description="多语言 MiniLM 模型，用于检查翻译是否保留了原文语义",
        ),
        "qwen2-ppl": ModelEntry(
            id="qwen2-ppl",
            name="Qwen2-0.5B 流畅度",
            function="文本流畅度评估 — 翻译腔检测 / 困惑度打分",
            category="translate",
            repo_id="Qwen/Qwen2-0.5B",
            check_dir=MODELS_DIR / "Qwen" / "Qwen2-0.5B",
            check_files=("model.safetensors", "pytorch_model.bin"),
            size_gb=0.95,
            vram_gb=2.0,
            description="Qwen2-0.5B 小语言模型，计算句子困惑度以检测机器翻译痕迹",
        ),
        "punctuate-all": ModelEntry(
            id="punctuate-all",
            name="punctuate-all 标点恢复",
            function="英文标点恢复 — 为无标点文本自动添加标点",
            category="translate",
            repo_id="kredor/punctuate-all",
            check_dir=MODELS_DIR / "punctuate-all",
            check_files=("pytorch_model.bin", "model.safetensors"),
            size_gb=1.1,
            vram_gb=1.0,
            description="英文标点恢复模型，NLP 流水线 token 分类",
        ),

        # ── TTS + 声音克隆 ─────────────────────────────────
        "chattts": ModelEntry(
            id="chattts",
            name="ChatTTS",
            function="离线中文 TTS — 对话式语音合成",
            category="tts",
            repo_id="2noise/ChatTTS",
            check_dir=MODELS_DIR / "ChatTTS",
            check_files=("config", "asset"),
            size_gb=2.37,
            vram_gb=3.0,
            description="离线中文 TTS 语音合成模型，支持音色种子控制",
        ),
        "cosyvoice": ModelEntry(
            id="cosyvoice",
            name="CosyVoice 2.0",
            function="离线 zero-shot TTS + 声音克隆 — v2 模型",
            category="tts",
            repo_id="FunAudioLLM/CosyVoice2-0.5B",
            check_dir=MODELS_DIR / "CosyVoice2-0.5B",
            check_files=("cosyvoice2.yaml",),
            size_gb=2.5,
            vram_gb=5.0,
            description="CosyVoice 2.0 离线 zero-shot TTS 语音合成 + 音色克隆 (v2 权重)",
        ),
        "cosyvoice3": ModelEntry(
            id="cosyvoice3",
            name="CosyVoice 3.0",
            function="离线 zero-shot TTS — v3 中文 CER 0.81%",
            category="tts",
            repo_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            check_dir=MODELS_DIR / "CosyVoice3-0.5B",
            check_files=("cosyvoice3.yaml",),
            size_gb=3.0,
            vram_gb=6.0,
            description="CosyVoice 3.0 离线 zero-shot TTS (v3 权重, 中文 CER 0.81%)",
        ),
        "openvoice-v2": ModelEntry(
            id="openvoice-v2",
            name="OpenVoice v2",
            function="声音克隆 — 音色转换",
            category="tts",
            repo_id="",
            check_dir=MODELS_DIR / "openvoice_v2",
            check_files=("converter",),
            size_gb=0.13,
            vram_gb=2.0,
            description="OpenVoice v2 音色转换模型，converter checkpoint",
        ),
        "edgetts": ModelEntry(
            id="edgetts",
            name="EdgeTTS",
            function="云端 TTS — 微软免费语音合成 API",
            category="tts",
            repo_id="",
            check_dir=MODELS_DIR / "_cloud_",
            size_gb=0,
            vram_gb=0,
            description="微软 Edge TTS 云端服务，无需本地显存，需联网使用",
        ),
    }

    @classmethod
    def ensure_hf_env(cls) -> None:
        """设置 HF 环境变量：镜像站点 + 缓存目录。

        中国大陆用户通过 hf-mirror.com 访问 HuggingFace。
        """
        HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR))
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    @classmethod
    def check(cls, model_id: str) -> ModelStatus:
        """检查单个模型是否已下载。

        判定逻辑：
        1. 目录不存在 → 未安装
        2. 目录存在 + 关键文件存在 → 已安装
        3. 目录存在 + 关键文件缺失 → partial（可重新下载修复）
        """
        entry = cls.KNOWN_MODELS.get(model_id)
        if entry is None:
            return ModelStatus(
                id=model_id, name=model_id, exists=False, path="", size_gb=0, size_mb=0,
            )
        check_dir = entry.check_dir
        # 云端模型特殊处理
        if str(check_dir) == str(MODELS_DIR / "_cloud_"):
            return ModelStatus(
                id=entry.id, name=entry.name, function=entry.function,
                category=entry.category, exists=True, path="☁ 云端",
                size_gb=0, size_mb=0, vram_gb=0, downloadable=False,
            )
        downloadable = bool(entry.repo_id or entry.torch_hub_repo or entry.direct_urls)
        if not check_dir.is_dir():
            return ModelStatus(
                id=entry.id, name=entry.name, function=entry.function,
                category=entry.category, exists=False, partial=False,
                path=str(check_dir), size_gb=entry.size_gb, size_mb=0,
                vram_gb=entry.vram_gb, downloadable=downloadable,
            )
        # 目录存在：检查关键文件 (支持 glob 模式如 *.th)
        def _find_files(search_dir: Path) -> bool:
            """在指定目录中查找关键文件（精确匹配 + glob）。"""
            if not entry.check_files:
                return search_dir.is_dir()
            for pat in entry.check_files:
                if "*" in pat or "?" in pat:
                    if list(search_dir.glob(pat)):
                        return True
                elif (search_dir / pat).exists():
                    return True
            return False

        in_primary = _find_files(check_dir)
        has_files = in_primary
        actual_path = str(check_dir)
        is_partial = False

        # 主目录未找到 → 回退查找
        if not has_files and entry.fallback_dirs:
            for fb_dir in entry.fallback_dirs:
                if _find_files(fb_dir):
                    has_files = True
                    actual_path = str(fb_dir)
                    is_partial = True  # 文件在回退目录，主目录为空
                    break
        elif not in_primary and entry.check_files:
            is_partial = True

        size_mb = round(
            cls._dir_size_mb(Path(actual_path)) if has_files else 0, 1
        )
        return ModelStatus(
            id=entry.id,
            name=entry.name,
            function=entry.function,
            category=entry.category,
            exists=has_files,
            partial=is_partial,
            path=actual_path,
            size_gb=entry.size_gb,
            size_mb=size_mb,
            vram_gb=entry.vram_gb,
            downloadable=downloadable,
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

    class CancelledError(Exception):
        """下载被取消。"""

    @classmethod
    def download_model(
        cls,
        model_id: str,
        progress_callback: Optional[Callable[[int, float, float], None]] = None,
        cancel_event: Optional["threading.Event"] = None,
    ) -> str:
        """下载指定模型到 models/ 目录，实时上报进度。

        cancel_event 用于外部取消下载（线程安全）。
        """
        from huggingface_hub import snapshot_download

        entry = cls.KNOWN_MODELS.get(model_id)
        if entry is None:
            raise ValueError(f"未知模型: {model_id}")
        if not entry.repo_id and not entry.torch_hub_repo:
            raise ValueError(f"模型 {model_id} 不支持下载，请手动安装")

        total_gb = entry.size_gb
        total_bytes = int(total_gb * 1024 ** 3)
        check_dir = entry.check_dir
        check_dir.mkdir(parents=True, exist_ok=True)

        result_path: list = [None]
        error: list = [None]

        def _dl() -> None:
            try:
                if entry.repo_id:
                    from huggingface_hub import snapshot_download
                    ignore_patterns = list(cls.DEFAULT_IGNORE_PATTERNS) + list(entry.ignore_patterns)
                    result_path[0] = snapshot_download(
                        repo_id=entry.repo_id,
                        local_dir=str(check_dir),
                        resume_download=True,
                        max_workers=4,
                        ignore_patterns=ignore_patterns if ignore_patterns else None,
                    )
                elif entry.direct_urls:
                    cls._download_via_url(entry.direct_urls, check_dir)
                    result_path[0] = str(check_dir)
                elif entry.torch_hub_repo:
                    os.environ.setdefault("TORCH_HOME", str(check_dir.parent.parent))
                    torch = __import__("torch")
                    model = torch.hub.load(
                        entry.torch_hub_repo, entry.torch_hub_model,
                        trust_repo=True, force_reload=False,
                    )
                    del model
                    result_path[0] = str(check_dir)
            except Exception as e:
                error[0] = e

        import threading, time

        t = threading.Thread(target=_dl, daemon=True)
        t.start()

        prev_pct = -1
        while t.is_alive():
            if cancel_event and cancel_event.is_set():
                if progress_callback:
                    progress_callback(-2, 0, total_gb)
                raise cls.CancelledError(f"下载已取消: {entry.name}")
            time.sleep(0.8)
            downloaded_bytes = cls._dir_size_bytes(check_dir)
            pct = min(99, int(downloaded_bytes / total_bytes * 100) if total_bytes > 0 else 0)
            downloaded_gb = downloaded_bytes / (1024 ** 3)
            if progress_callback and pct > prev_pct:
                progress_callback(pct, round(downloaded_gb, 2), total_gb)
                prev_pct = pct

        t.join()

        if error[0] is not None:
            if progress_callback:
                progress_callback(-1, 0, total_gb)
            raise RuntimeError(f"下载 {entry.name} 失败: {error[0]}") from error[0]

        if progress_callback:
            progress_callback(100, total_gb, total_gb)
        return result_path[0] or str(check_dir)

    @staticmethod
    def _download_via_url(urls: tuple, dest_dir: Path) -> None:
        """通过直链下载文件（支持多镜像，逐个尝试）。"""
        import urllib.request
        last_err = None
        for url in urls:
            try:
                fname = url.rstrip("/").rsplit("/", 1)[-1] or "checkpoint.th"
                dest = dest_dir / fname
                urllib.request.urlretrieve(url, str(dest))
                return
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"所有镜像下载失败: {last_err}")

    @staticmethod
    def _dir_size_bytes(path: Path) -> int:
        """计算目录磁盘占用（字节）。"""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except OSError:
            pass
        return total

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
