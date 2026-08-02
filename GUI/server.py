"""
FastAPI backend for Translate_video GUI.

Endpoints:
  POST /api/pipeline/run          - Start pipeline
  GET  /api/pipeline/{id}/logs    - SSE log stream
  GET  /api/pipeline/{id}/status  - Job status
  POST /api/pipeline/{id}/cancel  - Kill running job
  GET  /api/jobs                  - List all jobs (persisted)
  POST /api/batch/run             - Start batch processing
  GET  /api/batch/{id}            - Get batch status
  POST /api/batch/{id}/cancel     - Cancel entire batch
  POST /api/batch/{id}/skip       - Skip current video in batch
  GET  /api/batch/active          - Get active batch
  GET  /api/batch/list            - List all batches
  GET  /api/settings              - Read user settings
  POST /api/settings              - Write user settings
  POST /api/settings/reset        - Reset language to defaults
  GET  /api/subtitle/presets      - Get current subtitle presets
  GET  /api/files/browse          - List directory contents
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import yaml

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import pysrt

# Windows asyncio subprocess 兼容修复
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

# ── 系统级日志 ──────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

from core.compat import compat_setup_logging
compat_setup_logging(log_dir=LOG_DIR)
import logging
logger = logging.getLogger("server")

# Workflow Presets — Pipeline as Timeline Runtime bootstrap templates
from GUI.workflow_presets import get_presets, get_preset, RuntimeState


class SSELogHandler(logging.Handler):
    """将 Python logging 记录路由到 Job 的 SSE 日志流。

    每个 Job 运行期间创建并挂到 root logger，结束后移除。
    日志格式 ``[LEVEL] module: message`` 与前端 useSSE.ts 解析器兼容。
    """

    def __init__(self, append_log_fn):
        super().__init__()
        self._append = append_log_fn
        self.setLevel(logging.DEBUG)
        self.setFormatter(logging.Formatter(
            "[%(levelname)-5s] %(name)s: %(message)s"
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._append(msg)
        except Exception:
            self.handleError(record)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
TVW_SCRIPT = PROJECT_ROOT / "tvw.py"
DIST_DIR = Path(__file__).resolve().parent / "dist"
JOBS_DIR = Path(__file__).resolve().parent / "jobs"
BATCHES_DIR = Path(__file__).resolve().parent / "batches"
SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
FONT_DIR = PROJECT_ROOT / "models" / "font"

app = FastAPI(title="Translate Video GUI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _reapply_logging():
    """uvicorn 启动时会重置日志配置，重新应用系统级日志。"""
    compat_setup_logging(log_dir=LOG_DIR)
    logger.info("系统日志已就绪")


# 不需要记录日志的高频轮询/流式路径（前缀匹配）
_SKIP_LOG_PREFIXES = (
    "/api/system/info",
    "/api/pipeline/",  # status 轮询 + logs SSE
)




def _should_skip_log(path: str) -> bool:
    return path.startswith(_SKIP_LOG_PREFIXES)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个请求：method, path, status, duration。异常时打印完整堆栈。"""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        logger.exception(
            "%s %s -> 500 (%.0fms) [未处理异常]",
            request.method, request.url.path, elapsed,
        )
        raise
    elapsed = (time.perf_counter() - start) * 1000
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    if not _should_skip_log(request.url.path) or level >= logging.WARNING:
        logger.log(
            level, "%s %s -> %d (%.0fms)",
            request.method, request.url.path, response.status_code, elapsed,
        )
    return response


# ── 全局异常处理器 ──────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    logger.warning(
        "HTTP %d: %s %s",
        exc.status_code, request.method, request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            # detail 字段兼容前端 res.json().detail 读取 (P1 吞错修复后
            # 前端按 FastAPI 标准解析, 缺 detail 会退化为裸 "HTTP 400")
            "error": exc.detail,
            "detail": exc.detail,
            "code": f"HTTP_{exc.status_code}",
        },
    )


@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception):
    logger.critical(
        "未处理异常: %s %s — %s: %s",
        request.method, request.url.path, type(exc).__name__, exc,
    )
    return JSONResponse(
        status_code=500,
        content={"error": "内部服务器错误", "code": "INTERNAL_ERROR"},
    )


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

@dataclass
class Job:
    id: str
    process: subprocess.Popen | None = None
    status: str = "idle"        # idle | running | completed | failed | cancelled
    runtime_state: str = "uninitialized"  # Timeline Runtime state (UNINITIALIZED/BOOTSTRAPPING/READY/COMPUTING/FAILED/COMPLETE)
    progress: int = 0
    current_step: str = "就绪"
    logs: list[str] = field(default_factory=list)
    video_path: str = ""
    created_at: str = ""
    batch_id: str | None = None
    workspace_path: str = ""    # workspace directory for this job
    _queues: list[asyncio.Queue] = field(default_factory=list)
    _pending_save: int = 0
    _loop: asyncio.AbstractEventLoop | None = None
    _log_file: object | None = None    # open file handle for {workspace}/pipeline.log
    _log_lock: object | None = None    # threading.Lock for file writes
    _core_state: object | None = None  # core/ TimelineProjectState (批次11 §阶段B)
    _stage_states: dict = field(default_factory=dict)  # stage_id → StageInfo for WebUI pipeline progress

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    def open_log_file(self, workspace: str) -> None:
        """Open workspace log file for append."""
        import threading
        os.makedirs(workspace, exist_ok=True)
        self._log_file = open(os.path.join(workspace, "pipeline.log"), "a", encoding="utf-8")
        self._log_lock = threading.Lock()

    def close_log_file(self) -> None:
        """Close workspace log file."""
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        self._log_lock = None

    @property
    def log_file_path(self) -> str | None:
        """Absolute path to workspace log file, if available."""
        if self._log_file is not None:
            return self._log_file.name
        # Fallback: derive from video_path
        if self.video_path:
            stem = os.path.splitext(os.path.basename(self.video_path))[0]
            return os.path.join(os.path.dirname(self.video_path), f"{stem}_project", "pipeline.log")
        return None

    def append_log(self, line: str) -> None:
        # 跳过 tqdm 进度条行（每秒数十条，无信息价值）
        if re.match(r'^\s*\d+%\|', line):
            return
        # 过滤 ANSI 转义码和 null 字节（破坏 JSON/SSE 解析）
        line = re.sub(r'\x1b\[[0-9;]*m', '', line)
        line = line.replace('\x00', '')
        if not line.strip():
            return
        self.logs.append(line)
        # 不裁剪 — SSE idx 依赖列表索引稳定
        # 写入 workspace pipeline.log（线程安全）
        if self._log_file is not None and self._log_lock is not None:
            with self._log_lock:
                self._log_file.write(line + "\n")
                self._log_file.flush()

        # Parse step hints from stdout for progress
        lower = line.lower()
        if "[1/4]" in line or "字幕提取" in line:
            self.current_step = "字幕提取中..."
            self.progress = 5
        elif "[2/4]" in line or (self.current_step == "字幕提取中..." and "翻译" in line):
            self.current_step = "字幕翻译中..."
            self.progress = 30
        elif "[3/4]" in line or (self.current_step == "字幕翻译中..." and "tts" in lower):
            self.current_step = "TTS 合成中..."
            self.progress = 60
        elif "[4/4]" in line:
            self.current_step = "视频渲染中..."
            self.progress = 85
        if "[ok]" in lower:
            self.progress = min(self.progress + 10, 95)

        # 批量写磁盘：每 50 条日志保存一次（仅保存元信息，不保存全量日志）
        self._pending_save += 1
        if self._pending_save >= 50:
            _save_job(self)
            self._pending_save = 0

        # SSE 即时推送：通过 asyncio.Queue 通知所有订阅者
        if self._loop is not None and self._queues:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            payload = {"message": line, "ts": ts}
            for q in self._queues:
                self._loop.call_soon_threadsafe(q.put_nowait, payload)

    def _save_deferred(self) -> None:
        """Flush pending saves (call on status change or shutdown)."""
        if self._pending_save > 0:
            _save_job(self)
            self._pending_save = 0


@dataclass
class BatchSession:
    id: str
    config_json: str
    video_paths: list[str]
    video_job_ids: dict[str, str] = field(default_factory=dict)
    current_video_index: int = 0
    status: str = "running"     # running | completed | cancelled | partial | failed
    created_at: str = ""
    logs: list[str] = field(default_factory=list)

    def append_log(self, line: str) -> None:
        self.logs.append(line)
        self.logs = self.logs[-200:]
        _save_batch(self)


def _save_batch(batch: BatchSession) -> None:
    BATCHES_DIR.mkdir(exist_ok=True)
    (BATCHES_DIR / f"{batch.id}.json").write_text(
        json.dumps({
            "id": batch.id,
            "config_json": batch.config_json,
            "video_paths": batch.video_paths,
            "video_job_ids": batch.video_job_ids,
            "current_video_index": batch.current_video_index,
            "status": batch.status,
            "logs": batch.logs,
            "created_at": batch.created_at,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_batches() -> dict[str, BatchSession]:
    BATCHES_DIR.mkdir(exist_ok=True)
    batches: dict[str, BatchSession] = {}
    for p in BATCHES_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        batch = BatchSession(
            id=data.get("id", p.stem),
            config_json=data.get("config_json", "{}"),
            video_paths=data.get("video_paths", []),
            video_job_ids=data.get("video_job_ids", {}),
            current_video_index=data.get("current_video_index", 0),
            status="failed" if data.get("status") == "running" else data.get("status", "failed"),
            logs=data.get("logs", []),
            created_at=data.get("created_at", ""),
        )
        if data.get("status") == "running":
            batch.logs.append("[BATCH] 服务重启，批次中断")
            _save_batch(batch)
        batches[batch.id] = batch
    return batches


_batches: dict[str, BatchSession] = _load_batches()


def _save_job(job: Job) -> None:
    JOBS_DIR.mkdir(exist_ok=True)
    (JOBS_DIR / f"{job.id}.json").write_text(
        json.dumps({
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "logs_tail": job.logs[-10:],   # only last 10 lines for preview; full log in workspace pipeline.log
            "video_path": job.video_path,
            "created_at": job.created_at,
            "batch_id": job.batch_id,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    job._pending_save = 0


def _load_jobs() -> dict[str, Job]:
    JOBS_DIR.mkdir(exist_ok=True)
    jobs: dict[str, Job] = {}
    for p in JOBS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        job = Job(
            id=data.get("id", p.stem),
            status=data.get("status", "failed"),
            progress=data.get("progress", 0),
            current_step=data.get("current_step", ""),
            logs=data.get("logs_tail", data.get("logs", [])),
            video_path=data.get("video_path", ""),
            created_at=data.get("created_at", ""),
            batch_id=data.get("batch_id"),
        )
        if job.status == "running":
            job.status = "failed"
            job.current_step = "服务重启，任务中断"
            _save_job(job)
        jobs[job.id] = job
    return jobs


_jobs: dict[str, Job] = _load_jobs()


# ---------------------------------------------------------------------------
# Settings & Config.yaml management
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_settings(data: dict) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_glossary_list(val) -> list[str]:
    """Backward-compat: YAML 中 default_dict 可能是单个字符串或列表。"""
    if val is None:
        return ["minecraft.json"]
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [val]
    return ["minecraft.json"]


def _load_yaml_defaults() -> dict:
    """Read config/tts.yaml and config/translate.yaml, map to frontend field names."""
    tts = _load_yaml(PROJECT_ROOT / "config" / "tts.yaml").get("tts", {})
    trans = _load_yaml(PROJECT_ROOT / "config" / "translate.yaml").get("translate", {})

    return {
        "engine": tts.get("engine_type", "edge"),
        "chatttsSpeakerSeed": tts.get("chattts_speaker_seed", 2),
        "chatttsSpeakerPt": tts.get("chattts_speaker_pt") or "",
        "chatttsModelSource": tts.get("chattts_model_source", "local"),
        "chatttsModelPath": tts.get("chattts_model_path") or "",
        "voice": tts.get("voice", "zh-CN-XiaoxiaoNeural"),
        "speechRate": tts.get("base_speed", 30),
        "maxSpeed": tts.get("max_speed", 100),
        "videoSpeedMin": tts.get("video_speed_min", 0.60),
        "videoSpeedMax": tts.get("video_speed_max", 2.00),
        "enableVoiceClone": tts.get("voice_clone_engine", "openvoice") != "none",
        "voiceCloneEngine": tts.get("voice_clone_engine", "none"),
        "voiceCloneDevice": tts.get("voice_clone_device", "auto"),
        "voiceCloneConcurrency": tts.get("voice_clone_concurrency", 1),
        "cosyvoiceMode": tts.get("cosyvoice_mode", "local"),
        "cosyvoiceModelVersion": tts.get("cosyvoice_model_version", "v2"),
        "voiceCloneSample": tts.get("voice_clone_sample") or "",
        "enableEmotionClone": tts.get("enable_emotion", False),
        "defaultEmotion": tts.get("default_emotion", "neutral"),
        "emotionRefAudio": tts.get("emotion_ref_audio") or "",
        "concurrency": trans.get("concurrency", {}).get("max_workers", tts.get("threading_workers", 3)),
        "ttsWorkers": tts.get("threading_workers", 7),
        "chatttsWorkers": tts.get("chattts_workers", 0),  # 0 = VRAM自动
        "cosyvoiceTtsModelVersion": tts.get("cosyvoice_tts_model_version", "v2"),
        "cosyvoiceTtsModelPath": tts.get("cosyvoice_tts_model_path", ""),
        "cosyvoiceTtsPromptAudio": tts.get("cosyvoice_tts_prompt_audio", ""),
        "cosyvoiceTtsPromptText": tts.get("cosyvoice_tts_prompt_text", ""),
        "cosyvoiceTtsFp16": tts.get("cosyvoice_tts_fp16", True),
        "cosyvoiceTtsWorkers": tts.get("cosyvoice_tts_workers", 0),
        "cosyvoiceTtsSpeed": tts.get("cosyvoice_tts_speed", 1.0),
        "cosyvoiceTtsMode": tts.get("cosyvoice_tts_mode", "cross_lingual"),
        "cosyvoiceTtsLang": tts.get("cosyvoice_tts_lang", ""),
        "indexttsFp16": tts.get("indextts_fp16", True),
        "indexttsEnableClone": tts.get("indextts_enable_clone", True),
        "indexttsSpeakerAudio": tts.get("indextts_speaker_audio", ""),
        "indexttsCheckpointsDir": tts.get("indextts_checkpoints_dir", ""),
        "loudnessNormEnabled": tts.get("loudness_norm_enabled", True),
        "loudnessTargetAuto": tts.get("loudness_target_auto", True),
        "loudnessTargetLufs": tts.get("loudness_target_lufs", -16.0),
        "enableCheckpoint": tts.get("enable_resume", False),
        "captionFont": tts.get("caption_font", ""),
        "videoCodec": tts.get("video_codec", "libx264"),
        "audioCodec": tts.get("video_audio_codec", "aac"),
        "apiKey": trans.get("api_key", ""),
        "apiType": trans.get("api_type", "deepseek"),
        "enableSemanticValidation": trans.get("semantic_check", True),
        "enableNaturalnessCheck": trans.get("quality_assessment", {}).get("dimensions", {}).get("naturalness", {}).get("enabled", True),
        "naturalnessThreshold": trans.get("quality_assessment", {}).get("dimensions", {}).get("naturalness", {}).get("threshold", 3.0),
        "jointVerification": trans.get("joint_verification", False),
        "verificationMode": trans.get("verification_mode", "joint_formula"),
        "enableTermReplacement": trans.get("terms_dict", {}).get("enabled", True),
        "activeGlossary": _parse_glossary_list(trans.get("terms_dict", {}).get("default_dict", ["minecraft.json"])),
        "targetLang": trans.get("target_lang", "zh-CN"),
    }


def _snake_defaults() -> dict:
    """蛇形键默认值，匹配 SettingsView 的 config state 键名。"""
    base = _load_yaml_defaults()
    return {
        "tts_engine": base.get("engine", "chattts"),
        "speed_factor": 1.0,
        "tts_concurrency": base.get("ttsWorkers", 2),
        "loudness_norm": base.get("loudnessNormEnabled", True),
        "chattts_speaker_seed": base.get("chatttsSpeakerSeed", 2),
        "chattts_speaker_pt": base.get("chatttsSpeakerPt", ""),
        "chattts_temperature": 0.3,
        "chattts_top_k": 20,
        "chattts_top_p": 0.7,
        "chattts_workers": base.get("chatttsWorkers", 0),
        "chattts_emotion_injection": True,
        "edge_voice": base.get("voice", "zh-CN-XiaoxiaoNeural"),
        "edge_rate": "+0%",
        "edge_pitch": "+0Hz",
        "edge_volume": "+0%",
        "base_speed": 40,
        "video_speed_min": 0.60,
        "video_speed_max": 2.00,
        "loudness_target_lufs": -16.0,
        "demucs_model": "htdemucs",
        "skip_demucs": False,
        "skip_tts": False,
        "skip_extract": False,
        "skip_translate": False,
        "skip_semantic_validation": False,
        "skip_naturalness_check": False,
        "asr_model": "turbo",
        "device": "cuda",
        "compute_type": "float16",
        "source_lang": "auto",
        "max_speakers": 0,
        "clustering_threshold": 0.65,
        "api_type": base.get("apiType", "deepseek"),
        "api_key": base.get("apiKey", ""),
        "model": "deepseek-v4-flash",
        "target_lang": base.get("targetLang", "zh"),
        "translate_concurrency": base.get("concurrency", 3),
        "temperature": 0.1,
        "max_tokens": 4000,
        "top_p": 0.9,
        "api_base_url": "https://api.deepseek.com",
        "quality_gate": True,
        "verification_mode": "logic_gate",
        "gate_threshold_accept": 0.80,
        "gate_threshold_reject": 0.60,
        "gate_beta": 0.6,
        "gate_gamma": 0.4,
        "sim_drop_limit": 0.05,
        "semantic_threshold": 0.70,
        "joint_verification": False,
        "custom_prompt": "",
        "enable_glossary": True,
        "glossary_files": "minecraft.json",
        "max_retries": 2,
        "fallback_to_single": True,
        "caption_font": base.get("captionFont", ""),
        "caption_font_size": 0,  # 0 = 自动 (video_width * font_size_factor)
        "caption_font_color": "#FFFFFF",
        "caption_stroke_color": "#000000",
        "caption_stroke_width": 2,
        "caption_bg_color": "#000000",
        "caption_alignment": "center",
        "caption_position": "bottom",
        "caption_max_lines": 2,
        "caption_font_size_factor": 0.030,
        "caption_width_ratio": 0.85,
        "font_size_mode": "adaptive",
        "max_font_size": 0,
        "enable_subtitle_optimization": True,
        "bilingual_mode": "target_only",
        "output_format": "mp4",
        "video_codec": base.get("videoCodec", "libx264"),
        "output_resolution": "original",
        "video_bitrate": 8,
        "preserve_original_audio": False,
        "bgm_volume": 1.0,
        "audio_codec": "aac",
        "audio_bitrate": "192k",
    }


class RunRequest(BaseModel):
    video_path: str
    lang: str = "auto"
    target_lang: str = "zh-CN"
    model: str = "turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    engine: str = "edge"
    chattts_speaker_seed: Optional[int] = 2
    chattts_speaker_pt: str = ""
    chattts_model_source: str = "local"
    chattts_model_path: str = ""
    voice: str = "zh-CN-XiaoxiaoNeural"
    speech_rate: int = 40
    max_speed: int = 100
    video_speed_min: float = 0.60
    video_speed_max: float = 2.00
    skip_extract: bool = False
    skip_translate: bool = False
    skip_tts: bool = False
    skip_defect_check: bool = False
    skip_demucs: bool = False
    skip_semantic_validation: bool = False
    skip_naturalness_check: bool = False
    force: bool = False
    caption_font: str = ""
    caption_font_size_mode: str = "adaptive"
    caption_font_size: int = 0
    caption_font_color: str = ""
    caption_stroke_width: float = 0.0
    caption_stroke_color: str = ""
    caption_bg_color: str = ""
    caption_alignment: str = "center"
    caption_position: str = "bottom"
    caption_max_lines: int = 2
    caption_max_font_size: int = 0
    caption_font_size_factor: float = 0.030
    caption_width_ratio: float = 0.85
    caption_optimize: bool = True
    bgm_volume: float = 1.0
    voice_clone_engine: str = "none"
    voice_clone_device: str = "auto"
    voice_clone_concurrency: int = 1
    cosyvoice_mode: str = "local"
    cosyvoice_model_version: str = "v2"
    num_workers: int = 1
    tts_workers: int = 7
    chattts_workers: int = 0  # 0 = VRAM自动
    # CosyVoice TTS fields
    cosyvoice_tts_model_version: str = "v2"
    cosyvoice_tts_model_path: str = ""
    cosyvoice_tts_prompt_audio: str = ""
    cosyvoice_tts_prompt_text: str = ""
    cosyvoice_tts_fp16: bool = True
    cosyvoice_tts_workers: int = 0
    cosyvoice_tts_speed: float = 1.0
    cosyvoice_tts_mode: str = "cross_lingual"
    cosyvoice_tts_lang: str = ""
    indextts_fp16: bool = True
    indextts_enable_clone: bool = True
    indextts_speaker_audio: str = ""
    indextts_checkpoints_dir: str = ""
    loudness_norm_enabled: bool = True
    loudness_target_auto: bool = True
    loudness_target_lufs: float = -16.0
    skip_align: bool = False
    align_lang: str = "ja"
    enable_emotion: bool = False
    enable_speaker_diarization: bool = False
    use_core: bool = False  # 启用 core/ Adapter-Pass-Gate 新架构


def _update_workspace_runtime_state(workspace_path: str, state: RuntimeState) -> None:
    """Update runtime_state in workspace project.json."""
    if not workspace_path:
        return
    manifest_path = Path(workspace_path) / "project.json"
    if not manifest_path.is_file():
        return
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        m["runtime_state"] = state.value
        m["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _persist_config_patch(workspace: str, patch_entry: dict) -> None:
    """Append a config patch to the workspace patch log file."""
    if not workspace:
        return
    log_path = Path(workspace) / "01_extract" / "timeline_patches.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if log_path.is_file():
            with open(log_path, "r", encoding="utf-8") as f:
                patches = json.load(f)
        else:
            patches = []
        patches.append(patch_entry)
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(patches, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_config_overrides(workspace: str, event_id: str) -> dict[str, dict]:
    """Load per-slot config overrides for an event from the patch log.

    Returns dict[slot_name, config_dict] where config_dict contains
    the merged override fields for that slot.
    """
    if not workspace:
        return {}
    log_path = Path(workspace) / "01_extract" / "timeline_patches.json"
    if not log_path.is_file():
        return {}
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            patches = json.load(f)
    except Exception:
        return {}

    overrides: dict[str, dict] = {}
    for p in patches:
        if p.get("target_id") != event_id:
            continue
        op = p.get("op", "")
        val = p.get("value", {})
        slot = val.get("slot", "")
        if not slot:
            continue
        if op in ("override_config", "OVERRIDE_CONFIG"):
            partial = val.get("partial_config", {})
            if slot not in overrides:
                overrides[slot] = {}
            # deep merge into existing overrides for this slot
            _deep_merge_override(overrides[slot], partial)
        elif op in ("set_config", "SET_CONFIG"):
            block = val.get("config_block", {})
            if slot not in overrides:
                overrides[slot] = {}
            _deep_merge_override(overrides[slot], block)
        elif op in ("reset_config", "RESET_CONFIG"):
            fields = val.get("fields") or []
            if slot in overrides and fields:
                for f in fields:
                    overrides[slot].pop(f, None)
            elif slot in overrides and not fields:
                overrides[slot] = {}

    return overrides


def _deep_merge_override(base: dict, override: dict) -> None:
    """In-place deep merge of override into base."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge_override(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Helper functions for pipeline launch
# ---------------------------------------------------------------------------

def _write_caption_config(req: RunRequest) -> str:
    caption_config_path = PROJECT_ROOT / "config" / "caption.yaml"
    caption_config_path.parent.mkdir(exist_ok=True)
    caption_data = {
        "caption": {
            "font": req.caption_font,
            "font_size_mode": req.caption_font_size_mode,
            "font_size": req.caption_font_size,
            "font_color": req.caption_font_color or "white",
            "stroke_width": req.caption_stroke_width,
            "stroke_color": req.caption_stroke_color or "black",
            "bg_color": req.caption_bg_color or "rgba(0,0,0,128)",
            "alignment": req.caption_alignment,
            "position": req.caption_position,
            "max_lines": req.caption_max_lines,
            "max_font_size": req.caption_max_font_size,
            "font_size_factor": req.caption_font_size_factor,
            "width_ratio": req.caption_width_ratio,
            "enable_subtitle_optimization": req.caption_optimize,
        }
    }
    with open(caption_config_path, "w", encoding="utf-8") as f:
        yaml.dump(caption_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return str(caption_config_path)


def _write_tts_runtime_config(req: RunRequest) -> str:
    """Write runtime TTS YAML with frontend-adjustable fields only.

    Only writes fields the user can adjust from the WebUI (engine, voice, speed).
    TTSConfig.from_yaml() fills missing fields with dataclass defaults, which match
    the same defaults used when running without --config.
    """
    config_path = PROJECT_ROOT / "config" / "runtime_tts.yaml"
    config_path.parent.mkdir(exist_ok=True)
    data = {
        "tts": {
            "engine_type": req.engine,
            "chattts_speaker_seed": req.chattts_speaker_seed,
            "chattts_speaker_pt": req.chattts_speaker_pt or None,
            "chattts_model_source": req.chattts_model_source,
            "chattts_model_path": req.chattts_model_path or None,
            "chattts_workers": req.chattts_workers,
            "voice": req.voice,
            "target_lang": req.target_lang,
            "base_speed": req.speech_rate,
            "max_speed": req.max_speed,
            "video_speed_min": req.video_speed_min,
            "video_speed_max": req.video_speed_max,
            "threading_workers": req.tts_workers,
            "bgm_volume": req.bgm_volume,
            "voice_clone_engine": req.voice_clone_engine,
            "voice_clone_device": req.voice_clone_device,
            "voice_clone_concurrency": req.voice_clone_concurrency,
            "cosyvoice_tts_model_version": req.cosyvoice_tts_model_version,
            "cosyvoice_tts_model_path": req.cosyvoice_tts_model_path or None,
            "cosyvoice_tts_prompt_audio": req.cosyvoice_tts_prompt_audio or None,
            "cosyvoice_tts_prompt_text": req.cosyvoice_tts_prompt_text or None,
            "cosyvoice_tts_fp16": req.cosyvoice_tts_fp16,
            "cosyvoice_tts_workers": req.cosyvoice_tts_workers,
            "cosyvoice_tts_speed": req.cosyvoice_tts_speed,
            "cosyvoice_tts_mode": req.cosyvoice_tts_mode,
            "cosyvoice_tts_lang": req.cosyvoice_tts_lang,
            "indextts_fp16": req.indextts_fp16,
            "indextts_enable_clone": req.indextts_enable_clone,
            "indextts_speaker_audio": req.indextts_speaker_audio or None,
            "indextts_checkpoints_dir": req.indextts_checkpoints_dir or None,
            "loudness_norm_enabled": req.loudness_norm_enabled,
            "loudness_target_auto": req.loudness_target_auto,
            "loudness_target_lufs": req.loudness_target_lufs,
            "enable_emotion": req.enable_emotion,
            # Voice clone (existing — keep for backward compat)
            "cosyvoice_mode": req.cosyvoice_mode,
            "cosyvoice_model_version": req.cosyvoice_model_version,
        }
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return str(config_path)


class BatchRunRequest(BaseModel):
    video_paths: list[str]
    config: dict


class BatchRunResponse(BaseModel):
    batch_id: str
    video_count: int


@app.post("/api/batch/run", response_model=BatchRunResponse)
async def start_batch(req: BatchRunRequest) -> BatchRunResponse:
    for p in req.video_paths:
        if not Path(p).is_file():
            raise HTTPException(status_code=400, detail=f"视频文件不存在: {p}")

    batch_id = "batch_" + uuid.uuid4().hex[:8]
    batch = BatchSession(
        id=batch_id,
        config_json=json.dumps(req.config),
        video_paths=req.video_paths,
        status="running",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _batches[batch_id] = batch
    _save_batch(batch)

    asyncio.create_task(_batch_processor(batch_id))
    return BatchRunResponse(batch_id=batch_id, video_count=len(req.video_paths))


@app.post("/api/batch/{batch_id}/skip")
async def skip_current_video(batch_id: str) -> dict:
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status != "running":
        raise HTTPException(status_code=400, detail="Batch is not running")

    idx = batch.current_video_index
    if idx < len(batch.video_paths):
        current_path = batch.video_paths[idx]
        job_id = batch.video_job_ids.get(current_path)
        if job_id:
            job = _jobs.get(job_id)
            if job and job.process and job.process.returncode is None:
                job.process.terminate()
                try:
                    job.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    job.process.kill()
                job.status = "cancelled"
                job.current_step = "已跳过"
                job.append_log("[WARN] 用户跳过此视频")
                _save_job(job)

        batch.append_log(f"[BATCH] 跳过: {os.path.basename(current_path)}")

    _save_batch(batch)
    return {"ok": True}


def _build_batch_dict(batch: BatchSession) -> dict:
    videos: list[dict] = []
    for video_path in batch.video_paths:
        job_id = batch.video_job_ids.get(video_path)
        job = _jobs.get(job_id) if job_id else None
        videos.append({
            "video_path": video_path,
            "video_name": os.path.basename(video_path),
            "status": job.status if job else "queued",
            "progress": job.progress if job else 0,
            "current_step": job.current_step if job else "排队中",
            "job_id": job_id,
        })
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "current_index": batch.current_video_index,
        "total_count": len(batch.video_paths),
        "completed_count": sum(1 for v in videos if v["status"] == "completed"),
        "failed_count": sum(1 for v in videos if v["status"] == "failed"),
        "videos": videos,
        "logs": batch.logs,
        "created_at": batch.created_at,
    }


@app.get("/api/batch/{batch_id}")
async def get_batch_status(batch_id: str) -> dict:
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return _build_batch_dict(batch)


@app.post("/api/batch/{batch_id}/cancel")
async def cancel_batch(batch_id: str) -> dict:
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch.status = "cancelled"
    batch.append_log("[BATCH] 批次已取消")

    if batch.current_video_index < len(batch.video_paths):
        current_path = batch.video_paths[batch.current_video_index]
        job_id = batch.video_job_ids.get(current_path)
        if job_id:
            job = _jobs.get(job_id)
            if job and job.process and job.process.returncode is None:
                job.process.terminate()
                try:
                    job.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    job.process.kill()
                job.status = "cancelled"
                job.current_step = "已取消"
                job.append_log("[WARN] 批次取消，任务终止")
                _save_job(job)

    _save_batch(batch)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings & Subtitle presets
# ---------------------------------------------------------------------------

class SubtitleOptimizeRequest(BaseModel):
    target_srt: str
    source_srt: str | None = None
    mode: str = "target_only"       # target_only | bilingual
    lang: str = "zh"
    min_duration: float | None = None
    reading_speed: float | None = None
    max_merge_gap: float = 0.3
    inter_gap: float = 0.05
    max_duration: float = 10.0


@app.post("/api/subtitle/optimize")
async def subtitle_optimize(req: SubtitleOptimizeRequest) -> dict:
    from core.compat import compat_optimize_external_srt, compat_load_ext_subtitle_config

    target = Path(req.target_srt)
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"目标字幕文件不存在: {req.target_srt}")

    # Load defaults from config
    cfg = compat_load_ext_subtitle_config()
    mode = req.mode or cfg.get("mode", "target_only")

    if mode == "bilingual" and not req.source_srt:
        raise HTTPException(status_code=400, detail="双语模式需要提供原文字幕文件")

    if req.source_srt and not Path(req.source_srt).is_file():
        raise HTTPException(status_code=400, detail=f"原文字幕文件不存在: {req.source_srt}")

    # Output path: same dir, _optimized suffix
    stem, ext = os.path.splitext(str(target))
    output_path = f"{stem}_optimized{ext}"

    kwargs = {
        "lang": req.lang,
        "min_duration": req.min_duration,
        "reading_speed": req.reading_speed,
        "max_merge_gap": req.max_merge_gap,
        "inter_gap": req.inter_gap,
        "max_duration": req.max_duration,
    }

    if mode == "bilingual" and req.source_srt:
        stats = compat_optimize_external_srt(req.target_srt, req.source_srt, output_path, **kwargs)
    else:
        stats = compat_optimize_external_srt(req.target_srt, "", output_path, **kwargs)

    return {"ok": True, "output_path": output_path, "stats": stats}


@app.get("/api/subtitle/optimize-defaults")
async def subtitle_optimize_defaults() -> dict:
    from core.compat import compat_load_ext_subtitle_config
    cfg = compat_load_ext_subtitle_config()
    return {
        "mode": cfg.get("mode", "target_only"),
        "min_duration_cjk": cfg.get("min_duration_cjk", 1.5),
        "reading_speed_cjk": cfg.get("reading_speed_cjk", 4.0),
        "min_duration_latin": cfg.get("min_duration_latin", 1.2),
        "reading_speed_latin": cfg.get("reading_speed_latin", 12.0),
        "min_duration_arabic": cfg.get("min_duration_arabic", 1.3),
        "reading_speed_arabic": cfg.get("reading_speed_arabic", 10.0),
        "max_merge_gap": cfg.get("max_merge_gap", 0.3),
        "inter_gap": cfg.get("inter_gap", 0.05),
        "max_duration": cfg.get("max_duration", 10.0),
    }


# ---------------------------------------------------------------------------
# Subtitle review / calibration
# ---------------------------------------------------------------------------

class ReviewLoadRequest(BaseModel):
    source_srt: str | None = None
    translated_srt: str | None = None
    translate_log: str | None = None
    workspace: str | None = None


@app.get("/api/project/manifest/resolve")
async def project_manifest_resolve(workspace: str) -> dict:
    """读取 project.json 并返回解析后的绝对文件路径，供前端直接使用。"""
    manifest_path = os.path.join(workspace, "project.json")
    if not os.path.isfile(manifest_path):
        # CLI (tvw.py) 旧工作区可能没有 project.json — 从 session.json 合成
        session_path = os.path.join(workspace, "session.json")
        if not os.path.isfile(session_path):
            raise HTTPException(status_code=404, detail="project.json 不存在")
        manifest = {"video_path": "", "files": {}}
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                manifest["video_path"] = json.load(f).get("video_path", "")
        except Exception:
            pass
    else:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

    files = manifest.get("files", {})
    workspace_dir = os.path.abspath(workspace)

    def _resolve(key: str, fallback: str = "") -> str:
        rel = files.get(key, "")
        if rel:
            abs_path = os.path.join(workspace_dir, rel)
            if os.path.isfile(abs_path):
                return os.path.normpath(abs_path)
        if fallback:
            abs_path = os.path.join(workspace_dir, fallback)
            if os.path.isfile(abs_path):
                return os.path.normpath(abs_path)
        return ""

    source_srt = _resolve("source_srt", "01_extract/source.srt")
    machine_srt = _resolve("machine_srt", "02_translate/machine.srt")
    reviewed_srt = _resolve("reviewed_srt", "")
    translate_log = _resolve("translate_log", "02_translate/translate-log.json")

    # 优先 reviewed_srt，否则 machine_srt
    translated_srt = reviewed_srt or machine_srt

    # 获取视频时长（从 ffprobe）
    video_duration = 0
    video_path = manifest.get("video_path", "")
    if video_path and os.path.isfile(video_path):
        try:
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                video_duration = float(result.stdout.strip())
        except Exception:
            pass

    return {
        "manifest": manifest,
        "video_path": video_path,
        "workspace": os.path.normpath(workspace_dir),
        "video_duration": video_duration,
        "paths": {
            "source_srt": source_srt,
            "translated_srt": translated_srt,
            "machine_srt": machine_srt,
            "reviewed_srt": reviewed_srt,
            "translate_log": translate_log,
        },
    }


def _srt_time_to_ms(srt_time) -> int:
    return srt_time.ordinal



def _detect_video_in_dir(srt_path: str) -> str:
    srt_dir = os.path.dirname(srt_path)
    srt_stem = os.path.splitext(os.path.basename(srt_path))[0]
    VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}

    # Search directories: SRT dir first, then parent dir (pipeline uses {name}_out/)
    search_dirs = [srt_dir]
    parent_dir = os.path.dirname(srt_dir)
    if parent_dir and parent_dir != srt_dir:
        search_dirs.append(parent_dir)

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        # Prefer exact stem match, then any video file
        for name in sorted(os.listdir(search_dir)):
            _, ext = os.path.splitext(name)
            if ext.lower() not in VIDEO_EXTS:
                continue
            video_path = os.path.join(search_dir, name)
            if not os.path.isfile(video_path):
                continue
            stem, _ = os.path.splitext(name)
            if stem == srt_stem:
                return video_path
        # Fallback: any video in the directory
        for name in sorted(os.listdir(search_dir)):
            _, ext = os.path.splitext(name)
            if ext.lower() in VIDEO_EXTS:
                video_path = os.path.join(search_dir, name)
                if os.path.isfile(video_path):
                    return video_path
    return ""


def _run_qa_checks(entries: list[dict], lang: str = "zh") -> None:
    for i, entry in enumerate(entries):
        duration = (entry["endMs"] - entry["startMs"]) / 1000.0
        text = entry.get("translatedText", "")
        char_count = len(text.replace("\n", ""))
        cps = char_count / duration if duration > 0 else 0
        cps_limit = 12 if lang in ("zh", "ja", "ko") else 20

        if cps > cps_limit:
            entry.setdefault("issues", []).append({
                "type": "cps_high", "message": f"CPS {cps:.1f} > {cps_limit}",
                "severity": "warning",
            })
        if duration < 0.8:
            entry.setdefault("issues", []).append({
                "type": "duration_short", "message": f"时长 {duration:.2f}s < 0.8s",
                "severity": "warning",
            })
        elif duration > 7.0:
            entry.setdefault("issues", []).append({
                "type": "duration_long", "message": f"时长 {duration:.2f}s > 7.0s",
                "severity": "warning",
            })
        if not text.strip():
            entry.setdefault("issues", []).append({
                "type": "empty", "message": "译文为空",
                "severity": "error",
            })
        if i > 0:
            prev_end = entries[i - 1]["endMs"]
            if entry["startMs"] < prev_end:
                entry.setdefault("issues", []).append({
                    "type": "overlap",
                    "message": f"与上一条重叠 {prev_end - entry['startMs']}ms",
                    "severity": "error",
                })
def _synthesize_srt_from_timeline(workspace: str) -> tuple[str, str] | None:
    """core/ 工作区无 SRT 工件时，从 timeline.json 生成 source.srt / machine.srt。

    返回 (source_srt_path, machine_srt_path)；timeline.json 缺失或为空返回 None。
    """
    tl_path = os.path.join(workspace, "01_extract", "timeline.json")
    if not os.path.isfile(tl_path):
        return None
    try:
        with open(tl_path, "r", encoding="utf-8") as f:
            events = json.load(f).get("events", [])
    except Exception:
        return None
    if not events:
        return None

    def _ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _dump(items: list, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for i, (st, et, txt) in enumerate(items, 1):
                f.write(f"{i}\n{_ts(st)} --> {_ts(et)}\n{txt}\n\n")

    src_items, tr_items = [], []
    for e in events:
        tr = e.get("translation")
        if isinstance(tr, dict):
            tr = tr.get("text", "") or ""
        src_items.append((e.get("start", 0), e.get("end", 0), e.get("text", "")))
        tr_items.append((e.get("start", 0), e.get("end", 0), tr or ""))

    src_path = os.path.join(workspace, "01_extract", "source.srt")
    tr_path = os.path.join(workspace, "02_translate", "machine.srt")
    _dump(src_items, src_path)
    _dump(tr_items, tr_path)
    return src_path, tr_path


@app.post("/api/subtitle/review/load")
async def review_load(req: ReviewLoadRequest) -> dict:

    # 从工作目录 manifest 加载
    if req.workspace:
        manifest_path = os.path.join(req.workspace, "project.json")
        if not os.path.isfile(manifest_path):
            raise HTTPException(status_code=400, detail=f"project.json 不存在: {req.workspace}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        ws = req.workspace
        files = manifest.get("files", {})
        src = files.get("source_srt", "01_extract/source.srt")
        tr = files.get("reviewed_srt") or files.get("machine_srt", "02_translate/machine.srt")
        log = files.get("translate_log", "02_translate/source-translate-log.json")
        sf_rel = files.get("translate_semantic_flagged", "02_translate/source-translate-semantic-flagged.json")
        qr_rel = files.get("quality_report", "02_translate/quality_report.json")
        pm_rel = files.get("prompt_manifest", "02_translate/source-prompt-manifest.json")
        source = Path(os.path.join(ws, src))
        translated = Path(os.path.join(ws, tr))
        translate_log = os.path.join(ws, log)
        semantic_flagged_json = os.path.join(ws, sf_rel)
        quality_report_json = os.path.join(ws, qr_rel)
        prompt_manifest_json = os.path.join(ws, pm_rel)
    else:
        source = Path(req.source_srt)
        translated = Path(req.translated_srt)
        translate_log = req.translate_log
        # 手动加载时从源字幕路径推导 workspace
        _ws_derived = os.path.dirname(os.path.dirname(str(source)))
        semantic_flagged_json = os.path.join(
            _ws_derived, "02_translate", "source-translate-semantic-flagged.json",
        )
        quality_report_json = os.path.join(_ws_derived, "02_translate", "quality_report.json")
        prompt_manifest_json = os.path.join(_ws_derived, "02_translate", "source-prompt-manifest.json")

    if not source.is_file() and req.workspace:
        # core/ 工作区: SRT 工件不存在时从 timeline.json 合成
        synth = _synthesize_srt_from_timeline(req.workspace)
        if synth:
            source, translated = Path(synth[0]), Path(synth[1])

    if not source.is_file():
        raise HTTPException(status_code=400, detail=f"原文字幕不存在: {source}（项目可能尚未运行字幕提取）")
    if not translated.is_file():
        raise HTTPException(status_code=400, detail=f"译文字幕不存在: {translated}（项目可能尚未完成翻译）")

    src_subs = pysrt.open(str(source))
    tr_subs = pysrt.open(str(translated))

    tr_map: dict[int, pysrt.SubRipItem] = {}
    for sub in tr_subs:
        tr_map[sub.index] = sub

    # Read translate-log.json for semantic check scores
    similarity_map: dict[int, float] = {}
    if translate_log:
        if not os.path.isfile(translate_log):
            # 兼容旧目录：文件可能在 01_extract/ 而非 02_translate/
            translate_log = os.path.join(os.path.dirname(translate_log), "..", "01_extract",
                                         os.path.basename(translate_log))
        if os.path.isfile(translate_log):
            try:
                with open(translate_log, "r", encoding="utf-8") as f:
                    log_data = json.load(f)
                for detail in log_data.get("details", []):
                    # 新格式：per-index similarities 映射
                    sims = detail.get("similarities")
                    if sims and isinstance(sims, dict):
                        for idx_str, score in sims.items():
                            similarity_map[int(idx_str)] = score
                    # 旧格式兼容：单个 similarity + indices 列表
                    sim = detail.get("similarity")
                    for idx in detail.get("indices", []):
                        if sim is not None and idx not in similarity_map:
                            similarity_map[idx] = sim
            except Exception:
                pass

    # 读取语义校验标记文件
    semantic_flagged_map: dict[int, dict] = {}
    if not os.path.isfile(semantic_flagged_json):
        # 兼容旧目录：文件可能在 01_extract/ 而非 02_translate/
        semantic_flagged_json = os.path.join(os.path.dirname(semantic_flagged_json), "..", "01_extract",
                                             os.path.basename(semantic_flagged_json))
    if os.path.isfile(semantic_flagged_json):
        try:
            with open(semantic_flagged_json, "r", encoding="utf-8") as f:
                sf_data = json.load(f)
            for item in sf_data.get("flagged", []):
                semantic_flagged_map[item["index"]] = item
        except Exception:
            pass

    # 读取质量报告 (quality_report.json，可选)
    quality_map: dict[int, dict] = {}
    quality_summary = None
    if os.path.isfile(quality_report_json):
        try:
            with open(quality_report_json, "r", encoding="utf-8") as f:
                qr = json.load(f)
            for entry in qr.get("entries", []):
                quality_map[entry["index"]] = entry
            quality_summary = qr.get("summary")
        except Exception:
            pass

    # 读取 Prompt 清单 (prompt_manifest.json，可选)
    prompt_manifest = None
    if os.path.isfile(prompt_manifest_json):
        try:
            with open(prompt_manifest_json, "r", encoding="utf-8") as f:
                prompt_manifest = json.load(f)
        except Exception:
            pass

    # 从 translate.yaml 读取语义阈值
    semantic_threshold = 0.65
    try:
        trans_cfg = _load_yaml(PROJECT_ROOT / "config" / "translate.yaml").get("translate", {})
        semantic_threshold = trans_cfg.get("semantic_threshold", 0.65)
    except Exception:
        pass

    lang = "zh"
    sample = " ".join(sub.text for sub in src_subs[:20])
    ja_chars = len(re.findall(r"[぀-ゟ゠-ヿ一-鿿]", sample))
    if ja_chars > 20:
        lang = "ja"
    elif len(re.findall(r"[a-zA-Z]", sample)) > len(sample) * 0.3:
        lang = "en"

    entries: list[dict] = []
    low_similarity_count = 0

    # core/ 工作区: SRT 是 timeline.json 的派生物, 本身无事件 ID —
    # 按开始时间匹配关联 (review 保存时 patch 需要真实 target, 禁止伪造 entry_N)
    event_id_by_start: list[tuple[float, str]] = []
    if req.workspace:
        tl_path = os.path.join(req.workspace, "01_extract", "timeline.json")
        if os.path.isfile(tl_path):
            try:
                with open(tl_path, "r", encoding="utf-8") as f:
                    tl = json.load(f)
                event_id_by_start = sorted(
                    (float(e.get("start", 0)) * 1000, str(e.get("id", "")))
                    for e in tl.get("events", []) if e.get("id")
                )
            except Exception:
                event_id_by_start = []

    def _match_event_id(start_ms: float) -> str | None:
        """按开始时间匹配事件, 容差 ±500ms, 无匹配返回 None (调用方显式处理)。"""
        best_id, best_delta = None, 500.0
        for s_ms, eid in event_id_by_start:
            delta = abs(s_ms - start_ms)
            if delta <= best_delta:
                best_id, best_delta = eid, delta
            elif s_ms > start_ms:
                break
        return best_id

    for src in src_subs:
        tr = tr_map.get(src.index)
        translated_text = tr.text if tr else ""
        start_ms = _srt_time_to_ms(src.start)
        end_ms = _srt_time_to_ms(src.end)

        issues: list[dict] = []
        sim = similarity_map.get(src.index)
        if sim is not None and sim < semantic_threshold:
            issues.append({
                "type": "low_similarity",
                "message": f"语义相似度低 ({sim:.2f})",
                "severity": "warning",
            })
            low_similarity_count += 1

        # 语义校验详情（来自 translate-semantic-flagged.json）
        sf_data = semantic_flagged_map.get(src.index)
        semantic_flagged = None
        if sf_data:
            semantic_flagged = {
                "similarity": sf_data.get("similarity"),
                "retried": sf_data.get("retried", False),
                "kept": sf_data.get("kept", "first"),
                "improvement": sf_data.get("improvement"),
                "retriedSimilarity": sf_data.get("new_similarity"),
                "retriedText": sf_data.get("new_translated", ""),
                "originalText": sf_data.get("translated", ""),
            }

        # 质量评分 (from quality_report.json)
        quality = quality_map.get(src.index)

        entries.append({
            "index": src.index,
            "start": str(src.start),
            "end": str(src.end),
            "startMs": start_ms,
            "endMs": end_ms,
            "sourceText": src.text,
            "translatedText": translated_text,
            "reviewStatus": "pending",
            "issues": issues,
            "similarity": sim,
            "semanticFlagged": semantic_flagged,
            "quality": quality.get("scores") if quality else None,
            "tier": quality.get("tier") if quality else None,
            "tierReason": quality.get("tierReason") if quality else None,
            "eventId": _match_event_id(start_ms),
        })

    _run_qa_checks(entries, lang)

    # Video detection: manifest first, then directory scan
    video_path = ""
    if req.workspace:
        manifest_path = os.path.join(req.workspace, "project.json")
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                video_path = json.load(f).get("video_path", "")
    if not video_path:
        video_path = _detect_video_in_dir(str(source))

    response = {
        "videoPath": video_path,
        "sourceSrtPath": str(source),
        "translatedSrtPath": str(translated),
        "entries": entries,
        "stats": {"total": len(entries), "lowSimilarity": low_similarity_count},
        "qualitySummary": quality_summary,
    }
    if prompt_manifest:
        response["promptManifest"] = prompt_manifest
    return response


class ReviewSaveRequest(BaseModel):
    translated_srt: str
    entries: list[dict]


@app.post("/api/subtitle/review/save")
async def review_save(req: ReviewSaveRequest) -> dict:

    translated = Path(req.translated_srt)
    if not translated.is_file():
        raise HTTPException(status_code=400, detail=f"字幕文件不存在: {req.translated_srt}")

    subs = pysrt.open(str(translated))
    updated = 0

    changes: dict[int, str] = {}
    for e in req.entries:
        if e.get("reviewStatus") == "modified":
            changes[e["index"]] = e["translatedText"]

    for sub in subs:
        if sub.index in changes:
            sub.text = changes[sub.index]
            updated += 1

    # 输出到工作目录 02_translate/reviewed.srt
    ws_reviewed = os.path.join(os.path.dirname(str(translated)), "..", "reviewed.srt")
    output_path = os.path.normpath(ws_reviewed)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    subs.save(output_path, encoding="utf-8")
    logger.info(f"Review saved: {updated} entries updated → {output_path}")

    return {"ok": True, "output_path": output_path, "updated": updated}


@app.get("/api/logs/recent")
async def logs_recent(limit: int = 200, workspace: str = ""):
    """全局日志尾部 (P5-B): 优先当前 workspace 的 pipeline.log, 否则 GUI/logs/ 最新 server 日志。

    日志按钮不再"形同虚设" — 无 job 运行时也能看到 server 进程日志。
    """
    lines: list[str] = []
    source = "server"
    if workspace:
        ws_log = Path(workspace) / "pipeline.log"
        if ws_log.is_file():
            try:
                with open(ws_log, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                source = "workspace"
            except OSError:
                lines = []
    if not lines:
        try:
            logs_dir = Path(LOG_DIR)
            candidates = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                with open(candidates[0], "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
        except OSError:
            lines = []
    return {"lines": lines[-limit:], "total": len(lines), "source": source}


@app.get("/api/config")
async def get_config() -> dict:
    """返回设置视图: config = 默认 + 用户差异合并, defaults = 系统默认, overridden = 被覆盖的键。

    差异层语义 (P1): settings.json["pipeline"] 只存用户改过的键,
    GET 时与 _snake_defaults() 合并后返回; 旧数据中的 null 残留自动过滤。
    """
    settings = load_settings()
    saved = settings.get("pipeline", {}) or {}
    defaults = _snake_defaults()
    merged = dict(defaults)
    from core.runtime.config_resolver import deep_merge
    clean = {k: v for k, v in saved.items() if v is not None}
    deep_merge(merged, clean)
    # P5-A: 质量策略选项来自 core 注册表 (单一事实源, 前端动态渲染不再硬编码)
    from core.quality.protocol import list_strategies
    return {
        "config": merged,
        "defaults": defaults,
        "overridden": list(clean.keys()),
        "quality_strategies": list_strategies(),
    }


@app.post("/api/config")
async def post_config(payload: dict) -> dict:
    """差异层写入: 增量 deep_merge 到 settings.json["pipeline"], null = 删除键 (恢复默认)。

    与 core/runtime/config_resolver.py 的 deep_merge 语义一致。
    修 P1 数据丢失: 旧实现整体替换, GlossaryManager 单键 POST 会清掉其它设置。
    """
    from core.runtime.config_resolver import deep_merge
    cfg = payload.get("config", payload)
    settings = load_settings()
    pipeline = settings.get("pipeline", {}) or {}
    deep_merge(pipeline, cfg)
    settings["pipeline"] = pipeline
    save_settings(settings)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Model Manager endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tts/speakers")
async def list_chattts_speakers() -> list[dict]:
    """列出预设 ChatTTS 音色（来自 ChatTTS_Speaker 排行榜）。"""
    import json
    speakers_path = PROJECT_ROOT / "models" / "chattts_speakers" / "speakers.json"
    if not speakers_path.is_file():
        return []
    with open(speakers_path, "r", encoding="utf-8") as f:
        return json.load(f)


# Edge TTS 语音列表缓存
_edge_voices_cache: list[dict] | None = None

@app.get("/api/tts/edge-voices")
async def list_edge_voices() -> list[dict]:
    """列出 Edge TTS 可用语音（按常用语言筛选，缓存结果）。"""
    global _edge_voices_cache
    if _edge_voices_cache is not None:
        return _edge_voices_cache
    import asyncio
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
    except ImportError:
        return []
    except Exception:
        return []

    # 常用语言前缀
    USEFUL = ("zh-CN", "zh-TW", "zh-HK", "ja-JP", "ko-KR",
              "en-US", "en-GB", "en-AU",
              "fr-FR", "de-DE", "es-ES", "pt-BR",
              "ru-RU", "ar-SA", "th-TH", "vi-VN", "id-ID", "it-IT")
    result = []
    for v in voices:
        short = v.get("ShortName", "")
        if any(short.startswith(p) for p in USEFUL):
            result.append({
                "name": short,
                "display": v.get("FriendlyName", short),
                "locale": v.get("Locale", ""),
                "gender": v.get("Gender", ""),
                "language": short.rsplit("-", 1)[0] if "-" in short else short,
            })
    _edge_voices_cache = result
    return result


# ---------------------------------------------------------------------------
# ChatTTS voice preview (gacha)
# ---------------------------------------------------------------------------

class ChatTTSPreviewRequest(BaseModel):
    seed: Optional[int] = None
    text: str = "这是一个ChatTTS语音合成测试案例。"
    model_source: str = "local"
    model_path: str = ""
    spk_emb: str = ""  # 预存的说话人嵌入，非空时跳过随机生成直接复用
    speaker_pt: str = ""  # 预设音色 .pt 文件路径，优先级最高


# 模块级 ChatTTS 引擎缓存：多次抽卡复用同一模型实例，避免反复加载 2.37GB
_chattts_engine = None
_chattts_engine_config = None  # (model_source, model_path)


@app.post("/api/tts/preview-chattts")
async def preview_chattts_voice(req: ChatTTSPreviewRequest) -> dict:
    """抽卡预览 ChatTTS 音色。

    PT 预设音色：首次合成后缓存 WAV，后续直接读缓存（无需 GPU）。
    自定义抽卡：每次随机生成，用后释放 VRAM。
    """
    global _chattts_engine, _chattts_engine_config

    import base64
    import tempfile
    import shutil
    from core.compat import compat_chattts_factory

    config_key = (req.model_source, req.model_path or "", req.speaker_pt or "")

    # ── PT 预设音色：缓存命中直接返回，无需 GPU ──
    cache_path = ""
    if req.speaker_pt:
        cache_path = req.speaker_pt.replace(".pt", "_preview.wav")
        if os.path.isfile(cache_path):
            with open(cache_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("ascii")
            return {
                "seed": None,
                "spk_emb": "",
                "audio_base64": audio_b64,
                "duration": round(float(len(base64.b64decode(audio_b64))) / 48000, 2),
                "text": req.text,
                "cached": True,
            }

    if _chattts_engine is not None and _chattts_engine_config != config_key:
        _chattts_engine.cleanup()
        _chattts_engine = None

    if _chattts_engine is None:
        _chattts_engine = ChatTTSEngine(
            speaker_seed=req.seed,
            model_source=req.model_source,
            model_path=req.model_path or None,
            spk_emb=req.spk_emb or None,
            speaker_pt=req.speaker_pt or None,
        )
        _chattts_engine_config = config_key
    elif req.speaker_pt:
        pass  # PT 模式无需换 seed
    elif req.spk_emb:
        if not _chattts_engine.spk_emb:
            _chattts_engine.reset_speaker(req.seed)
    else:
        _chattts_engine.reset_speaker(req.seed)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        duration = _chattts_engine.synthesize(req.text, tmp_path)

        # PT 预设 → 缓存 WAV 供后续复用
        if cache_path:
            shutil.copy2(tmp_path, cache_path)

        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")
        spk_emb_val = _chattts_engine.spk_emb
        if spk_emb_val is not None and not isinstance(spk_emb_val, str):
            spk_emb_val = ""  # tensor 不能 JSON 序列化
        return {
            "seed": _chattts_engine.speaker_seed,
            "spk_emb": spk_emb_val or "",
            "audio_base64": audio_b64,
            "duration": round(duration, 2),
            "text": req.text,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        # PT 预设音色：合成后立即释放 VRAM（缓存 WAV 供后续直接用）
        if cache_path and _chattts_engine is not None:
            _chattts_engine.cleanup()
            _chattts_engine = None
            _chattts_engine_config = None


def _release_chattts_engine_if_loaded() -> None:
    """释放 ChatTTS 预览引擎 — 流水线启动前归还 GPU 显存 (3060Ti 显存紧张)。"""
    global _chattts_engine, _chattts_engine_config
    if _chattts_engine is None:
        return
    try:
        _chattts_engine.cleanup()
    except Exception as e:
        logger.warning("ChatTTS 预览引擎释放失败: %s", e)
    _chattts_engine = None
    _chattts_engine_config = None


@app.post("/api/tts/release-chattts")
async def release_chattts_engine() -> dict:
    """释放 ChatTTS 预览引擎，归还 GPU 显存给流水线使用。"""
    _release_chattts_engine_if_loaded()
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:
        logger.warning("torch 显存清理失败: %s", e)
    return {"status": "released"}


class TTSPreviewRequest(BaseModel):
    text: str = ""
    engine: str = "chattts"
    voice_id: str = ""
    speaker_seed: int = 2


@app.post("/api/tts/preview")
async def tts_preview(req: TTSPreviewRequest) -> dict:
    """TTS 预览 — 调用对应引擎合成单个句子 (T4.4)。"""
    import base64, tempfile, numpy as np

    out_path = os.path.join(tempfile.gettempdir(), f"tvw_preview_{int(time.time())}.wav")
    try:
        if req.engine == "edge":
            import edge_tts
            communicate = edge_tts.Communicate(req.text, req.voice_id or "zh-CN-XiaoxiaoNeural")
            await communicate.save(out_path)
        else:
            from core.compat import compat_chattts_factory
            engine_cls = compat_chattts_factory()
            engine = engine_cls()
            engine.synthesize(req.text, out_path)

        with open(out_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        duration = 0.0
        try:
            import soundfile as sf
            info = sf.info(out_path)
            duration = info.duration
        except Exception:
            pass
        return {"audio_base64": audio_b64, "duration": duration, "path": out_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS preview failed: {e}")
    finally:
        try:
            os.unlink(out_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Glossary CRUD
# ---------------------------------------------------------------------------

@app.get("/api/glossary/dicts")
async def list_glossary_dicts() -> dict:
    terms_dir = PROJECT_ROOT / "config" / "terms"
    if not terms_dir.is_dir():
        return {"dicts": []}
    dicts = []
    for f in sorted(terms_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text("utf-8"))
            dicts.append({
                "name": f.stem,
                "description": data.get("description", ""),
                "termCount": len(data.get("terms", {})),
            })
        except Exception:
            pass
    return {"dicts": dicts}


@app.get("/api/glossary/dict/{name}")
async def get_glossary_dict(name: str) -> dict:
    path = PROJECT_ROOT / "config" / "terms" / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Dictionary not found: {name}")
    return json.loads(path.read_text("utf-8"))


# 术语表缓存 — 20 万条 minecraft_mod.json 每次 json.loads 太慢
_glossary_cache: dict[str, dict] = {}  # {name: {"entries": [(k,v),...], "mtime": float}}


def _get_glossary_entries(name: str) -> list[tuple[str, str]]:
    """返回术语表词条列表，使用缓存避免重复解析大 JSON。"""
    path = PROJECT_ROOT / "config" / "terms" / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Dictionary not found: {name}")
    mtime = path.stat().st_mtime
    cached = _glossary_cache.get(name)
    if cached and cached["mtime"] == mtime:
        return cached["entries"]
    data = json.loads(path.read_text("utf-8"))
    entries = list(data.get("terms", {}).items())
    _glossary_cache[name] = {"entries": entries, "mtime": mtime}
    return entries


def _invalidate_glossary_cache(name: str) -> None:
    _glossary_cache.pop(name, None)


@app.get("/api/glossary/dict/{name}/terms")
async def search_glossary_terms(name: str, q: str = "", offset: int = 0, limit: int = 200) -> dict:
    """分页搜索术语表词条。大文件 (20 万条) 走缓存，不反复解析 JSON。"""
    entries = _get_glossary_entries(name)
    if q:
        ql = q.lower()
        entries = [(k, v) for k, v in entries if ql in k.lower() or ql in v.lower()]
    total = len(entries)
    page = entries[offset:offset + limit]
    return {
        "name": name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [{"key": k, "value": v} for k, v in page],
    }


@app.post("/api/glossary/dict/{name}")
async def save_glossary_dict(name: str, payload: dict) -> dict:
    terms_dir = PROJECT_ROOT / "config" / "terms"
    terms_dir.mkdir(parents=True, exist_ok=True)
    path = terms_dir / f"{name}.json"
    data = {
        "name": name,
        "description": payload.get("description", ""),
        "terms": payload.get("terms", {}),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_glossary_cache(name)
    return {"ok": True, "name": name, "termCount": len(data["terms"])}


@app.delete("/api/glossary/dict/{name}")
async def delete_glossary_dict(name: str) -> dict:
    path = PROJECT_ROOT / "config" / "terms" / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Dictionary not found: {name}")
    path.unlink()
    _invalidate_glossary_cache(name)
    return {"ok": True}


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

# Cached system info — GPU name/VRAM don't change at runtime
_sys_info_cache: dict | None = None


@app.get("/api/system/info")
async def system_info() -> dict:
    """Detect CPU/GPU to recommend concurrency and device.

    Only scans on first call; subsequent polls return cached result.
    """
    global _sys_info_cache
    if _sys_info_cache is not None:
        return _sys_info_cache

    import os

    cpu_count = os.cpu_count() or 4

    has_gpu = False
    gpu_name = ""
    gpu_vram_mb = 0

    # Try nvidia-smi (multiple Windows paths)
    nvidia_smi_paths = [
        "nvidia-smi",
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for smi in nvidia_smi_paths:
        try:
            result = subprocess.run(
                [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and result.stdout.strip():
                has_gpu = True
                parts = result.stdout.strip().split(",")
                gpu_name = parts[0].strip()
                try:
                    gpu_vram_mb = int(float(parts[1].strip()))
                except (ValueError, IndexError):
                    pass
                break
        except Exception:
            continue

    # Fallback: check torch CUDA availability
    if not has_gpu:
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                has_gpu = True
                gpu_name = torch.cuda.get_device_name(0)
                gpu_vram_mb = int(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024))
        except Exception:
            pass

    # recommendedConcurrency: legacy translation concurrency
    if has_gpu:
        recommended = min(max(cpu_count // 2, 3), 8)
    else:
        recommended = min(max(cpu_count // 2, 2), 4)

    # Default video input directory
    source_dir = os.path.join(PROJECT_ROOT, "source_file")
    default_video_dir = source_dir if os.path.isdir(source_dir) else str(PROJECT_ROOT)

    # ChatTTS worker count based on VRAM (pass known VRAM to avoid import torch)
    chattts_workers = 1
    try:
        from core.compat import compat_calc_chattts_workers
        chattts_workers = calc_chattts_workers(total_vram_mb=gpu_vram_mb if has_gpu else None)
    except Exception:
        pass

    _sys_info_cache = {
        "cpuCount": cpu_count,
        "hasGpu": has_gpu,
        "gpuName": gpu_name,
        "gpuVramMb": gpu_vram_mb,
        "recommendedConcurrency": recommended,
        "defaultVideoDir": default_video_dir,
        "chatttsWorkers": chattts_workers,
    }
    return _sys_info_cache


@app.get("/api/system/status")
async def system_status() -> dict:
    """实时资源占用 — 状态栏轮询用，不缓存。"""
    cpu_usage = 0.0
    mem_usage = 0.0
    try:
        import psutil
        cpu_usage = psutil.cpu_percent(interval=None)
        mem_usage = psutil.virtual_memory().percent
    except Exception:
        pass

    gpu_usage: float | None = None
    for smi in ("nvidia-smi",
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        try:
            result = subprocess.run(
                [smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_usage = float(result.stdout.strip().splitlines()[0])
                break
        except Exception:
            continue

    return {
        "cpuUsage": round(cpu_usage, 1),
        "memUsage": round(mem_usage, 1),
        "gpuUsage": gpu_usage,
        "modelsOnline": [],
    }


@app.get("/api/video/info")
async def video_info(path: str) -> dict:
    """Return video metadata including resolution for a given file path."""
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=400, detail="视频文件不存在")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="ffmpeg 未安装或不在 PATH 中")

    try:
        result = subprocess.run(
            [ffmpeg, "-i", path],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ffmpeg 执行失败: {e}")

    stderr = result.stderr
    width = height = 0
    duration_sec = 0.0
    duration_str = ""

    for line in stderr.split("\n"):
        if "Duration:" in line:
            duration_str = line.split(",")[0].replace("Duration:", "").strip()
            try:
                parts = duration_str.replace(",", ".").split(":")
                h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
                duration_sec = h * 3600 + m * 60 + s
            except Exception:
                pass
        if "Video:" in line:
            import re
            res = re.search(r"(\d{3,5})x(\d{3,5})", line)
            if res:
                width = int(res.group(1))
                height = int(res.group(2))

    return {
        "width": width,
        "height": height,
        "duration": duration_sec,
        "durationStr": duration_str,
    }


# ---------------------------------------------------------------------------
# Font listing & subtitle preview (PIL + ImageMagick dual-engine)
# ---------------------------------------------------------------------------

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}


def _detect_imagemagick() -> str | None:
    """Find ImageMagick magick.exe binary."""
    import shutil
    auto = shutil.which("magick")
    if auto:
        return auto
    for pattern in [
        r"C:\Program Files\ImageMagick-*\magick.exe",
        r"C:\Program Files (x86)\ImageMagick-*\magick.exe",
        r"F:\Program Files\ImageMagick-*\magick.exe",
    ]:
        import glob as _glob
        found = _glob.glob(pattern)
        if found:
            return sorted(found, reverse=True)[0]
    return None


# Mapping from system font names to Windows font filenames.
# PIL needs actual file paths; ImageMagick can use system names directly.
_WIN_FONT_MAP: dict[str, str] = {
    "simhei":                    "simhei.ttf",
    "simsun":                    "simsun.ttc",
    "kaiti":                     "simkai.ttf",
    "fangsong":                  "simfang.ttf",
    "microsoft yahei":           "msyh.ttc",
    "microsoft-yahei-bold":      "msyhbd.ttc",
    "microsoft yahei bold":      "msyhbd.ttc",
    "microsoft jhenghei":        "msjh.ttc",
    "microsoft jhenghei bold":   "msjhbd.ttc",
    "mingliu":                   "mingliu.ttc",
    "pmingliu":                  "pmingliu.ttc",
    "dengxian":                  "deng.ttf",
    "dengxian bold":             "dengb.ttf",
    "youyuan":                   "simyou.ttf",
    "stkaiti":                   "STKAITI.TTF",
    "stfangsong":                "STFANGSO.TTF",
    "stsong":                    "STSONG.TTF",
    "stxihei":                   "STXIHEI.TTF",
    "stzhongsong":               "STZHONGS.TTF",
    "fzshuti":                   "STXINGKA.TTF",
}
_WIN_FONT_DIRS = [
    r"C:\Windows\Fonts",
    r"C:\WINNT\Fonts",
]


def _resolve_system_font_path(font_name: str) -> str | None:
    """Try to find a system font file on disk from a font name.

    Returns the absolute path if found, None otherwise.
    """
    # Direct lookup in the font map
    key = font_name.lower().strip()
    if key in _WIN_FONT_MAP:
        for fonts_dir in _WIN_FONT_DIRS:
            candidate = os.path.join(fonts_dir, _WIN_FONT_MAP[key])
            if os.path.isfile(candidate):
                return candidate
    # Fallback: scan font directories for matching filename (case-insensitive)
    for fonts_dir in _WIN_FONT_DIRS:
        if not os.path.isdir(fonts_dir):
            continue
        for ext in (".ttf", ".otf", ".ttc"):
            candidate = os.path.join(fonts_dir, font_name + ext)
            if os.path.isfile(candidate):
                return candidate
        # Try listing the directory
        try:
            for entry in os.listdir(fonts_dir):
                stem, ext = os.path.splitext(entry.lower())
                if ext in (".ttf", ".otf", ".ttc") and stem == key:
                    return os.path.join(fonts_dir, entry)
        except PermissionError:
            pass
    return None


def _resolve_font_path(font: str, engine: str = "pil") -> str:
    """Resolve font to an absolute path usable by both PIL and ImageMagick.

    Returns:
      - empty → default project Minecraft font
      - absolute path → verified or raise
      - relative .ttf/.otf/.ttc → resolved against FONT_DIR
      - system font name (e.g. "SimHei"):
          * pil  engine → try to find actual file via _resolve_system_font_path
          * imagemagick → returned as-is
    """
    if not font:
        return str(PROJECT_ROOT / "models" / "font" / "Minecraft_font" / "5_Minecraft_AE_zh_en.ttf")
    if Path(font).is_absolute():
        if not Path(font).is_file():
            raise HTTPException(status_code=400, detail=f"字体文件不存在: {font}")
        return font
    if font.endswith((".ttf", ".otf", ".ttc")) or "/" in font or "\\" in font:
        # 兼容两种输入: 相对 FONT_DIR 的裸路径，或已含 models/font 前缀的路径
        for candidate in (FONT_DIR / font, PROJECT_ROOT / font.lstrip("./")):
            if Path(candidate).is_file():
                return str(candidate)
        raise HTTPException(status_code=400, detail=f"字体文件不存在: {FONT_DIR / font}")
    # System font name
    if engine == "pil":
        sys_path = _resolve_system_font_path(font)
        if sys_path:
            return sys_path
    return font


def _parse_rgba(rgba_str: str) -> tuple[int, int, int, int]:
    """Parse 'rgba(R,G,B,A)' or 'R,G,B,A' to (R, G, B, A) tuple."""
    import re
    m = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', rgba_str)
    if m:
        return (int(m[1]), int(m[2]), int(m[3]), int(m[4]))
    parts = [p.strip() for p in rgba_str.replace('(', '').replace(')', '').split(',')]
    if len(parts) >= 4:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    return (0, 0, 0, 128)


def _draw_checkerboard(img, box, size: int = 8):
    """Draw a checkerboard pattern inside *box* to reveal semi-transparent overlays."""
    from PIL import ImageDraw as _ImageDraw
    draw = _ImageDraw.Draw(img)
    x0, y0, x1, y1 = [int(v) for v in box]
    for cy in range(y0, y1, size):
        for cx in range(x0, x1, size):
            color = (204, 204, 204, 255) if ((cx // size) + (cy // size)) % 2 == 0 else (136, 136, 136, 255)
            draw.rectangle([cx, cy, min(cx + size, x1), min(cy + size, y1)], fill=color)


def _render_subtitle_pil(
    font_path: str,
    font_size: int,
    font_color: str,
    stroke_color: str,
    stroke_width: float,
    bg_color: str,
    text_zh: str,
    text_en: str,
    alignment: str = "center",
    position: str = "bottom",
    canvas_w: int = 960,
    canvas_h: int = 540,
    max_lines: int = 2,
    font_size_factor: float = 0.030,
    max_font_size: int = 0,
    caption_width_ratio: float = 0.85,
    font_size_mode: str = "adaptive",
) -> bytes:
    """Render subtitle preview using PIL/Pillow (same engine as video output).

    Uses ImageFont.truetype + ImageDraw.multiline_text with adaptive font sizing
    matching CaptionRenderer behavior: shrink font to fit max_lines, cap at max_font_size.
    A solid checkerboard under the subtitle background reveals alpha transparency.
    """
    import io
    from PIL import Image, ImageDraw, ImageFont

    text = f"{text_zh}\n{text_en}" if text_en else text_zh

    # ── Load font ────────────────────────────────────────
    try:
        pil_font = ImageFont.truetype(font_path, font_size)
    except Exception:
        pil_font = ImageFont.load_default()

    # ── Font sizing (mirrors CaptionRenderer) ──
    max_width = int(canvas_w * caption_width_ratio)
    max_fs = max_font_size if max_font_size > 0 else int(canvas_h * 0.045)
    min_fs = 12
    desired = font_size if font_size > 0 else int(canvas_w * font_size_factor)

    if font_size_mode == "fixed" and font_size > 0:
        final_fs = desired
    else:
        def _count_lines(txt: str, fs: int) -> int:
            """Count wrapped lines at given font size and max_width."""
            try:
                f = ImageFont.truetype(font_path, fs)
            except Exception:
                f = ImageFont.load_default()
            total = 0
            for para in txt.split("\n"):
                if not para:
                    total += 1
                    continue
                # Detect script and wrap accordingly
                cjk = sum(1 for ch in para if '一' <= ch <= '鿿' or '぀' <= ch <= 'ヿ')
                if cjk > len(para) * 0.3:
                    # CJK: character-by-character
                    line = ""
                    for ch in para:
                        if f.getlength(line + ch) > max_width:
                            if line:
                                total += 1
                            line = ch
                        else:
                            line += ch
                    if line:
                        total += 1
                else:
                    # Latin: word boundary
                    line = ""
                    for word in para.split():
                        sep = " " if line else ""
                        if f.getlength(line + sep + word) > max_width:
                            if line:
                                total += 1
                                line = ""
                            # If single word too long, char-break it
                            if f.getlength(word) > max_width:
                                partial = ""
                                for ch in word:
                                    if f.getlength(partial + ch) > max_width:
                                        if partial:
                                            total += 1
                                        partial = ch
                                    else:
                                        partial += ch
                                line = partial
                            else:
                                line = word
                        else:
                            line = line + sep + word
                    if line:
                        total += 1
            return total

        # Binary search for largest fitting font
        if _count_lines(text, min(desired, max_fs)) <= max_lines:
            final_fs = min(desired, max_fs)
        else:
            best = min_fs
            lo, hi = min_fs, min(desired, max_fs)
            while lo <= hi:
                mid = (lo + hi) // 2
                if mid < min_fs:
                    break
                if _count_lines(text, mid) <= max_lines:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            final_fs = best

    # Re-load font at final size
    try:
        pil_font = ImageFont.truetype(font_path, final_fs)
    except Exception:
        pil_font = ImageFont.load_default()

    # ── Measure at final size ────────────────────────────
    img = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)

    bbox = draw.multiline_textbbox(
        (0, 0), text, font=pil_font, align=alignment, stroke_width=stroke_width,
    )
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    margin = 20
    if alignment == "left":
        x = margin
    elif alignment == "right":
        x = canvas_w - text_w - margin
    else:
        x = (canvas_w - text_w) // 2

    if position == "top":
        y = margin
    else:
        y = canvas_h - text_h - margin

    rgba = _parse_rgba(bg_color)

    bg_pad = 12
    bg_box = [
        max(0, x - bg_pad),
        max(0, y - bg_pad),
        min(canvas_w, x + text_w + bg_pad),
        min(canvas_h, y + text_h + bg_pad),
    ]

    # ── Solid color underlay to reveal alpha transparency ──
    # Draw a full-opacity dark bar spanning the canvas width behind the subtitle area,
    # so the semi-transparent subtitle background (rgba) is visible against a known color
    underlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    underlay_draw = ImageDraw.Draw(underlay)
    underlay_box = [
        0,
        max(0, bg_box[1] - 6),
        canvas_w,
        min(canvas_h, bg_box[3] + 6),
    ]
    underlay_draw.rectangle(underlay_box, fill=(68, 68, 68, 255))
    img = Image.alpha_composite(img, underlay)
    draw = ImageDraw.Draw(img)

    # Draw checkerboard in the subtitle background area
    checker_box = [
        max(0, bg_box[0] - 4),
        max(0, bg_box[1] - 4),
        min(canvas_w, bg_box[2] + 4),
        min(canvas_h, bg_box[3] + 4),
    ]
    _draw_checkerboard(img, checker_box)

    # Semi-transparent background
    bg_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg_overlay)
    bg_draw.rectangle(bg_box, fill=rgba)
    img = Image.alpha_composite(img, bg_overlay)
    draw = ImageDraw.Draw(img)

    draw.multiline_text(
        (x, y), text, font=pil_font, fill=font_color, align=alignment,
        stroke_width=stroke_width, stroke_fill=stroke_color,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_subtitle_imagemagick(
    magick: str,
    font: str,
    font_size: int,
    font_color: str,
    stroke_color: str,
    stroke_width: float,
    bg_color: str,
    text_zh: str,
    text_en: str,
    alignment: str = "center",
    position: str = "bottom",
    canvas_w: int = 960,
    canvas_h: int = 540,
    max_lines: int = 2,
    font_size_factor: float = 0.030,
    max_font_size: int = 0,
    caption_width_ratio: float = 0.85,
) -> bytes:
    """Render subtitle preview using ImageMagick CLI."""
    import subprocess, tempfile

    combined = f"{text_zh}\n{text_en}" if text_en else text_zh
    lines = [ln for ln in combined.split("\n") if ln]
    if not lines:
        lines = [" "]
    rgba = _parse_rgba(bg_color)
    bg_alpha_pct = int(rgba[3] / 255 * 100)

    gravity_map = {
        ("center", "bottom"): "south",
        ("left", "bottom"): "southwest",
        ("right", "bottom"): "southeast",
        ("center", "top"): "north",
        ("left", "top"): "northwest",
        ("right", "top"): "northeast",
    }
    gravity = gravity_map.get((alignment, position), "south")

    line_height = int(font_size * 1.6)
    tmp_dir = tempfile.gettempdir()
    out_path = os.path.join(tmp_dir, f"_subtitle_preview_{os.getpid()}.png")
    tile_path = os.path.join(tmp_dir, f"_checker_{os.getpid()}.png")

    # Generate a checkerboard tile to reveal semi-transparent background alpha
    subprocess.run([
        magick, "-size", "16x16",
        "xc:rgb(204,204,204)",
        "-fill", "rgb(136,136,136)",
        "-draw", "rectangle 0,0 7,7",
        "-draw", "rectangle 8,8 15,15",
        tile_path,
    ], capture_output=True, timeout=5)

    args = [
        magick,
        "-size", f"{canvas_w}x{canvas_h}",
        "xc:rgb(30,30,30)",
        "-tile", tile_path,
        "-draw", f"rectangle 0,{canvas_h - 108} {canvas_w},{canvas_h}",
        "-fill", f"rgba({rgba[0]},{rgba[1]},{rgba[2]},{bg_alpha_pct}%)",
        "-draw", f"rectangle 20,{canvas_h - 100} {canvas_w - 20},{canvas_h - 10}",
        "-gravity", gravity,
        "-encoding", "Unicode",
        "-font", font,
        "-pointsize", str(font_size),
        "-fill", font_color,
        "-stroke", stroke_color,
        "-strokewidth", str(stroke_width),
    ]
    for i, line in enumerate(reversed(lines)):
        y_offset = 20 + i * line_height
        args += ["-annotate", f"+0+{y_offset}", line]
    args.append(out_path)

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            logger.error("ImageMagick render failed: %s", result.stderr[:500])
            raise HTTPException(status_code=500, detail=f"ImageMagick 渲染失败: {result.stderr[:500]}")
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="ImageMagick 未找到")
    finally:
        try:
            os.remove(tile_path)
        except OSError:
            pass

    if not Path(out_path).is_file():
        raise HTTPException(status_code=500, detail="预览图生成失败")

    img_bytes = Path(out_path).read_bytes()
    try:
        os.remove(out_path)
    except OSError:
        pass
    return img_bytes


@app.get("/api/fonts")
async def list_fonts() -> dict:
    """List available font files under models/font/."""
    fonts: list[dict] = []
    if FONT_DIR.is_dir():
        for p in sorted(FONT_DIR.rglob("*")):
            if p.is_file() and p.suffix.lower() in FONT_EXTENSIONS:
                rel = str(p.relative_to(FONT_DIR))
                fonts.append({
                    "name": p.stem,
                    "path": str(p),
                    "relative": rel,
                })
    return {"fonts": fonts, "dir": str(FONT_DIR)}


@app.get("/api/subtitle/preview")
async def subtitle_preview(
    font: str = "",
    font_size: int = 36,
    font_color: str = "white",
    stroke_color: str = "black",
    stroke_width: float = 2,
    bg_color: str = "rgba(0,0,0,128)",
    text_zh: str = "Minecraft我的世界 村民交易",
    text_en: str = "Minecraft Villager Trade x64",
    alignment: str = "center",
    position: str = "bottom",
    engine: str = "pil",
    max_lines: int = 2,
    font_size_factor: float = 0.030,
    max_font_size: int = 0,
    caption_width_ratio: float = 0.85,
    font_size_mode: str = "adaptive",
) -> StreamingResponse:
    """Render a subtitle preview image.

    Two rendering engines:
      - pil (default):   PIL/Pillow — same FreeType engine as video output,
                          correct CJK text measurement and centering.
      - imagemagick:     ImageMagick CLI — legacy, requires ImageMagick.
    """
    from fastapi.responses import Response as RawResponse

    engine = engine.lower()
    if engine not in ("pil", "imagemagick"):
        raise HTTPException(status_code=400, detail=f"Unknown engine: {engine}. Use 'pil' or 'imagemagick'.")
    if alignment not in ("center", "left", "right"):
        raise HTTPException(status_code=400, detail=f"Unknown alignment: {alignment}")
    if position not in ("bottom", "top"):
        raise HTTPException(status_code=400, detail=f"Unknown position: {position}")

    resolved = _resolve_font_path(font, engine=engine)

    if engine == "imagemagick":
        magick = _detect_imagemagick()
        if not magick:
            raise HTTPException(
                status_code=503,
                detail="ImageMagick 未安装。请安装 ImageMagick 后重试，或使用 engine=pil。\n"
                       "下载地址: https://imagemagick.org/script/download.php",
            )
        img_bytes = _render_subtitle_imagemagick(
            magick=magick, font=resolved, font_size=font_size,
            font_color=font_color, stroke_color=stroke_color,
            stroke_width=stroke_width, bg_color=bg_color,
            text_zh=text_zh, text_en=text_en,
            alignment=alignment, position=position,
            max_lines=max_lines, font_size_factor=font_size_factor,
            max_font_size=max_font_size, caption_width_ratio=caption_width_ratio,
        )
    else:
        if not Path(resolved).is_file():
            raise HTTPException(
                status_code=400,
                detail=f"PIL 引擎需要字体文件路径，但字体不存在: {resolved}。"
                       "系统字体名仅支持 ImageMagick 引擎，或请将字体文件放入 models/font/ 目录。",
            )
        try:
            img_bytes = _render_subtitle_pil(
                font_path=resolved, font_size=font_size,
                font_color=font_color, stroke_color=stroke_color,
                stroke_width=stroke_width, bg_color=bg_color,
                text_zh=text_zh, text_en=text_en,
                alignment=alignment, position=position,
                max_lines=max_lines, font_size_factor=font_size_factor,
                max_font_size=max_font_size, caption_width_ratio=caption_width_ratio,
                font_size_mode=font_size_mode,
            )
        except Exception as e:
            logger.error("PIL render failed: %s", e)
            raise HTTPException(status_code=500, detail=f"PIL 渲染失败: {e}")

    return RawResponse(content=img_bytes, media_type="image/png")


# ---------------------------------------------------------------------------
# File browser
# ---------------------------------------------------------------------------

@app.get("/api/files/drives")
async def list_drives() -> dict:
    """Return available drives and quick-access locations."""
    drives: list[dict] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.exists(root):
            drives.append({"name": f"本地磁盘 ({letter}:)", "path": root})

    home = str(Path.home())
    quick_access = [
        {"label": "桌面", "path": os.path.join(home, "Desktop")},
        {"label": "下载", "path": os.path.join(home, "Downloads")},
        {"label": "视频", "path": os.path.join(home, "Videos")},
        {"label": "文档", "path": os.path.join(home, "Documents")},
    ]

    return {"drives": drives, "quickAccess": quick_access}


@app.post("/api/files/open-folder")
async def open_folder(video_path: str = "") -> dict:
    """Open workspace dir if exists, otherwise open video's parent dir."""
    if not video_path:
        raise HTTPException(status_code=400, detail="Missing video_path")
    target = os.path.dirname(video_path)
    name = os.path.splitext(os.path.basename(video_path))[0]
    ws = os.path.join(target, f"{name}_project")
    folder = ws if os.path.isdir(ws) else target
    if not os.path.isdir(folder):
        raise HTTPException(status_code=404, detail=f"Directory not found: {folder}")
    os.startfile(folder)
    return {"ok": True, "opened": folder}


@app.post("/api/files/open-path")
async def open_path(body: dict) -> dict:
    """在 Windows 资源管理器中打开指定路径（文件或目录）。"""
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="Missing path")
    full = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
    if not os.path.exists(full):
        raise HTTPException(status_code=404, detail=f"Path not found: {full}")
    os.startfile(full)
    return {"ok": True, "opened": full}


@app.get("/api/files/browse")
async def browse_files(path: str = "") -> dict:
    """List directory contents for the file picker."""
    if not path:
        path = str(PROJECT_ROOT)

    target = Path(path)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    entries: list[dict] = []
    try:
        for item in sorted(target.iterdir()):
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {
        "current": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": entries,
    }


@app.get("/api/files/find")
async def find_file(name: str = "", size: int = 0) -> dict:
    """Find a video file by name+size in known directories. Returns path if found."""
    if not name:
        raise HTTPException(status_code=400, detail="Missing file name")

    search_dirs = []
    sd = PROJECT_ROOT / "source_file"
    if sd.is_dir():
        search_dirs.append(sd)
    search_dirs.append(PROJECT_ROOT)

    # Also search common user directories
    home = Path.home()
    for d in ["Desktop", "Downloads", "Videos", "Documents"]:
        p = home / d
        if p.is_dir():
            search_dirs.append(p)

    for base in search_dirs:
        for item in base.rglob(name):
            if item.is_file() and (size == 0 or item.stat().st_size == size):
                return {"path": str(item), "name": item.name, "size": item.stat().st_size}

    raise HTTPException(status_code=404, detail=f"File not found: {name}")


@app.get("/api/files/video")
async def serve_video(path: str):
    """Stream a local video file for browser playback.

    Browsers cannot access local filesystem paths directly.
    This endpoint proxies the file so the video player can seek.
    """
    video_path = Path(path)
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail=f"Video not found: {path}")
    return FileResponse(video_path, media_type="video/mp4")


@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    """Upload a dropped file to source_file/, return server-side path."""
    SOURCE_DIR = PROJECT_ROOT / "source_file"
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    original_name = Path(file.filename).name
    dest = SOURCE_DIR / original_name

    counter = 1
    stem, suffix = dest.stem, dest.suffix
    while dest.exists():
        dest = SOURCE_DIR / f"{stem} ({counter}){suffix}"
        counter += 1

    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    return {
        "path": str(dest),
        "name": dest.name,
        "size": dest.stat().st_size,
    }


@app.get("/api/files/search-videos")
async def search_videos_recursive(path: str = "") -> dict:
    """Recursively find all video files under a directory."""
    if not path:
        path = str(PROJECT_ROOT)

    target = Path(path)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}
    videos: list[dict] = []
    try:
        for item in sorted(target.rglob("*")):
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                # 排除 _project 工作目录内的合成视频
                if any(p.endswith("_project") for p in item.parts):
                    continue
                videos.append({
                    "name": item.name,
                    "path": str(item),
                    "is_dir": False,
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {
        "current": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": [],
        "videos": videos,
    }


class SpeakerLoadRequest(BaseModel):
    workspace: str = ""


def _tl_has_empty_timeline(tl_path: str) -> bool:
    """Check if timeline.json is missing or has an empty events array."""
    if not os.path.isfile(tl_path):
        return True
    tl = _load_timeline_v2(tl_path)  # v1/损坏 → 显式 raise (禁止静默兜底)
    return len(tl.get("events", [])) == 0


def _load_timeline_v2(path: str) -> dict:
    """统一读 v2 timeline.json (唯一事实源)。

    仅接受 v2 格式 ({ schema_version: "2.0", events, speakers, metadata })。
    v1 旧格式必须先用 tools/normalize_v1_timeline.py 一次性迁移 —
    架构收束后运行时不再做静默迁移 (禁止兜底)。
    """
    import json as _json
    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)

    if data.get("schema_version") != "2.0":
        raise ValueError(
            f"timeline.json 不是 v2 格式 (schema_version={data.get('schema_version')!r})。"
            "旧 v1 工作区请先运行一次性迁移: "
            "python tools/normalize_v1_timeline.py --root <workspace 所在目录>"
        )
    return data


def _assign_speakers_by_time_overlap(segments, extract_dir):
    """按时间重叠将 speaker_timeline.json 的说话人分配到 transcript segments。"""
    import json as _json, os as _os
    stl_path = _os.path.join(extract_dir, "speaker_timeline.json")
    if not _os.path.isfile(stl_path):
        return
    try:
        with open(stl_path, "r", encoding="utf-8") as f:
            stl = _json.load(f)
    except Exception:
        return
    turns = stl.get("turns", stl.get("timeline", []))
    if not turns:
        return
    normalized = []
    for t in turns:
        spk = t.get("speaker", t.get("speaker_id", t[0] if isinstance(t, (list, tuple)) else ""))
        s = float(t.get("start", t[1] if isinstance(t, (list, tuple)) else 0))
        e = float(t.get("end", t[2] if isinstance(t, (list, tuple)) else 0))
        if spk and s < e:
            normalized.append((spk, s, e))
    if not normalized:
        return
    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        best_spk, best_overlap = None, 0.0
        for spk, ts, te in normalized:
            overlap = min(seg_end, te) - max(seg_start, ts)
            if overlap > best_overlap:
                best_overlap, best_spk = overlap, spk
        if best_spk and best_overlap > 0:
            seg["speaker"] = best_spk


# ── Canonical event serialization (Phase 3c: 后端 event builder 收敛) ──

def _norm_translation_text(raw) -> str:
    """translation (dict | string) → 纯文本。v3 统一 dict 后, 前端视图要 text。"""
    if isinstance(raw, dict):
        return raw.get("text", "") or ""
    return str(raw) if raw else ""


def _norm_overlap_flag(raw) -> bool:
    """overlap (bool | {overlap_duration}) → bool。"""
    if isinstance(raw, dict):
        return (raw.get("overlap_duration", 0) or 0) > 0
    return bool(raw)


def _canonical_segment(evt: dict, words_fallback: dict | None = None) -> dict:
    """统一的核心 segment 序列化 — speaker_lanes 与 inspector 的共享基础。

    取代 _build_inspector_from_transcript 与 speaker_load 的内联重复构建。
    words 缺失时可从 transcript 按 (start, end) 时间匹配补全 (words_fallback)。
    """
    words = evt.get("words") or []
    if not words and words_fallback:
        key = (round(evt.get("start", 0), 2), round(evt.get("end", 0), 2))
        words = words_fallback.get(key) or []
    seg_id = evt.get("id", "")
    return {
        "id": seg_id,
        "eventId": seg_id,
        "start": evt.get("start", 0),
        "end": evt.get("end", 0),
        "text": evt.get("text", ""),
        "translation": _norm_translation_text(evt.get("translation", "")),
        "overlap": _norm_overlap_flag(evt.get("overlap")),
        "words": words,
    }


def _segment_to_inspector(seg: dict, lane: dict, pass_trace: list) -> dict:
    """canonical segment → inspector_data 项 (加 speaker 上下文 + UI 状态)。"""
    return {
        "id": seg["id"], "start": seg["start"], "end": seg["end"],
        "speaker": lane["speaker"], "displayName": lane["display_name"],
        "color": lane.get("color", ""),
        "text": seg["text"], "translation": seg["translation"],
        "source": "asr", "confidence": 1.0,
        "words": seg.get("words", []),
        "patches": [], "passTrace": pass_trace,
        "visualState": {
            "hasPatches": False, "hasAiSuggestion": False,
            "isSelected": False, "isMultiSelected": False,
        },
    }


def _build_inspector_from_transcript(result: dict, segments: list,
                                      patch_log_data: list, patches_data: dict) -> None:
    """Build inspector_data and speaker_lanes from transcript.json segments.

    Used as fallback when timeline.json is missing or empty, so the frontend
    still shows ASR segments even if timeline fusion (NODE 3.75) failed.
    核心序列化走 _canonical_segment / _segment_to_inspector (Phase 3c)。
    """
    SPEAKER_COLORS = ["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4"]
    speaker_segments: dict[str, list] = {}
    for i, seg in enumerate(segments):
        spk = seg.get("speaker") or "UNKNOWN"
        if not seg.get("id"):
            seg = {**seg, "id": f"seg_{i+1:03d}"}
        canon = _canonical_segment(seg)
        if spk not in speaker_segments:
            speaker_segments[spk] = []
        speaker_segments[spk].append(canon)

    lanes = []
    for i, (spk, segs) in enumerate(sorted(speaker_segments.items())):
        lanes.append({
            "speaker": spk,
            "display_name": spk,
            "voice_id": "",
            "color": SPEAKER_COLORS[i % len(SPEAKER_COLORS)],
            "segments": segs,
            "segment_count": len(segs),
            "total_duration": round(sum(s["end"] - s["start"] for s in segs), 1),
        })
    result["speaker_lanes"] = lanes

    # Build inspector_data sorted by start time (not speaker-grouped)
    all_segments = []
    for lane in lanes:
        for seg in lane["segments"]:
            all_segments.append((seg["start"], _segment_to_inspector(seg, lane, [])))
    all_segments.sort(key=lambda x: x[0])
    inspector_data = {item["id"]: item for _, item in all_segments}
    result["inspector_data"] = inspector_data


SPEAKER_COLORS = ["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4",
                  "#F44336", "#795548", "#607D8B", "#CDDC39", "#03A9F4", "#FF5722"]


def _build_timeline_views(extract_dir: str) -> dict | None:
    """从 timeline.json 构建 GUI 视图 (唯一事实源) — speaker_load 与 timeline/load 共享。

    返回 {audio_id, version, metadata, lanes, inspector_data, pass_trace,
          speakerNames, ai_patches, patch_log}。timeline.json 缺失/为空 → None
    (调用方决定: timeline/load 响亮 400, speaker_load 走 transcript 兼容路径)。
    """
    import json as _json
    tl_path = os.path.join(extract_dir, "timeline.json")
    if not os.path.isfile(tl_path) or _tl_has_empty_timeline(tl_path):
        return None
    tl = _load_timeline_v2(tl_path)

    # 从 transcript.json 补全 word-level timestamps (timeline.json words 缺失时)
    _tj_words = None
    tj_path = os.path.join(extract_dir, "transcript.json")
    if os.path.isfile(tj_path):
        try:
            with open(tj_path, "r", encoding="utf-8") as f:
                _tj_segments = _json.load(f).get("segments", [])
            _tj_words = {}
            for seg in _tj_segments:
                w = seg.get("words") or []
                if w:
                    key = (round(seg.get("start", 0), 2), round(seg.get("end", 0), 2))
                    _tj_words[key] = w
        except Exception:
            pass

    speakers_v2 = tl.get("speakers", {})
    speaker_segments: dict[str, list] = {}
    for evt in tl.get("events", []):
        spk = evt.get("speaker") or "UNKNOWN"
        speaker_segments.setdefault(spk, []).append(_canonical_segment(evt, _tj_words))

    lanes = []
    for i, (spk, segs) in enumerate(sorted(speaker_segments.items())):
        spk_info = speakers_v2.get(spk, {})
        lanes.append({
            "speaker": spk,
            "display_name": spk_info.get("name") or spk,
            "voice_id": spk_info.get("voice_id", ""),
            "color": spk_info.get("color") or SPEAKER_COLORS[i % len(SPEAKER_COLORS)],
            "segments": segs,
            "segment_count": len(segs),
            "total_duration": round(sum(s["end"] - s["start"] for s in segs), 1),
        })

    # Patch 历史
    patch_log: list = []
    log_path = os.path.join(extract_dir, "timeline_patches.json")
    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            patch_log = _json.load(f)

    # pass_trace (旧词表回显)
    pass_names_seen: set = {p.get("opcode", "") for p in patch_log if p.get("opcode")}
    KNOWN_PASS_ORDER = ["MERGE", "RETAG_SPEAKER", "SET_TRANSLATION", "SPLIT", "ANNOTATE"]
    pass_trace = [pn for pn in KNOWN_PASS_ORDER if pn in pass_names_seen]

    # AI Patch 建议 (失败静默降级为空 — 建议是辅助数据, 非编辑事实)
    ai_patches: dict = {"high": [], "medium": [], "low": []}
    try:
        from timeline.api.timeline import generate_candidate_patches
        ai = generate_candidate_patches(tl_path)
        ai_patches = {"high": ai.get("high", []), "medium": ai.get("medium", []),
                      "low": ai.get("low", [])}
    except Exception:
        pass

    inspector_data: dict = {}
    for lane in lanes:
        for seg in lane["segments"]:
            inspector_data[seg["id"]] = _segment_to_inspector(seg, lane, pass_trace)
    for p in patch_log:
        for tid in p.get("targets", []):
            if tid in inspector_data:
                inspector_data[tid]["visualState"]["hasPatches"] = True
                inspector_data[tid]["patches"].append(p)
    for cat in ("high", "medium"):
        for p in ai_patches.get(cat, []):
            for tid in p.get("targets", []):
                if tid in inspector_data:
                    inspector_data[tid]["visualState"]["hasAiSuggestion"] = True

    return {
        "audio_id": tl.get("project", {}).get("id", ""),
        "version": tl.get("schema_version", "2.0"),
        "metadata": tl.get("metadata", {}),
        "lanes": lanes,
        "inspector_data": inspector_data,
        "pass_trace": pass_trace,
        "speakerNames": {
            sid: (s.get("name") or s.get("label") or sid)
            for sid, s in (tl.get("speakers") or {}).items()
        },
        "ai_patches": ai_patches,
        "patch_log": patch_log,
    }


@app.post("/api/speaker/diarization/load")
async def speaker_load(req: SpeakerLoadRequest):
    """加载 Timeline IR (v2.0 schema) + AI Patch 建议。

    返回 SpeakerLoadResponse (前端接口不变):
      { audio_id, version, speaker_lanes, patches, patch_log, inspector_data, speakerNames }
    """
    workspace = req.workspace
    extract_dir = os.path.join(workspace, "01_extract") if workspace else ""
    if not extract_dir or not os.path.isdir(extract_dir):
        raise HTTPException(status_code=400, detail="无效的工作目录")
    import json as _json

    result = {
        "audio_id": "",
        "version": "2.0",
        "speaker_lanes": [],
        "patches": {"high": [], "medium": [], "low": []},
        "patch_log": [],
        "speakerNames": {},
        "verification": None,
    }

    # Load verification data
    sv_path = os.path.join(extract_dir, "speaker_verification.json")
    if os.path.isfile(sv_path):
        try:
            with open(sv_path, "r", encoding="utf-8") as f:
                sv = _json.load(f)
            result["verification"] = {
                "passesAll": sv.get("passes_all", True),
                "summary": {
                    "totalIssues": sv.get("summary", {}).get("total_issues", 0),
                    "errors": sv.get("summary", {}).get("errors", 0),
                    "warnings": sv.get("summary", {}).get("warnings", 0),
                    "info": sv.get("summary", {}).get("infos", 0),
                    "speakers": sv.get("summary", {}).get("speakers", 0),
                    "turns": sv.get("summary", {}).get("turns", 0),
                },
                "issues": [
                    {"layer": i["layer"], "severity": i["severity"],
                     "message": i["message"], "detail": i.get("detail", {})}
                    for i in sv.get("issues", [])
                ],
            }
        except Exception:
            pass

    tl_path = os.path.join(extract_dir, "timeline.json")
    has_timeline = os.path.isfile(tl_path)
    views = _build_timeline_views(extract_dir) if has_timeline else None

    if not has_timeline:
        stl_path = os.path.join(extract_dir, "speaker_timeline.json")
        if os.path.isfile(stl_path):
            with open(stl_path, "r", encoding="utf-8") as f:
                stl = _json.load(f)
            result["timeline"] = stl.get("turns", [])
            result["speakers"] = stl.get("speakers", [])

    if views is None:
        # timeline.json 缺失/空 — transcript fallback (兼容旧工作区)
        tj_path = os.path.join(extract_dir, "transcript.json")
        if os.path.isfile(tj_path):
            logger.info("speaker_load: timeline.json missing/empty, falling back to transcript.json")
            with open(tj_path, "r", encoding="utf-8") as f:
                tj = _json.load(f)
            segments = tj.get("segments", [])
            if segments:
                # 用 speaker_timeline.json 按时间重叠分配说话人
                _assign_speakers_by_time_overlap(segments, extract_dir)
                _build_inspector_from_transcript(result, segments, result.get("patch_log", []),
                                                  result.get("patches", {}))
                return result
        if not has_timeline:
            return result
        return result

    result["audio_id"] = views["audio_id"]
    result["version"] = views["version"]
    result["metadata"] = views["metadata"]
    result["speaker_lanes"] = views["lanes"]
    result["pass_trace"] = views["pass_trace"]
    result["inspector_data"] = views["inspector_data"]
    result["speakerNames"] = views["speakerNames"]
    result["patches"] = views["ai_patches"]
    result["patch_log"] = views["patch_log"]

    return result


@app.get("/api/speaker/diarization/waveform")
async def speaker_waveform(workspace: str = ""):
    """返回 vocals.wav 的波形峰值数据 (供 Canvas 渲染)"""
    import numpy as np
    import wave as _wave
    extract_dir = os.path.join(workspace, "01_extract")
    wav_path = os.path.join(extract_dir, "vocals.wav")
    if not os.path.isfile(wav_path):
        wav_path = os.path.join(extract_dir, "audio.wav")
    if not os.path.isfile(wav_path):
        # core/ bootstrap 的命名: {stem}_extracted.wav
        import glob as _glob
        matches = _glob.glob(os.path.join(extract_dir, "*_extracted.wav"))
        wav_path = matches[0] if matches else wav_path
    if not os.path.isfile(wav_path):
        raise HTTPException(status_code=404, detail="音频文件不存在")

    with _wave.open(wav_path, "rb") as wf:
        n_frames = wf.getnframes()
        sample_rate = wf.getframerate()
        raw = wf.readframes(n_frames)
        dtype = np.int16 if wf.getsampwidth() == 2 else np.int32
        samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        if wf.getnchannels() > 1:
            samples = samples.reshape(-1, wf.getnchannels()).mean(axis=1)

    window = max(1, int(sample_rate / 100))
    peaks_list = []
    for i in range(0, len(samples) - window, window):
        chunk_max = float(np.max(np.abs(samples[i:i + window])))
        peaks_list.append(chunk_max)

    max_peak = max(peaks_list) if peaks_list else 1.0
    if max_peak > 0:
        peaks_list = [p / max_peak for p in peaks_list]

    return {"peaks": peaks_list, "duration": n_frames / sample_rate, "sampleRate": sample_rate}


# ---------------------------------------------------------------------------
# Speaker Merge / Split / Rename API (M4)
# ---------------------------------------------------------------------------

class SpeakerRegenerateRequest(BaseModel):
    workspace: str = ""


class ScreeningRequest(BaseModel):
    workspace: str = ""
    include_cross_model: bool = True  # 是否启用交叉嵌入验证（需加载 WeSpeaker）


@app.post("/api/speaker/screening/run")
async def speaker_screening_run(req: ScreeningRequest):
    """运行说话人筛查 — 纯信号规则 + 交叉嵌入验证。

    返回: { screening: {...}, cross_model: {...} | null }
    """
    workspace = req.workspace
    extract_dir = os.path.join(workspace, "01_extract") if workspace else ""
    if not extract_dir or not os.path.isdir(extract_dir):
        raise HTTPException(status_code=400, detail="无效的工作目录")

    import json as _json

    # 加载 speaker_timeline.json
    tl_path = os.path.join(extract_dir, "speaker_timeline.json")
    timeline: list[dict] = []
    if os.path.isfile(tl_path):
        with open(tl_path, "r", encoding="utf-8") as f:
            tl = _json.load(f)
        for t in tl.get("turns", []):
            seg_id = t.get("id", f"{t.get('speaker','?')}_{t.get('start',0)}")
            timeline.append({
                "id": seg_id,
                "speaker": t.get("speaker", "?"),
                "start": t.get("start", 0),
                "end": t.get("end", 0),
            })

    if not timeline:
        return {"screening": {"total_issues": 0, "critical_count": 0, "warning_count": 0, "issues": []},
                "cross_model": None}

    # 查找 vocals.wav
    vocals_path = os.path.join(extract_dir, "vocals.wav")
    if not os.path.isfile(vocals_path):
        vocals_path = os.path.join(extract_dir, "audio.wav")  # fallback
    if not os.path.isfile(vocals_path):
        vocals_path = ""

    # 方案 B: 纯信号规则
    from core.speaker.screening import ScreeningLayer, screening_report
    screener = ScreeningLayer()
    issues = screener.screen(timeline, vocals_path if os.path.isfile(vocals_path) else None)
    screening = screening_report(issues)

    # 方案 A: 交叉嵌入验证
    cross_model = None
    if req.include_cross_model and os.path.isfile(vocals_path):
        try:
            from core.speaker.cross_model import CrossModelVerifier, cross_model_report
            verifier = CrossModelVerifier()
            divergences = verifier.verify(timeline, vocals_path)
            cross_model = cross_model_report(divergences)
        except Exception:
            cross_model = None

    return {"screening": screening, "cross_model": cross_model}


@app.post("/api/speaker/diarization/continue-dub")
async def speaker_continue_dub(req: SpeakerRegenerateRequest):
    """说话人校验完成后继续配音 — 启动 TRANSLATE → TTS → EXPORT 管线。"""
    workspace = req.workspace
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace 不能为空")

    # 从 project.json 读取 video_path
    manifest_path = os.path.join(workspace, "project.json")
    if not os.path.isfile(manifest_path):
        raise HTTPException(status_code=404, detail="project.json 不存在")
    import json as _json
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = _json.load(f)
    video_path = manifest.get("video_path", "")
    if not video_path or not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail="video_path 无效")

    job_id = uuid.uuid4().hex[:8]
    job = Job(
        id=job_id,
        status="running",
        runtime_state="dubbing",
        current_step="说话人校验完成，开始配音...",
        video_path=video_path,
        workspace_path=workspace,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _jobs[job_id] = job
    job._loop = asyncio.get_running_loop()
    _save_job(job)

    # 构建 CoreRunRequest 的等价物用于 _run_core_pipeline_sync
    class DubRequest:
        video_path = video_path
        workflow_preset = "dub_multi"
        lang = manifest.get("lang", "auto")
        target_lang = manifest.get("target_lang", "zh")
        engine = "chattts"
        export_stage = False

    req_wrapper = DubRequest()
    asyncio.create_task(_run_core_job_with_flags(job, req_wrapper, dub_after_review=True))

    return {"job_id": job_id, "status": "started"}


async def _run_core_job_with_flags(job: Job, req, **flags) -> None:
    """在线程池中运行 core/ Pipeline（支持额外 tvw 参数）。"""
    await asyncio.to_thread(_run_core_pipeline_sync, job, req, flags)


class PatchApplyRequest(BaseModel):
    workspace: str = ""
    patch: dict = {}


class PatchUndoRequest(BaseModel):
    workspace: str = ""


# ── Phase 4: 编辑写路径统一走 core PatchEngine + timeline_io ─────────

def _edit_paths(workspace: str):
    """校验 workspace 并返回 (extract_dir, tl_path, log_path)。"""
    extract_dir = os.path.join(workspace, "01_extract") if workspace else ""
    if not extract_dir or not os.path.isdir(extract_dir):
        raise HTTPException(status_code=400, detail="无效的工作目录")
    tl_path = os.path.join(extract_dir, "timeline.json")
    if not os.path.isfile(tl_path):
        raise HTTPException(status_code=404, detail="timeline.json 不存在")
    return extract_dir, tl_path, os.path.join(extract_dir, "timeline_patches.json")


def _project_meta(extract_dir: str) -> tuple[str, str, str]:
    """从磁盘 timeline.json 读 project 元数据 (persist 需要)。"""
    with open(os.path.join(extract_dir, "timeline.json"), "r", encoding="utf-8") as f:
        proj = (json.load(f) or {}).get("project", {})
    return (proj.get("source_video", ""), proj.get("source_lang", ""),
            proj.get("id", ""))


def _persist_edited(state, extract_dir: str) -> None:
    """编辑后持久化 — 唯一写路径 (timeline_io.persist_state)。

    persist_state 的 ws_dir 参数是 workspace 根目录 (内部拼 01_extract/timeline.json)。
    """
    from core.runtime.timeline_io import persist_state
    video, lang, pid = _project_meta(extract_dir)
    persist_state(state, os.path.dirname(extract_dir), video, lang, pid)


def _inspector_from_state(state) -> dict:
    """从内存 state 构建事件 inspector 视图 (apply/undo 响应局部刷新, 零 IO)。

    与 _build_timeline_views 的 inspector 结构一致; pass_trace 空 (局部刷新
    不重算), hasPatches 由前端本地 appliedPatches 维护。
    """
    lanes_cache: dict[str, dict] = {}
    out: dict = {}
    for es in state.sorted_events():
        spk = es.ir.speaker_ref or "UNKNOWN"
        if spk not in lanes_cache:
            node = state.ir.speakers.get(spk)
            lanes_cache[spk] = {
                "speaker": spk,
                "display_name": (node.name if node else None) or spk,
                "voice_id": (node.voice_id if node else "") or "",
                "color": (node.color if node else "") or SPEAKER_COLORS[len(lanes_cache) % len(SPEAKER_COLORS)],
            }
        seg = _canonical_segment({
            "id": es.id,
            "start": es.start,
            "end": es.end,
            "text": es.ir.text_ref or "",
            "translation": es.translation.text if es.translation else "",
            "words": list(es.asr.words or []),
        })
        out[es.id] = _segment_to_inspector(seg, lanes_cache[spk], [])
    return out


def _apply_edit_patch(workspace: str, patch) -> dict:
    """统一编辑写路径: load_state → PatchEngine.apply → 链落盘 → persist。"""
    from core.runtime.patch_engine import PatchEngine
    from core.runtime.timeline_io import load_state
    from GUI.patch_adapter import load_chain, save_chain

    extract_dir, tl_path, log_path = _edit_paths(workspace)
    state = load_state(tl_path)
    result = PatchEngine().apply(state, patch)
    if result.get("status") != "applied":
        raise HTTPException(status_code=422, detail=str(result))
    bak_path = tl_path + ".bak"
    chain = load_chain(log_path)
    if not chain and not os.path.isfile(bak_path):
        import shutil
        shutil.copy2(tl_path, bak_path)
    chain.append(patch)
    save_chain(chain, log_path)
    _persist_edited(state, extract_dir)
    # P3-D: 局部刷新 — 返回应用后的事件快照, 前端不再全量 loadWorkspace
    return {**result, "events": _inspector_from_state(state)}


class TimelineLoadRequest(BaseModel):
    workspace: str = ""


@app.post("/api/timeline/load")
async def timeline_load(req: TimelineLoadRequest):
    """加载事件视图 — timeline.json 是唯一事实源 (P3-C: 主数据源从 speaker 端点迁移)。

    返回 {inspector_data, pass_trace}。timeline.json 缺失/为空 → 显式 400
    (不降级 transcript — 那是 diarization/load 的兼容路径, timeline 读路径不假装)。
    """
    workspace = req.workspace
    extract_dir = os.path.join(workspace, "01_extract") if workspace else ""
    if not extract_dir or not os.path.isdir(extract_dir):
        raise HTTPException(status_code=400, detail="无效的工作目录")
    views = _build_timeline_views(extract_dir)
    if views is None:
        raise HTTPException(
            status_code=400,
            detail="该项目尚未运行流水线，无时间轴数据 — 请返回项目中心选择视频与预设启动 Bootstrap",
        )
    return {"inspector_data": views["inspector_data"], "pass_trace": views["pass_trace"]}


@app.post("/api/timeline/patch/apply")
async def timeline_patch_apply(req: PatchApplyRequest):
    """应用一个 patch — Phase 4: 统一走 PatchEngine + timeline_io。

    旧前端契约 (patchDraftToApiFormat 旧词表) 经 patch_adapter.legacy_to_core 映射。
    """
    from GUI.patch_adapter import legacy_to_core, UnsupportedPatchError

    try:
        patch = legacy_to_core(req.patch)
    except UnsupportedPatchError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result = _apply_edit_patch(req.workspace, patch)
    return {"status": "applied", "patch_id": patch.id,
            "diff": result, "events": result.get("events", {})}


@app.post("/api/timeline/patch/undo")
async def timeline_patch_undo(req: PatchUndoRequest):
    """回滚最近一个 patch — Phase 4: pristine + PatchEngine 重放链。

    修复旧系统静默 no-op (bak 缺失时用当前副本当源重放, 结果不变但返回 undone):
    无 pristine 源显式报错 (禁止兜底)。
    """
    from core.runtime.patch_engine import PatchEngine
    from core.runtime.timeline_io import load_state
    from GUI.patch_adapter import load_chain, save_chain

    extract_dir, tl_path, log_path = _edit_paths(req.workspace)
    chain = load_chain(log_path)
    if not chain:
        return {"status": "no_patches"}

    bak_path = tl_path + ".bak"
    if not os.path.isfile(bak_path):
        raise HTTPException(
            status_code=409,
            detail="undo 需要 pristine 备份 (timeline.json.bak), 但备份缺失且补丁链非空。"
                   "请手动恢复备份或清除补丁链。")

    state = load_state(bak_path)
    engine = PatchEngine()
    removed = chain.pop()
    for p in chain:
        r = engine.apply(state, p)
        if r.get("status") != "applied":
            raise HTTPException(
                status_code=500,
                detail=f"undo 重放失败 (patch {p.id}): {r.get('reason')}")
    _persist_edited(state, extract_dir)
    save_chain(chain, log_path)
    if not chain and os.path.isfile(bak_path):
        os.remove(bak_path)
    # P3-D: 局部刷新 — 回滚后事件快照
    return {"status": "undone", "patch_id": removed.id,
            "events": _inspector_from_state(state)}


@app.get("/api/timeline/patch/log")
async def timeline_patch_log(workspace: str = ""):
    """获取 patch 历史记录 — Phase 4: 链读取 (新旧格式混合归一)。"""
    from GUI.patch_adapter import load_chain, core_to_legacy
    extract_dir = os.path.join(workspace, "01_extract") if workspace else ""
    log_path = os.path.join(extract_dir, "timeline_patches.json")
    if not os.path.isfile(log_path):
        return {"patches": [], "count": 0}
    patches = [core_to_legacy(p) for p in load_chain(log_path)]
    return {"patches": patches, "count": len(patches)}


# ── T4.2 Patch Debug — Git-log style patch history ──────────────

@app.get("/api/timeline/review/flags")
async def timeline_review_flags(workspace: str = ""):
    """Review 面板 — 自动标记低置信度/冲突/异常 segment (T4.3)。"""
    tl_path = os.path.join(workspace, "01_extract", "timeline.json") if workspace else ""
    flags: list[dict] = []
    if not tl_path or not os.path.isfile(tl_path):
        return {"flags": [], "summary": {"low_confidence": 0, "speaker_conflict": 0, "emotion_jump": 0, "length_exceeded": 0}}

    try:
        with open(tl_path, "r", encoding="utf-8") as f:
            tl = json.load(f)
    except Exception:
        return {"flags": [], "summary": {"low_confidence": 0, "speaker_conflict": 0, "emotion_jump": 0, "length_exceeded": 0}}

    events = tl.get("events", [])
    prev_emotion = None
    prev_speaker = None
    summary = {"low_confidence": 0, "speaker_conflict": 0, "emotion_jump": 0, "length_exceeded": 0}

    for evt in events:
        eid = evt.get("id", "")
        flag_types = []
        reason = ""

        # low confidence
        if evt.get("confidence", 1.0) < 0.7:
            flag_types.append("low_confidence")
            reason += "置信度低; "
            summary["low_confidence"] += 1

        # speaker conflict / change
        speaker = evt.get("speaker")
        if prev_speaker and speaker and speaker != prev_speaker:
            sid = evt.get("start", 0)
            if any(e.get("start", 0) < sid and e.get("end", 0) > sid and e.get("speaker") != speaker for e in events):
                flag_types.append("speaker_conflict")
                reason += "说话人冲突; "
                summary["speaker_conflict"] += 1
        prev_speaker = speaker

        # emotion jump
        emotion = evt.get("emotion")
        if emotion and prev_emotion and emotion != prev_emotion:
            flag_types.append("emotion_jump")
            reason += "情绪跳变; "
            summary["emotion_jump"] += 1
        prev_emotion = emotion

        # text length exceeds typical reading speed
        text = evt.get("text", "")
        translation = evt.get("translation", "")
        if isinstance(translation, dict):
            translation = translation.get("text", "") or ""
        dur = evt.get("end", 0) - evt.get("start", 0)
        chars = len(text + translation)
        if dur > 0 and chars / dur > 20:
            flag_types.append("length_exceeded")
            reason += "字幕过长; "
            summary["length_exceeded"] += 1

        if flag_types:
            flags.append({"event_id": eid, "flags": flag_types, "reason": reason.rstrip("; "),
                          "start": evt.get("start", 0), "end": evt.get("end", 0),
                          "text": text[:60], "translation": translation[:60] if isinstance(translation, str) else ""})

    return {"flags": flags, "summary": summary}


# ── AI Suggestion API ─────────────────────────────────────────────

class AiSuggestRequest(BaseModel):
    event_id: str = ""
    workspace: str = ""
    source_text: str = ""
    current_translation: str = ""
    target_lang: str = "zh"


class AiSuggestResponse(BaseModel):
    suggestion: str
    reasoning: str = ""
    diff: dict = {}


@app.post("/api/timeline/ai/suggest")
async def timeline_ai_suggest(req: AiSuggestRequest):
    """Generate AI improvement suggestion for a translated segment."""
    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="source_text is empty")
    if not req.current_translation.strip():
        raise HTTPException(status_code=400, detail="current_translation is empty")

    settings = load_settings()
    pipeline_cfg = settings.get("pipeline", {})
    api_type = pipeline_cfg.get("apiType") or pipeline_cfg.get("api_type") or "deepseek"
    api_key = pipeline_cfg.get("apiKey") or pipeline_cfg.get("api_key") or ""
    api_base = pipeline_cfg.get("apiBaseUrl") or pipeline_cfg.get("api_base_url") or ""
    api_model = pipeline_cfg.get("apiModel") or pipeline_cfg.get("api_model") or "deepseek-chat"

    if not api_key:
        raise HTTPException(status_code=400, detail="API key not configured. Please set it in Settings → API Config.")

    provider_base_urls = {
        "deepseek": "https://api.deepseek.com",
        "kimi": "https://api.moonshot.ai/v1",
        "xiaomi": "https://api.xiaomimimo.com/v1",
    }
    base_url = api_base or provider_base_urls.get(api_type, "https://api.deepseek.com")
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    system_prompt = (
        "You are an expert translation reviewer. Given a source text and its current translation, "
        "suggest an improved translation that is more natural, fluent, and accurate. "
        "Provide your response in JSON format with three fields: "
        '"suggestion" (the improved translation text), '
        '"reasoning" (brief explanation of what was improved), '
        '"diff" (object with "before" and "after" keys). '
        "Only return valid JSON, no other text."
    )
    user_prompt = (
        f"Source text: {req.source_text}\n"
        f"Current translation: {req.current_translation}\n"
        f"Target language: {req.target_lang}\n\n"
        f"Please suggest an improved translation."
    )

    try:
        import requests
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": api_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        return AiSuggestResponse(
            suggestion=result.get("suggestion", ""),
            reasoning=result.get("reasoning", ""),
            diff=result.get("diff", {"before": req.current_translation, "after": result.get("suggestion", "")}),
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {str(e)}")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse LLM response: {str(e)}")


# ── Config Parameter API (v3.0 — 定稿 §11.2) ─────────────────────────────────

class ConfigApplyRequest(BaseModel):
    workspace: str = ""
    event_id: str = ""
    slot: str = "tts"
    field: str = ""
    value: object = None
    op: str = "override"  # "override" | "set" | "reset"

@app.post("/api/timeline/config/apply")
async def timeline_config_apply(req: ConfigApplyRequest):
    """Apply a config override to a single event."""
    try:
        from core.runtime.patch_factory import make_override_config, make_set_config, make_reset_config
        from core.runtime.patch_engine import PatchEngine
        from core.runtime.project_state import TimelineProjectState

        if req.op == "override":
            patch = make_override_config(req.event_id, req.slot, req.field, req.value)
        elif req.op == "set":
            patch = make_set_config(req.event_id, req.slot, req.config_block if hasattr(req, 'config_block') else {req.field: req.value})
        elif req.op == "reset":
            patch = make_reset_config(req.event_id, req.slot, [req.field] if req.field else None)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown op: {req.op}")

        # Persist patch to workspace patch log
        _persist_config_patch(req.workspace, {
            "id": patch.id,
            "op": patch.op.value,
            "target_id": patch.target_id,
            "value": patch.value,
            "timestamp": patch.timestamp,
            "author": patch.author,
        })

        return {
            "status": "patch_created",
            "patch": {
                "id": patch.id,
                "op": patch.op.value,
                "target_id": patch.target_id,
                "value": patch.value,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/timeline/config/resolve")
async def timeline_config_resolve(event_id: str, slot: str, workspace: str = ""):
    """Resolve the effective config for an event slot (Event > Speaker > Global).

    Reads global defaults from GlobalConfig, then merges speaker-level and
    event-level overrides from the workspace patch log.
    """
    try:
        from core.runtime.config_resolver import ConfigResolver, deep_merge
        from core.config.global_config import GlobalConfig

        gc = GlobalConfig()
        resolved = gc.get_slot_defaults(slot)
        inherited = "global"

        if workspace and event_id:
            # Layer 2: speaker-level overrides (from timeline.json speaker configs)
            speaker_config = _load_speaker_config_for_event(workspace, event_id, slot)
            if speaker_config:
                deep_merge(resolved, speaker_config)
                inherited = "speaker"

            # Layer 3: event-level overrides (from timeline_patches.json)
            event_overrides = _load_config_overrides(workspace, event_id)
            if slot in event_overrides:
                deep_merge(resolved, event_overrides[slot])
                inherited = "event"

            # Collect list of overridden fields for UI display
            overrides_list = list(event_overrides.get(slot, {}).keys()) if slot in event_overrides else []

            return {
                "event_id": event_id,
                "slot": slot,
                "resolved": resolved,
                "inherited_from": inherited,
                "overrides": overrides_list,
            }

        return {
            "event_id": event_id,
            "slot": slot,
            "resolved": resolved,
            "inherited_from": inherited,
            "overrides": [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _load_speaker_config_for_event(workspace: str, event_id: str, slot: str) -> dict:
    """Load speaker-level config for an event from timeline.json."""
    import json as _json
    tl_path = Path(workspace) / "01_extract" / "timeline.json"
    if not tl_path.is_file():
        return {}
    try:
        with open(tl_path, "r", encoding="utf-8") as f:
            tl = _json.load(f)
    except Exception:
        return {}

    # Find the event to get its speaker
    speaker_id = None
    for seg in tl.get("timeline", []):
        if seg.get("id") == event_id:
            speaker_id = seg.get("speaker", "")
            break

    if not speaker_id:
        return {}

    # Look up speaker config
    for spk in tl.get("speakers", []):
        if spk.get("id") == speaker_id or spk.get("speaker") == speaker_id:
            return spk.get("config", {}).get(slot, {})

    return {}

@app.get("/api/speaker/audio/preview")
async def speaker_audio_preview(path: str = "", start: float = 0, end: float = 0):
    """返回指定时间范围的音频 base64（用于前端试听）。"""
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=400, detail="音频文件不存在")
    dur = end - start
    if dur <= 0 or dur > 10:
        raise HTTPException(status_code=400, detail="时间范围应在 0-10s 之间")
    import base64, subprocess
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-t", str(dur),
         "-i", path, "-f", "wav", "-"],
        capture_output=True, timeout=15,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail="ffmpeg 提取失败")
    return {"audio_base64": base64.b64encode(proc.stdout).decode("ascii"), "format": "wav"}


@app.get("/api/speaker/diarization/overlaps")
async def speaker_overlaps(workspace: str = ""):
    """返回重叠说话区域 (调用 speaker_fusion.detect_overlaps)"""
    import json as _json
    extract_dir = os.path.join(workspace, "01_extract")
    stl_path = os.path.join(extract_dir, "speaker_timeline.json")
    if not os.path.isfile(stl_path):
        return {"overlaps": [], "strategy": "mark_for_review"}
    with open(stl_path, "r", encoding="utf-8") as f:
        stl = _json.load(f)
    timeline = [(t["speaker"], t["start"], t["end"], t.get("confidence", 1.0))
                for t in stl.get("turns", [])]
    from pipeline.speaker_fusion import detect_overlaps
    return {"overlaps": detect_overlaps(timeline), "strategy": "mark_for_review"}


@app.get("/api/workflow/presets")
async def list_workflow_presets() -> dict:
    """Return all available Workflow Presets (Pass DAG templates)."""
    return {"presets": get_presets()}


class WorkspaceCreateRequest(BaseModel):
    video_path: str
    name: str = ""
    workflow_preset: str = "quick_sub_single"
    lang: str = ""
    target_lang: str = ""


@app.post("/api/workspace/create")
async def create_workspace(req: WorkspaceCreateRequest) -> dict:
    """Create a workspace directory and initialize project.json.

    This is the first step in the Timeline Runtime lifecycle.
    Does NOT start pipeline processing — that's a separate call.
    """
    video_path = Path(req.video_path)
    if not video_path.is_file():
        raise HTTPException(status_code=400, detail=f"Video not found: {req.video_path}")

    # Derive workspace path: {video_dir}/{name}_project/
    name = req.name or video_path.stem
    workspace_dir = video_path.parent / f"{name}_project"

    # Lookup preset for defaults
    preset = get_preset(req.workflow_preset)
    passes = preset.passes if preset else []

    # Create directory structure
    for sub in ["01_extract", "02_translate", "03_speaker", "04_patch", "05_tts", "06_export"]:
        (workspace_dir / sub).mkdir(parents=True, exist_ok=True)

    # Write initial project.json
    manifest = {
        "version": 1,
        "name": name,
        "video_path": str(video_path),
        "workflow_preset": req.workflow_preset,
        "passes": passes,
        "runtime_state": RuntimeState.UNINITIALIZED.value,
        "lang": req.lang,
        "target_lang": req.target_lang,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": {},
        "files": {},
    }
    manifest_path = workspace_dir / "project.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {
        "workspace": str(workspace_dir),
        "name": name,
        "manifest": manifest,
    }


@app.get("/api/workspaces")
async def list_workspaces() -> dict:
    """Scan source_file/ for *_project directories and return summaries."""
    source_dir = PROJECT_ROOT / "source_file"
    workspaces: list[dict] = []

    if source_dir.is_dir():
        for d in sorted(source_dir.iterdir()):
            if not d.is_dir() or not d.name.endswith("_project"):
                continue
            manifest_path = d / "project.json"
            runtime_state = RuntimeState.UNINITIALIZED.value
            video_path = ""
            if manifest_path.is_file():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        m = json.load(f)
                    runtime_state = m.get("runtime_state", RuntimeState.UNINITIALIZED.value)
                    video_path = m.get("video_path", "")
                except Exception:
                    pass

            # 回退：CLI (tvw.py) 启动的流水线只写 session.json，不写 project.json 的
            # runtime_state。映射 SessionState → RuntimeState，否则 CLI 建的项目卡片点不开。
            if runtime_state == RuntimeState.UNINITIALIZED.value:
                session_path = d / "session.json"
                if session_path.is_file():
                    try:
                        with open(session_path, "r", encoding="utf-8") as f:
                            s = json.load(f)
                        _SESSION_TO_RUNTIME = {
                            "reviewable": RuntimeState.READY.value,
                            "validated": RuntimeState.READY.value,
                            "completed": RuntimeState.COMPLETE.value,
                            "exporting": RuntimeState.COMPUTING.value,
                            "bootstrapping": RuntimeState.BOOTSTRAPPING.value,
                            "failed": RuntimeState.FAILED.value,
                        }
                        runtime_state = _SESSION_TO_RUNTIME.get(
                            s.get("session_state", ""), runtime_state)
                    except Exception:
                        pass

            workspaces.append({
                "path": str(d),
                "name": d.name.replace("_project", ""),
                "updatedAt": datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc).isoformat(),
                "runtimeState": runtime_state,
                "videoPath": video_path,
            })

    return {"workspaces": workspaces}


@app.post("/api/workspace/delete")
async def delete_workspace(body: dict) -> dict:
    """Delete a workspace directory and its contents."""
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="Missing path")
    ws_dir = Path(path)
    if not ws_dir.is_dir() or not ws_dir.name.endswith("_project"):
        raise HTTPException(status_code=400, detail="Not a workspace directory")
    # Cancel any running job for this workspace
    for job_id, job in list(_jobs.items()):
        if getattr(job, "workspace_path", "") == str(ws_dir):
            if job.process and job.process.returncode is None:
                job.process.terminate()
                try:
                    job.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    job.process.kill()
            del _jobs[job_id]
    import shutil
    shutil.rmtree(str(ws_dir), ignore_errors=True)
    return {"ok": True}


class CoreRunRequest(BaseModel):
    video_path: str
    workflow_preset: str = "quick_sub_single"
    lang: str = "auto"
    target_lang: str = "zh"
    engine: str = "chattts"
    skip_tts: bool = False
    skip_demucs: bool = False
    asr_model: str = "turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    num_speakers: int = 0  # 0=自动, >0=指定说话人数
    export_stage: bool = False  # True=仅跑 TTS→EXPORT（需已存在 bootstrap 工作区）


class CoreRunResponse(BaseModel):
    job_id: str
    workspace_path: str = ""
    policy_summary: dict = {}


class CoreStatusResponse(BaseModel):
    job_id: str
    status: str
    orchestrator_status: str = "IDLE"
    current_stage: str = ""
    current_step: str = ""
    progress: int = 0
    stages: dict = {}
    pending_review: list[str] = []
    metrics: dict = {}


def _preset_to_policy(preset_id: str, target_lang: str) -> tuple:
    """将 WorkflowPreset ID 映射为 WorkflowPolicy 实例。(批次11 §阶段C)"""
    preset = get_preset(preset_id)
    preset_passes = preset.passes if preset else []
    skip_tts = preset.config_defaults.get("skip_tts", False) if preset else False

    if preset is not None and preset.policy_fn is not None:
        policy = preset.policy_fn(target_lang)
    else:
        from core.config.workflow_policy import WorkflowPolicy
        if skip_tts:
            policy = WorkflowPolicy.quick_preset(target_lang)
        else:
            policy = WorkflowPolicy.default_preset(target_lang)

    return policy, preset_passes, skip_tts


def _timeline_to_srt(workspace: str) -> str | None:
    """从 workspace 的 timeline.json 导出翻译后的 SRT，供旧 TTS 管线使用。

    优先级: 02_translate/timeline_v2.json > 02_translate/timeline.json > 01_extract/timeline.json
    """
    tl_candidates = [
        os.path.join(workspace, "02_translate", "timeline_v2.json"),
        os.path.join(workspace, "02_translate", "timeline.json"),
        os.path.join(workspace, "01_extract", "timeline.json"),
    ]
    tl_path = None
    for p in tl_candidates:
        if os.path.isfile(p):
            tl_path = p
            break

    if not tl_path:
        logger.warning(f"_timeline_to_srt: no timeline.json found in {workspace}")
        return None

    try:
        with open(tl_path, "r", encoding="utf-8") as f:
            tl = json.load(f)
    except Exception:
        return None

    events = tl if isinstance(tl, list) else tl.get("events", [])
    if not events:
        return None

    out_dir = os.path.join(workspace, "02_translate")
    os.makedirs(out_dir, exist_ok=True)
    srt_path = os.path.join(out_dir, "machine.srt")

    idx = 1
    lines: list[str] = []
    for e in events:
        start = e.get("start", 0)
        end = e.get("end", 0)
        if start >= end:
            continue
        trans = e.get("translation", "")
        if isinstance(trans, dict):
            trans = trans.get("text", "") or ""
        text = str(trans or e.get("text", "")).strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(_to_srt_time(start) + " --> " + _to_srt_time(end))
        lines.append(text)
        lines.append("")
        idx += 1

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"_timeline_to_srt: exported {idx - 1} entries → {srt_path}")
    return srt_path


def _to_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── P2 设置桥: settings.json 差异层 → core GlobalConfig 槽位覆盖 ──────────

# 前端 snake_case 键 → (槽位, 点路径)。路径支持嵌套 (如 "gate.mode")。
_SLOT_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    # audio
    "demucs_model": ("audio", "demucs_model"),
    "skip_demucs": ("audio", "skip_demucs"),
    "loudness_norm": ("audio", "loudness_compensation"),
    "loudness_target_lufs": ("audio", "target_loudness"),
    # asr
    "asr_model": ("asr", "model"),
    "source_lang": ("asr", "language"),
    # speaker
    "max_speakers": ("speaker", "max_speakers"),
    "clustering_threshold": ("speaker", "clustering_threshold"),
    # translation
    "translate_concurrency": ("translation", "concurrency"),
    "temperature": ("translation", "temperature"),
    "max_tokens": ("translation", "max_tokens"),
    "top_p": ("translation", "top_p"),
    "max_retries": ("translation", "max_retries"),
    # P5-A: verification_mode 是 core 策略选择键 (tvw.py quality_strategy 消费),
    # 不再是旧 CLI 死参数; semantic_threshold 映射策略真读的 gate.semantic_threshold
    "verification_mode": ("translation", "quality_strategy"),
    "semantic_threshold": ("translation", "gate.semantic_threshold"),
    "sim_drop_limit": ("translation", "gate.sim_drop_limit"),
    # tts
    "speed_factor": ("tts", "speed_factor"),
    "tts_concurrency": ("tts", "concurrency"),
    "chattts_speaker_seed": ("tts", "chattts_speaker_seed"),
    "chattts_temperature": ("tts", "chattts_temperature"),
    "chattts_top_k": ("tts", "chattts_top_k"),
    "chattts_top_p": ("tts", "chattts_top_p"),
    "chattts_workers": ("tts", "chattts_workers"),
    "chattts_emotion_injection": ("tts", "chattts_emotion_injection"),
    "edge_voice": ("tts", "edge_voice"),
    "edge_rate": ("tts", "edge_rate"),
    "edge_pitch": ("tts", "edge_pitch"),
    "edge_volume": ("tts", "edge_volume"),
    "base_speed": ("tts", "base_speed"),
    "video_speed_min": ("tts", "video_speed_min"),
    "video_speed_max": ("tts", "video_speed_max"),
}

# 字幕样式走 CLI 参数 (pass_factory caption_config 消费端已存在)
_CAPTION_CLI_MAP: tuple[tuple[str, str], ...] = (
    ("--caption-font", "caption_font"),
    ("--caption-font-size", "caption_font_size"),
    ("--caption-font-color", "caption_font_color"),
    ("--caption-stroke-width", "caption_stroke_width"),
    ("--caption-stroke-color", "caption_stroke_color"),
    ("--caption-bg-color", "caption_bg_color"),
    ("--caption-alignment", "caption_alignment"),
    ("--caption-position", "caption_position"),
    ("--caption-max-lines", "caption_max_lines"),
    ("--caption-width-ratio", "caption_width_ratio"),
)


def _pipeline_cfg_to_slot_overrides(cfg: dict) -> dict:
    """把前端差异层 (snake_case) 映射为槽位级覆盖 dict。

    只映射用户改过的键 (差异层天然满足); 等于"自动/默认"语义的
    值跳过 (source_lang=auto, max_speakers=0), 交由引擎自动检测。
    """
    overrides: dict = {}
    for key, (slot, path) in _SLOT_OVERRIDE_MAP.items():
        if key not in cfg or cfg[key] is None:
            continue
        val = cfg[key]
        if key == "source_lang" and val in ("auto", ""):
            continue
        if key == "max_speakers" and val in (0, ""):
            continue
        target = overrides.setdefault(slot, {})
        parts = path.split(".")
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = val
    return overrides


def _run_core_pipeline_sync(job: Job, req: CoreRunRequest, flags: dict | None = None) -> None:
    """在线程池中同步执行 core/ Pipeline（通过 tvw.py subprocess 统一入口）。

    计划书 §10 架构: WebUI → Runtime API → tvw.py (subprocess) → WorkflowOrchestrator
    """
    import subprocess as _sp

    # 流水线需要 GPU 显存 — 先释放 ChatTTS 预览引擎 (抽卡试听后常驻 2.37GB)
    _release_chattts_engine_if_loaded()

    sse_handler = SSELogHandler(job.append_log)
    root_logger = logging.getLogger()
    root_logger.addHandler(sse_handler)

    _stage_index = {"load": 5, "extract": 20, "translate": 50, "validate": 65, "tts": 75, "export": 90}

    # 从 settings.json 读取全局偏好，弥补前端简化后不再传的字段
    settings = load_settings()
    pipeline_cfg = settings.get("pipeline", {})
    engine = req.engine or pipeline_cfg.get("tts_engine", "chattts")
    target_lang = req.target_lang or pipeline_cfg.get("target_lang", "zh")

    # 构建 tvw.py 参数
    tvw_args = [
        str(VENV_PYTHON), str(TVW_SCRIPT),
        "--json-output", "run", str(req.video_path),
        "--use-core",
    ]
    if target_lang:
        tvw_args.extend(["--lang", target_lang])
    if engine:
        tvw_args.extend(["--engine", engine])
    # P2 设置桥: 差异层 → GlobalConfig 槽位覆盖 (新架构配置体系正门)
    slot_overrides = _pipeline_cfg_to_slot_overrides(pipeline_cfg)
    if slot_overrides:
        tvw_args.extend(["--config-overrides", json.dumps(slot_overrides, ensure_ascii=False)])
    # P2 CLI 参数桥 (pass_factory 已有消费端: caption_config)
    for flag, key in _CAPTION_CLI_MAP:
        if key in pipeline_cfg and pipeline_cfg[key] not in (None, ""):
            tvw_args.extend([flag, str(pipeline_cfg[key])])
    max_speakers = pipeline_cfg.get("max_speakers") or 0
    if max_speakers > 0 and getattr(req, "num_speakers", 0) <= 0:
        tvw_args.extend(["--num-speakers", str(max_speakers)])
    # Bootstrap if not explicit export and not full_pipeline
    preset = get_preset(req.workflow_preset) if req.workflow_preset else None
    full_pipeline = preset.config_defaults.get("full_pipeline", False) if preset else False
    extract_only = preset.config_defaults.get("bootstrap", False) if preset else False
    export_stage = getattr(req, "export_stage", False)
    if full_pipeline:
        pass  # 不加 --bootstrap 或 --export-stage → tvw.py 用 default_preset 跑全 6 阶段
    elif extract_only:
        tvw_args.append("--extract-only")
    elif not export_stage:
        tvw_args.append("--bootstrap")
    if flags and flags.get("dub_after_review"):
        tvw_args.append("--dub-after-review")
    if export_stage:
        tvw_args.append("--export-stage")
    if getattr(req, "stages", None):
        tvw_args.extend(["--stages", req.stages])
    if getattr(req, "num_speakers", 0) > 0:
        tvw_args.extend(["--num-speakers", str(req.num_speakers)])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTORCH_NO_CUDA_MEMORY_CACHING"] = "1"
    # P2/P5 LLM 参数桥: 环境变量注入 (SentenceTranslator.from_config / pass 消费),
    # 仅当外部环境未设置时注入 settings 值 — 环境变量优先级最高, 凭据不落日志
    for env_key, cfg_key in (("DEEPSEEK_API_KEY", "api_key"), ("LLM_MODEL", "model"),
                             ("LLM_BASE_URL", "api_base_url"), ("LLM_TEMPERATURE", "temperature"),
                             ("LLM_MAX_RETRIES", "max_retries"), ("LLM_MAX_TOKENS", "max_tokens"),
                             ("LLM_TOP_P", "top_p"), ("LLM_CONCURRENCY", "translate_concurrency")):
        val = pipeline_cfg.get(cfg_key)
        if val not in (None, "") and not os.environ.get(env_key):
            env[env_key] = str(val)
    # P5-A 术语表桥: 前端术语页/设置开关 → load_manual_glossary (覆盖 yaml terms_dict)
    if pipeline_cfg.get("enable_glossary") is False and not os.environ.get("GLOSSARY_ENABLED"):
        env["GLOSSARY_ENABLED"] = "0"
    glossary_files = pipeline_cfg.get("glossary_files")
    if glossary_files and not os.environ.get("GLOSSARY_FILES"):
        env["GLOSSARY_FILES"] = str(glossary_files)

    try:
        job.status = "running"
        job.runtime_state = "bootstrapping"
        job.current_step = "启动 tvw.py core/ Pipeline..."
        job.append_log("[INFO] 启动 tvw.py run --use-core --json-output")
        job.append_log(f"[INFO] {' '.join(tvw_args)}")

        ws_dir = str(Path(req.video_path).parent / f"{Path(req.video_path).stem}_project")
        job.workspace_path = ws_dir
        job.open_log_file(ws_dir)
        _update_workspace_runtime_state(ws_dir, RuntimeState.BOOTSTRAPPING)

        job.process = _sp.Popen(
            tvw_args,
            stdout=_sp.PIPE,
            stderr=_sp.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # 逐行解析 JSON 事件（RS 前缀）和普通日志
        _json_begin = "\x1e"
        for line in job.process.stdout:
            if job.status == "cancelled":
                job.process.terminate()
                job.process.wait(timeout=10)
                break
            line = line.rstrip()
            if not line:
                continue
            # 鲁棒解析: 尝试去掉 RS 前缀解析 JSON，失败则作为原始日志
            if line.startswith(_json_begin):
                line = line[1:]
            try:
                evt = json.loads(line)
                _handle_tvw_event(job, evt, _stage_index)
            except ValueError:
                job.append_log(line)

        job.process.wait()
        rc = job.process.returncode

        if job.status == "cancelled":
            return

        if rc == 0:
            job.status = "completed"
            is_export = getattr(req, "export_stage", False)
            job.runtime_state = "complete" if is_export else "ready"
            job.progress = 100
            job.current_step = "core/ Pipeline 完成"
            _update_workspace_runtime_state(
                job.workspace_path,
                RuntimeState.COMPLETE if is_export else RuntimeState.READY)
            if job._loop is not None and job._queues:
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                for q in job._queues:
                    job._loop.call_soon_threadsafe(
                        q.put_nowait,
                        {"event": "done", "status": "completed", "ts": ts},
                    )
        else:
            job.status = "failed"
            job.runtime_state = "failed"
            job.current_step = f"tvw.py exited with code {rc}"
            job.append_log(f"[ERROR] tvw.py exited with code {rc}")
            _update_workspace_runtime_state(job.workspace_path, RuntimeState.FAILED)
            if job._loop is not None and job._queues:
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                for q in job._queues:
                    job._loop.call_soon_threadsafe(
                        q.put_nowait,
                        {"event": "done", "status": "failed", "ts": ts},
                    )

    except Exception as e:
        job.status = "failed"
        job.runtime_state = "failed"
        job.current_step = "core/ Pipeline 失败"
        job.append_log(f"[ERROR] tvw.py Pipeline 失败: {e}")
        logger.exception("tvw.py Pipeline 异常 (job=%s)", job.id)
        _update_workspace_runtime_state(job.workspace_path, RuntimeState.FAILED)
        if job._loop is not None and job._queues:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            for q in job._queues:
                job._loop.call_soon_threadsafe(
                    q.put_nowait,
                    {"event": "done", "status": "failed", "ts": ts},
                )
    finally:
        _save_job(job)
        root_logger.removeHandler(sse_handler)
        job.close_log_file()


def _handle_tvw_event(job: Job, evt: dict, stage_index: dict) -> None:
    """将 tvw.py JSON 事件转换为 WebUI SSE 消息，并维护 job._stage_states。"""
    import json as _json
    ev_type = evt.get("type", "")
    if ev_type == "stage_started":
        stage = evt.get("stage", "")
        if not stage:
            return  # 跳过空 stage 事件（来自 WorkflowOrchestrator 启动事件）
        label = evt.get("stage_label", stage)
        job.current_step = f"{label}..."
        job.progress = stage_index.get(stage, 10)
        job.append_log(f"[STAGE] {label} 开始")
        job.append_log(f"[STAGE] {label} 开始")
        # 更新阶段状态
        job._stage_states[stage] = {
            "status": "running", "label": label,
            "percent": 0, "current_item": 0, "total_items": evt.get("total_items", 0),
            "started_at": time.time(),
        }
    elif ev_type == "stage_progress":
        stage = evt.get("stage", "")
        label = evt.get("stage_label", stage)
        ci = evt.get("current_item", 0)
        ti = evt.get("total_items", 0)
        pct = round(evt.get("percent", 0), 3)
        job.append_log(f"  [{label}] {evt.get('message', '')} ({ci}/{ti})")
        if stage in job._stage_states or stage:
            job._stage_states[stage] = {
                "status": "running", "label": label,
                "percent": pct, "current_item": ci, "total_items": ti or job._stage_states.get(stage, {}).get("total_items", 0),
            }
    elif ev_type == "stage_completed":
        stage = evt.get("stage", "")
        if not stage:
            return  # 跳过空 stage 事件
        label = evt.get("stage_label", stage)
        job.current_step = f"{label} 完成"
        job.progress = stage_index.get(stage, 50) + 5
        job.append_log(f"[STAGE] {label} 完成 — {evt.get('message', '')}")
        # 更新阶段状态
        prev = job._stage_states.get(stage, {})
        job._stage_states[stage] = {
            "status": "completed", "label": label,
            "percent": 100,
            "current_item": prev.get("total_items", prev.get("current_item", 0)),
            "total_items": prev.get("total_items", 0),
            "elapsed": round(time.time() - prev.get("started_at", time.time()), 1),
        }
    elif ev_type == "workflow_completed":
        job.status = "completed"
        job.runtime_state = "ready"
        job.progress = 100
        job.current_step = "core/ Pipeline 完成"
        job.append_log(f"[INFO] tvw.py workflow 完成: {evt.get('events', 0)} events")
        # Bootstrap 完成后自动桥接 timeline.json → machine.srt
        if job.workspace_path:
            try:
                srt_path = _timeline_to_srt(job.workspace_path)
                if srt_path:
                    job.append_log(f"[INFO] SRT 桥接完成: {srt_path}")
            except Exception as e:
                job.append_log(f"[WARN] SRT 桥接失败: {e}")
    elif ev_type in ("workflow_failed", "error"):
        job.append_log(f"[ERROR] tvw.py: {evt.get('error', evt.get('message', ''))}")
    elif ev_type == "log":
        level = evt.get("level", "INFO")
        msg = evt.get("message", "")
        job.append_log(f"[{level}] tvw: {msg}")
    else:
        job.append_log(f"[INFO] tvw: {_json.dumps(evt, ensure_ascii=False)}")

    if job._loop is not None and job._queues:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        payload = {
            "event": ev_type,
            "stage": evt.get("stage", ""),
            "stage_label": evt.get("stage_label", evt.get("stage", "")),
            "current_item": evt.get("current_item", 0),
            "total_items": evt.get("total_items", 0),
            "percent": round(evt.get("percent", 0), 3),
            "message": evt.get("message", evt.get("error", "")),
            "ts": ts,
            "payload": evt,
        }
        for q in job._queues:
            job._loop.call_soon_threadsafe(q.put_nowait, payload)


@app.post("/api/core/pipeline/run", response_model=CoreRunResponse)
async def start_core_pipeline(req: CoreRunRequest) -> CoreRunResponse:
    """启动 core/ WorkflowOrchestrator Pipeline。(批次11 §3.1)"""
    video = Path(req.video_path)
    if not video.is_file():
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {req.video_path}")

    job_id = uuid.uuid4().hex[:8]
    workspace_path = str(video.parent / f"{video.stem}_project")

    policy, _, skip_tts = _preset_to_policy(req.workflow_preset, req.target_lang)

    # Core Pipeline 分两段: Bootstrap (到 VALIDATE) + Export (TTS→EXPORT)
    # Timeline Runtime 初始化时永远只跑 Bootstrap，TTS 在用户确认后显式触发
    is_bootstrap = True

    policy_summary = {
        "stages": [s.value for s in policy.stage_order()],
        "gates": {},
    }
    for stage, sc in policy.stages.items():
        if sc.gate:
            policy_summary["gates"][stage.value] = sc.gate

    job = Job(
        id=job_id,
        status="running",
        runtime_state="bootstrapping",
        current_step="启动 core/ Pipeline...",
        video_path=req.video_path,
        workspace_path=workspace_path,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _jobs[job_id] = job
    job._loop = asyncio.get_running_loop()
    _save_job(job)

    asyncio.create_task(_run_core_job(job, req))

    return CoreRunResponse(
        job_id=job_id,
        workspace_path=workspace_path,
        policy_summary=policy_summary,
    )


async def _run_core_job(job: Job, req: CoreRunRequest) -> None:
    """在线程池中运行 core/ Pipeline。"""
    await asyncio.to_thread(_run_core_pipeline_sync, job, req)


@app.get("/api/core/pipeline/{job_id}/status", response_model=CoreStatusResponse)
async def get_core_status(job_id: str) -> CoreStatusResponse:
    """返回 core/ Pipeline 的结构化状态。(批次11 §3.2)"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return CoreStatusResponse(
        job_id=job_id,
        status=job.status,
        orchestrator_status=job.runtime_state.upper() if job.runtime_state else "IDLE",
        current_stage=job.current_step,
        current_step=job.current_step,
        progress=job.progress,
        stages=job._stage_states,
        pending_review=[],
        metrics={},
    )


# ── core Pipeline 日志流实现 (P5-B 端点曾引用未定义函数 — 补齐) ──

async def stream_logs(job_id: str, request: Request) -> StreamingResponse:
    """SSE 实时日志流: 转发 job._queues 的 stage/done 事件 + keepalive。

    历史日志由前端通过 /logs/tail 预取, 本流只推实时事件避免重复。
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    q = job.subscribe()

    async def gen():
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if isinstance(evt, dict):
                    if evt.get("event") == "done":
                        yield f"event: done\ndata: {json.dumps({'status': evt.get('status', 'completed')}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'message': str(evt)}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            job.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def logs_tail(job_id: str, limit: int = 200) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"lines": job.logs[-limit:], "total": len(job.logs)}


async def logs_range(job_id: str, before: int = 0, limit: int = 200) -> dict:
    """返回全局索引 [before-limit, before) 的日志段 (滚动向上加载)。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    start = max(0, before - limit)
    return {"lines": job.logs[start:before], "first": start, "total": len(job.logs)}


@app.get("/api/core/pipeline/{job_id}/logs")
async def get_core_logs(job_id: str, request: Request) -> StreamingResponse:
    """core/ Pipeline SSE 日志流。"""
    return await stream_logs(job_id, request)


@app.get("/api/core/pipeline/{job_id}/logs/tail")
async def get_core_log_tail(job_id: str, limit: int = 200) -> dict:
    return await logs_tail(job_id, limit)


@app.get("/api/core/pipeline/{job_id}/logs/range")
async def get_core_log_range(job_id: str, before: int = 0, limit: int = 200) -> dict:
    return await logs_range(job_id, before, limit)


@app.post("/api/core/pipeline/{job_id}/cancel")
async def cancel_core_job(job_id: str) -> dict:
    return await cancel_job(job_id)


@app.post("/api/core/pipeline/cancel-by-workspace")
async def cancel_core_by_workspace(body: dict) -> dict:
    """Cancel a running core job by workspace path."""
    ws = body.get("workspace_path", "")
    if not ws:
        raise HTTPException(status_code=400, detail="Missing workspace_path")
    for job_id, job in _jobs.items():
        if getattr(job, "workspace_path", "") == ws and job.status == "running":
            if job.process and job.process.returncode is None:
                job.process.terminate()
                try:
                    job.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    job.process.kill()
            job.status = "cancelled"
            job.current_step = "已取消"
            job.append_log("[WARN] 任务已取消")
            _save_job(job)
            _update_workspace_runtime_state(ws, RuntimeState.FAILED)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="No running job for this workspace")


# ── Export endpoint (TTS→Render→Merge→Package) ──

class ExportRunRequest(BaseModel):
    workspace: str = ""
    video_path: str = ""
    engine: str = "chattts"
    target_lang: str = "zh"
    subtitle_mode: str = "burned"
    caption_font: str = ""
    caption_font_size_mode: str = "adaptive"


@app.post("/api/export/run")
async def start_export(req: ExportRunRequest) -> dict:
    """启动核心管线的 Export 阶段 (TTS→EXPORT)。"""
    video_path = req.video_path
    workspace = req.workspace

    # 从 req.video_path 或 workspace 解析视频路径
    if not video_path and workspace:
        manifest_path = Path(workspace) / "project.json"
        if manifest_path.is_file():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                video_path = manifest.get("video_path", "")
            except Exception:
                pass

    if not video_path:
        raise HTTPException(status_code=400, detail="无法确定视频路径")

    if not Path(video_path).is_file():
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {video_path}")

    # 前置检查：翻译未完成的导出注定在 TTS 阶段失败（zh 语音无法读 fallback 原文），
    # 在这里 fail fast 而不是跑几分钟 TTS 才死。
    if workspace:
        tl_path = Path(workspace) / "01_extract" / "timeline.json"
        if tl_path.is_file():
            try:
                with open(tl_path, "r", encoding="utf-8") as f:
                    _tl = json.load(f)
                untranslated = []
                for evt in _tl.get("events", []):
                    tr = evt.get("translation")
                    if isinstance(tr, dict):
                        tr = tr.get("text", "") or ""
                    tr = (tr or "").strip()
                    if not tr or tr.startswith("[TR]"):
                        untranslated.append(evt.get("id", "?"))
                if untranslated:
                    raise HTTPException(
                        status_code=400,
                        detail=f"翻译未完成：{len(untranslated)} 个事件是原文 fallback（[TR] 前缀或空）。"
                               f"请检查 config/translate.yaml 的 api_key 并先完成翻译阶段。",
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # timeline.json 读取失败不阻塞导出（TTS 阶段会自行报错）

    job_id = uuid.uuid4().hex[:8]
    job = Job(
        id=job_id,
        status="running",
        runtime_state="exporting",
        current_step="启动 Export...",
        video_path=video_path,
        workspace_path=workspace,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _jobs[job_id] = job
    job._loop = asyncio.get_running_loop()
    _save_job(job)

    # 构建 CoreRunRequest 以复用 _run_core_pipeline_sync
    export_req = CoreRunRequest(
        video_path=video_path,
        workflow_preset="export",
        target_lang=req.target_lang,
        engine=req.engine,
        export_stage=True,
    )
    asyncio.create_task(_run_core_job(job, export_req))

    return {"job_id": job_id, "workspace_path": workspace}


# ---------------------------------------------------------------------------
# Static file serving (production build)
# ---------------------------------------------------------------------------

if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")


if __name__ == "__main__":
    # Print startup banner
    magick_available = _detect_imagemagick()
    font_count = 0
    if FONT_DIR.is_dir():
        font_count = sum(1 for p in FONT_DIR.rglob("*") if p.is_file() and p.suffix.lower() in FONT_EXTENSIONS)

    banner = f"""
=======================================================
  Translate Video GUI Server v1.0
=======================================================
  Backend:  http://127.0.0.1:8000
  API Docs: http://127.0.0.1:8000/docs
  Log file: {LOG_DIR / "server.log"}
  Font dir: {FONT_DIR} ({font_count} fonts)
  ImageMagick: {"OK" if magick_available else "NOT FOUND"}
  Static: {"serving from dist/" if DIST_DIR.is_dir() else "not built (use npm run build)"}
=======================================================
Close this window to stop the server.
"""
    print(banner)
    logger.info("Server starting on http://127.0.0.1:8000")
    logger.info("Log file: %s", LOG_DIR / "server.log")
    logger.info("Font directory: %s (%d fonts found)", FONT_DIR, font_count)
    logger.info("ImageMagick: %s", "available" if magick_available else "MISSING")

    import uvicorn
    uvicorn.run(
        app, host="127.0.0.1", port=8000, reload=True,
        # 禁止 uvicorn 覆盖系统日志配置
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {},
            "handlers": {},
            "loggers": {},
        },
    )
