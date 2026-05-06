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
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import AsyncIterator

import yaml

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging setup: file + console
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = logging.Formatter(
    "[%(asctime)s] [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_file_handler = RotatingFileHandler(
    LOG_DIR / "server.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
)
_file_handler.setFormatter(LOG_FORMAT)
_file_handler.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(LOG_FORMAT)
_console_handler.setLevel(logging.INFO)

logging.basicConfig(level=logging.DEBUG, handlers=[_file_handler, _console_handler])
logger = logging.getLogger("server")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
DIST_DIR = Path(__file__).resolve().parent / "dist"
JOBS_DIR = Path(__file__).resolve().parent / "jobs"
BATCHES_DIR = Path(__file__).resolve().parent / "batches"
SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
CONFIG_YAML = PROJECT_ROOT / "SRT" / "Config.yaml"
CONFIG_BAK = PROJECT_ROOT / "SRT" / "Config.yaml.bak"
FONT_DIR = PROJECT_ROOT / "models" / "font"

app = FastAPI(title="Translate Video GUI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every API request with method, path, status, and duration."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.0fms)",
        request.method, request.url.path, response.status_code, elapsed,
    )
    if response.status_code >= 400:
        logger.warning("  Request failed with status %d", response.status_code)
    return response


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

@dataclass
class Job:
    id: str
    process: asyncio.subprocess.Process | None = None
    status: str = "idle"        # idle | running | completed | failed | cancelled
    progress: int = 0
    current_step: str = "就绪"
    logs: list[str] = field(default_factory=list)
    video_path: str = ""
    created_at: str = ""
    batch_id: str | None = None
    _log_event: asyncio.Event = field(default_factory=asyncio.Event)

    def append_log(self, line: str) -> None:
        self.logs.append(line)
        # Parse step hints from stdout for progress
        lower = line.lower()
        if "[1/3]" in line or "字幕提取" in line:
            self.current_step = "字幕提取中..."
            self.progress = 10
        elif "[2/3]" in line or "翻译" in line:
            self.current_step = "字幕翻译中..."
            self.progress = 40
        elif "[3/3]" in line or "tts" in line.lower():
            self.current_step = "TTS 合成中..."
            self.progress = 70
        if "[ok]" in lower:
            self.progress = min(self.progress + 15, 95)
        _save_job(self)
        # Wake up any SSE listeners
        self._log_event.set()
        self._log_event.clear()


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
            "logs": job.logs[-200:],
            "video_path": job.video_path,
            "created_at": job.created_at,
            "batch_id": job.batch_id,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
            logs=data.get("logs", []),
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


def _load_yaml_defaults() -> dict:
    """Read config/tts.yaml and config/translate.yaml, map to frontend field names."""
    tts = _load_yaml(PROJECT_ROOT / "config" / "tts.yaml").get("tts", {})
    trans = _load_yaml(PROJECT_ROOT / "config" / "translate.yaml").get("translate", {})

    return {
        "engine": tts.get("engine_type", "edge"),
        "voice": tts.get("voice", "zh-CN-XiaoxiaoNeural"),
        "enableVoiceClone": tts.get("enable_openvoice", False),
        "voiceCloneSample": tts.get("voice_clone_sample") or "",
        "openvoiceVersion": tts.get("openvoice_model_version", "v2"),
        "enableEmotionClone": tts.get("enable_emotion", False),
        "defaultEmotion": tts.get("default_emotion", "neutral"),
        "emotionRefAudio": tts.get("emotion_ref_audio") or "",
        "concurrency": trans.get("concurrency", {}).get("max_workers", tts.get("threading_workers", 3)),
        "enableCheckpoint": tts.get("enable_resume", False),
        "captionFont": tts.get("caption_font", ""),
        "videoCodec": tts.get("video_codec", "libx264"),
        "audioCodec": tts.get("video_audio_codec", "aac"),
        "apiKey": trans.get("api_key", ""),
        "apiType": trans.get("api_type", "deepseek"),
        "enableSemanticValidation": trans.get("semantic_check", True),
        "enableTermReplacement": trans.get("terms_dict", {}).get("enabled", True),
    }


def ensure_backup() -> None:
    if not CONFIG_BAK.exists() and CONFIG_YAML.exists():
        shutil.copy2(CONFIG_YAML, CONFIG_BAK)


def load_config_yaml() -> dict:
    with open(CONFIG_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_config_yaml(data: dict) -> None:
    with open(CONFIG_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def apply_subtitle_settings() -> None:
    ensure_backup()
    settings = load_settings()
    overrides = settings.get("subtitle", {})
    if not overrides:
        return
    presets = load_config_yaml()
    for lang, params in overrides.items():
        if lang in presets and isinstance(params, dict):
            presets[lang].update(params)
    write_config_yaml(presets)


def reset_language(language: str) -> dict:
    ensure_backup()
    with open(CONFIG_BAK, "r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}
    presets = load_config_yaml()
    if language in defaults:
        presets[language] = defaults[language]
    write_config_yaml(presets)
    settings = load_settings()
    settings.get("subtitle", {}).pop(language, None)
    save_settings(settings)
    return presets.get(language, {})


def _sync_translate_config() -> None:
    """Write pipeline settings (concurrency, etc.) from settings.json → translate.yaml."""
    translate_path = PROJECT_ROOT / "config" / "translate.yaml"
    if not translate_path.exists():
        return
    settings = load_settings()
    pipeline_cfg = settings.get("pipeline", {})
    if not pipeline_cfg:
        return

    with open(translate_path, "r", encoding="utf-8") as f:
        trans = yaml.safe_load(f) or {}

    if "translate" not in trans:
        trans["translate"] = {}

    # Sync concurrency setting
    if "concurrency" in pipeline_cfg:
        conc = pipeline_cfg["concurrency"]
        if "concurrency" not in trans["translate"]:
            trans["translate"]["concurrency"] = {}
        trans["translate"]["concurrency"]["enabled"] = conc > 1
        trans["translate"]["concurrency"]["max_workers"] = conc

    # Sync API key if provided
    if pipeline_cfg.get("apiKey"):
        trans["translate"]["api_key"] = pipeline_cfg["apiKey"]

    with open(translate_path, "w", encoding="utf-8") as f:
        yaml.dump(trans, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    video_path: str
    lang: str = "auto"
    model: str = "turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    engine: str = "edge"
    skip_extract: bool = False
    skip_translate: bool = False
    skip_tts: bool = False
    skip_defect_check: bool = False
    skip_demucs: bool = False
    force: bool = False
    caption_font: str = ""
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
    num_workers: int = 1


class RunResponse(BaseModel):
    job_id: str


class StatusResponse(BaseModel):
    status: str
    progress: int
    current_step: str


# ---------------------------------------------------------------------------
# Helper functions for pipeline launch
# ---------------------------------------------------------------------------

def _write_caption_config(req: RunRequest) -> str:
    caption_config_path = PROJECT_ROOT / "config" / "caption.yaml"
    caption_config_path.parent.mkdir(exist_ok=True)
    caption_data = {
        "caption": {
            "font": req.caption_font,
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


def _build_cli_args(req: RunRequest) -> list[str]:
    caption_config_path = _write_caption_config(req)
    args: list[str] = [
        str(VENV_PYTHON), str(MAIN_SCRIPT), str(req.video_path),
        "--model", req.model,
        "--device", req.device,
        "--compute-type", req.compute_type,
        "--engine", req.engine,
        "--caption-config", caption_config_path,
    ]
    if req.lang and req.lang != "auto":
        args.extend(["--lang", req.lang])
    if req.skip_extract:
        args.append("--skip-extract")
    if req.skip_translate:
        args.append("--skip-translate")
    if req.skip_tts:
        args.append("--skip-tts")
    if req.skip_defect_check:
        args.append("--skip-defect-check")
    if req.skip_demucs:
        args.append("--skip-demucs")
    if req.force:
        args.append("--force")
    if req.num_workers > 1:
        args.extend(["--num-workers", str(req.num_workers)])
    return args


async def _run_job_sync(job: Job, args: list[str]) -> None:
    """Run a single job and wait for completion (for batch processing)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        job.process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        assert job.process.stdout is not None
        async for raw_line in job.process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                job.append_log(line)

        await job.process.wait()
        if job.status == "cancelled":
            _save_job(job)
            return
        if job.process.returncode == 0:
            job.status = "completed"
            job.progress = 100
            job.current_step = "处理完成"
            job.append_log("[INFO] 处理完成")
        else:
            job.status = "failed"
            job.current_step = f"失败 (code={job.process.returncode})"
            job.append_log(f"[ERROR] 流水线失败，退出码: {job.process.returncode}")
        _save_job(job)
    except Exception as e:
        job.status = "failed"
        job.current_step = "异常"
        job.append_log(f"[ERROR] {e}")
        _save_job(job)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/pipeline/run", response_model=RunResponse)
async def start_pipeline(req: RunRequest) -> RunResponse:
    video = Path(req.video_path)
    if not video.is_file():
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {req.video_path}")

    job_id = uuid.uuid4().hex[:8]
    job = Job(
        id=job_id,
        status="running",
        current_step="启动中...",
        video_path=req.video_path,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _jobs[job_id] = job
    _save_job(job)

    apply_subtitle_settings()
    _sync_translate_config()
    args = _build_cli_args(req)

    asyncio.create_task(_run_job(job, args))
    return RunResponse(job_id=job_id)


async def _run_job(job: Job, args: list[str]) -> None:
    """Run a job as a fire-and-forget background task."""
    await _run_job_sync(job, args)


async def _batch_processor(batch_id: str) -> None:
    """Process all videos in a batch sequentially."""
    batch = _batches.get(batch_id)
    if not batch:
        return

    try:
        for i, video_path in enumerate(batch.video_paths):
            if batch.status == "cancelled":
                batch.append_log("[BATCH] 批次已取消，停止处理")
                return

            batch.current_video_index = i
            video_name = os.path.basename(video_path)
            batch.append_log(f"[BATCH] ({i+1}/{len(batch.video_paths)}) 开始: {video_name}")
            _save_batch(batch)

            video = Path(video_path)
            if not video.is_file():
                batch.append_log(f"[ERROR] 视频文件不存在，跳过: {video_path}")
                continue

            config_data = json.loads(batch.config_json)
            config_data["video_path"] = video_path
            req = RunRequest(**config_data)

            job_id = uuid.uuid4().hex[:8]
            job = Job(
                id=job_id,
                status="running",
                current_step="启动中...",
                video_path=video_path,
                batch_id=batch_id,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            _jobs[job_id] = job
            batch.video_job_ids[video_path] = job_id
            _save_job(job)

            apply_subtitle_settings()
            _sync_translate_config()
            args = _build_cli_args(req)

            await _run_job_sync(job, args)

            if job.status == "completed":
                batch.append_log(f"[BATCH] [OK] ({i+1}/{len(batch.video_paths)}) {video_name}")
            elif job.status == "failed":
                batch.append_log(f"[ERROR] 视频处理失败: {video_name}")
            elif job.status == "cancelled":
                batch.append_log(f"[BATCH] 视频已跳过: {video_name}")

        all_jobs = [j for j in _jobs.values() if j.batch_id == batch_id]
        if batch.status == "cancelled":
            return
        if all(j.status == "completed" for j in all_jobs):
            batch.status = "completed"
            batch.append_log("[BATCH] 批次全部完成")
        elif any(j.status == "completed" for j in all_jobs):
            batch.status = "partial"
            batch.append_log("[BATCH] 批次部分完成")
        else:
            batch.status = "failed"
            batch.append_log("[BATCH] 批次失败")

    except Exception as e:
        batch.status = "failed"
        batch.append_log(f"[BATCH] [ERROR] 批次异常: {e}")
    finally:
        _save_batch(batch)


@app.get("/api/pipeline/{job_id}/status", response_model=StatusResponse)
async def get_status(job_id: str) -> StatusResponse:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return StatusResponse(
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
    )


@app.get("/api/pipeline/{job_id}/logs")
async def stream_logs(job_id: str) -> StreamingResponse:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream() -> AsyncIterator[str]:
        idx = 0
        while True:
            # Send any new log lines
            while idx < len(job.logs):
                data = json.dumps({"message": job.logs[idx]}, ensure_ascii=False)
                yield f"data: {data}\n\n"
                idx += 1

            if job.status in ("completed", "failed", "cancelled"):
                # Send final status event
                yield f"event: done\ndata: {json.dumps({'status': job.status})}\n\n"
                return

            # Wait for new logs or timeout
            try:
                await asyncio.wait_for(job._log_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/pipeline/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.process and job.process.returncode is None:
        job.process.terminate()
        try:
            await asyncio.wait_for(job.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            job.process.kill()
        job.status = "cancelled"
        job.current_step = "已取消"
        job.append_log("[WARN] 任务已取消")
        _save_job(job)
    return {"ok": True}


@app.get("/api/jobs")
async def list_jobs() -> list[dict]:
    return [
        {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "video_path": job.video_path,
            "created_at": job.created_at,
        }
        for job in sorted(_jobs.values(), key=lambda j: j.created_at or "", reverse=True)
    ]


# ---------------------------------------------------------------------------
# Batch processing endpoints
# ---------------------------------------------------------------------------

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
                    await asyncio.wait_for(job.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
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


@app.get("/api/batch/list")
async def list_batches() -> list[dict]:
    return [
        {
            "batch_id": b.id,
            "status": b.status,
            "video_count": len(b.video_paths),
            "completed_count": sum(
                1 for p in b.video_paths
                if (jid := b.video_job_ids.get(p))
                and (j := _jobs.get(jid))
                and j.status == "completed"
            ),
            "created_at": b.created_at,
        }
        for b in sorted(_batches.values(), key=lambda x: x.created_at or "", reverse=True)
    ]


@app.get("/api/batch/active")
async def get_active_batch() -> dict | None:
    for batch in _batches.values():
        if batch.status == "running":
            return _build_batch_dict(batch)
    return None


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
                    await asyncio.wait_for(job.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
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

class SettingsPayload(BaseModel):
    subtitle: dict[str, dict] | None = None


class ResetPayload(BaseModel):
    language: str


@app.get("/api/settings")
async def get_settings() -> dict:
    return load_settings()


@app.post("/api/settings")
async def post_settings(payload: SettingsPayload) -> dict:
    current = load_settings()
    if payload.subtitle is not None:
        current["subtitle"] = payload.subtitle
    save_settings(current)
    return current


@app.post("/api/settings/reset")
async def post_settings_reset(payload: ResetPayload) -> dict:
    lang_preset = reset_language(payload.language)
    return {"language": payload.language, "preset": lang_preset}


@app.get("/api/subtitle/presets")
async def get_subtitle_presets() -> dict:
    ensure_backup()
    return load_config_yaml()


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
    from pipeline.external_subtitle_optimizer import (
        optimize_srt, optimize_bilingual, load_ext_subtitle_config,
    )

    target = Path(req.target_srt)
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"目标字幕文件不存在: {req.target_srt}")

    # Load defaults from config
    cfg = load_ext_subtitle_config()
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
        stats = optimize_bilingual(req.target_srt, req.source_srt, output_path, **kwargs)
    else:
        stats = optimize_srt(req.target_srt, output_path, **kwargs)

    return {"ok": True, "output_path": output_path, "stats": stats}


@app.get("/api/subtitle/optimize-defaults")
async def subtitle_optimize_defaults() -> dict:
    from pipeline.external_subtitle_optimizer import load_ext_subtitle_config
    cfg = load_ext_subtitle_config()
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
    source_srt: str
    translated_srt: str
    translate_log: str | None = None


def _srt_time_to_ms(srt_time) -> int:
    return srt_time.ordinal


def _detect_video_in_dir(srt_path: str) -> str:
    srt_dir = os.path.dirname(srt_path)
    VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}
    for name in sorted(os.listdir(srt_dir)):
        _, ext = os.path.splitext(name)
        if ext.lower() in VIDEO_EXTS:
            video_path = os.path.join(srt_dir, name)
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


@app.post("/api/subtitle/review/load")
async def review_load(req: ReviewLoadRequest) -> dict:
    import pysrt

    source = Path(req.source_srt)
    translated = Path(req.translated_srt)
    if not source.is_file():
        raise HTTPException(status_code=400, detail=f"原文字幕不存在: {req.source_srt}")
    if not translated.is_file():
        raise HTTPException(status_code=400, detail=f"译文字幕不存在: {req.translated_srt}")

    src_subs = pysrt.open(str(source))
    tr_subs = pysrt.open(str(translated))

    tr_map: dict[int, pysrt.SubRipItem] = {}
    for sub in tr_subs:
        tr_map[sub.index] = sub

    # Read translate-log.json for semantic check scores
    similarity_map: dict[int, float] = {}
    if req.translate_log and os.path.isfile(req.translate_log):
        try:
            with open(req.translate_log, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            for detail in log_data.get("details", []):
                sim = detail.get("similarity")
                for idx in detail.get("indices", []):
                    if sim is not None:
                        similarity_map[idx] = sim
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

    for src in src_subs:
        tr = tr_map.get(src.index)
        translated_text = tr.text if tr else ""
        start_ms = _srt_time_to_ms(src.start)
        end_ms = _srt_time_to_ms(src.end)

        issues: list[dict] = []
        sim = similarity_map.get(src.index)
        if sim is not None and sim < 0.65:
            issues.append({
                "type": "low_similarity",
                "message": f"语义相似度低 ({sim:.2f})",
                "severity": "warning",
            })
            low_similarity_count += 1

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
        })

    _run_qa_checks(entries, lang)

    video_path = _detect_video_in_dir(req.source_srt)

    return {
        "videoPath": video_path,
        "sourceSrtPath": req.source_srt,
        "translatedSrtPath": req.translated_srt,
        "entries": entries,
        "stats": {"total": len(entries), "lowSimilarity": low_similarity_count},
    }


class ReviewSaveRequest(BaseModel):
    translated_srt: str
    entries: list[dict]


@app.post("/api/subtitle/review/save")
async def review_save(req: ReviewSaveRequest) -> dict:
    import pysrt

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

    stem, ext = os.path.splitext(str(translated))
    if stem.endswith("-auto"):
        stem = stem[:-5]
    output_path = f"{stem}-reviewed{ext}"

    subs.save(output_path, encoding="utf-8")
    logger.info(f"Review saved: {updated} entries updated → {output_path}")

    return {"ok": True, "output_path": output_path, "updated": updated}


@app.get("/api/subtitle/review/qa-check")
async def review_qa_check(srt_path: str, lang: str = "zh") -> dict:
    import pysrt

    path = Path(srt_path)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"字幕文件不存在: {srt_path}")

    subs = pysrt.open(str(path))
    entries: list[dict] = []
    for sub in subs:
        entries.append({
            "index": sub.index,
            "start": str(sub.start),
            "end": str(sub.end),
            "startMs": _srt_time_to_ms(sub.start),
            "endMs": _srt_time_to_ms(sub.end),
            "sourceText": "",
            "translatedText": sub.text,
            "issues": [],
        })

    _run_qa_checks(entries, lang)

    all_issues: list[dict] = []
    for e in entries:
        for issue in e["issues"]:
            all_issues.append({"index": e["index"], **issue})

    error_count = sum(1 for i in all_issues if i["severity"] == "error")
    warning_count = sum(1 for i in all_issues if i["severity"] == "warning")

    return {
        "total": len(entries),
        "errorCount": error_count,
        "warningCount": warning_count,
        "issues": all_issues,
    }


# ---------------------------------------------------------------------------
# Config — layered: YAML defaults → user overrides in settings.json
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def get_config() -> dict:
    base = _load_yaml_defaults()
    settings = load_settings()
    overrides = settings.get("pipeline", {})
    base.update(overrides)
    return base


@app.post("/api/config")
async def post_config(payload: dict) -> dict:
    base = _load_yaml_defaults()
    overrides: dict = {}
    for key, value in payload.items():
        if key in base and value != base.get(key):
            overrides[key] = value
        elif key not in base:
            overrides[key] = value
    settings = load_settings()
    settings["pipeline"] = overrides
    save_settings(settings)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

@app.get("/api/system/info")
async def system_info() -> dict:
    """Detect CPU/GPU to recommend concurrency and device."""
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
                capture_output=True, text=True, timeout=5,
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

    return {
        "cpuCount": cpu_count,
        "hasGpu": has_gpu,
        "gpuName": gpu_name,
        "gpuVramMb": gpu_vram_mb,
        "recommendedConcurrency": recommended,
        "defaultVideoDir": default_video_dir,
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
            capture_output=True, text=True, timeout=10,
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
        resolved = str(FONT_DIR / font)
        if not Path(resolved).is_file():
            raise HTTPException(status_code=400, detail=f"字体文件不存在: {resolved}")
        return resolved
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

    # ── Adaptive font sizing (mirrors CaptionRenderer) ──
    max_width = int(canvas_w * caption_width_ratio)
    max_fs = max_font_size if max_font_size > 0 else int(canvas_h * 0.045)
    min_fs = 12
    desired = font_size if font_size > 0 else int(canvas_w * font_size_factor)

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
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
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
            )
        except Exception as e:
            logger.error("PIL render failed: %s", e)
            raise HTTPException(status_code=500, detail=f"PIL 渲染失败: {e}")

    return RawResponse(content=img_bytes, media_type="image/png")


# ---------------------------------------------------------------------------
# File browser
# ---------------------------------------------------------------------------

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


@app.get("/api/files/stream")
async def stream_file(path: str, request: Request):
    """Stream a file with HTTP Range support (for video seeking)."""
    file_path = Path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            end_str = range_match.group(2)
            end = int(end_str) if end_str else file_size - 1
            chunk_size = end - start + 1

            from fastapi.responses import Response

            with open(file_path, "rb") as f:
                f.seek(start)
                data = f.read(chunk_size)

            return Response(
                content=data,
                status_code=206,
                media_type="video/mp4",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_size),
                },
            )

    from fastapi.responses import FileResponse
    return FileResponse(path, media_type="video/mp4")


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
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
