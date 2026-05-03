"""
FastAPI backend for Translate_video GUI.

Endpoints:
  POST /api/pipeline/run          - Start pipeline
  GET  /api/pipeline/{id}/logs    - SSE log stream
  GET  /api/pipeline/{id}/status  - Job status
  POST /api/pipeline/{id}/cancel  - Kill running job
  GET  /api/jobs                  - List all jobs (persisted)
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
import shutil
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


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    video_path: str
    lang: str = "auto"
    model: str = "small"
    device: str = "cpu"
    engine: str = "edge"
    skip_extract: bool = False
    skip_translate: bool = False
    skip_tts: bool = False
    skip_defect_check: bool = False
    force: bool = False
    caption_font: str = ""
    caption_font_size: int = 0
    caption_stroke_width: float = 0.0


class RunResponse(BaseModel):
    job_id: str


class StatusResponse(BaseModel):
    status: str
    progress: int
    current_step: str


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

    # Apply user subtitle settings to Config.yaml before launching pipeline
    apply_subtitle_settings()

    # Build CLI args matching main.py's argparse
    args: list[str] = [
        str(VENV_PYTHON), str(MAIN_SCRIPT), str(video),
        "--model", req.model,
        "--device", req.device,
        "--engine", req.engine,
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
    if req.force:
        args.append("--force")
    if req.caption_font:
        args.extend(["--caption-font", req.caption_font])
    if req.caption_font_size > 0:
        args.extend(["--caption-font-size", str(req.caption_font_size)])
    if req.caption_stroke_width > 0:
        args.extend(["--caption-stroke-width", str(req.caption_stroke_width)])

    asyncio.create_task(_run_job(job, args))
    return RunResponse(job_id=job_id)


async def _run_job(job: Job, args: list[str]) -> None:
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

    # Try nvidia-smi (multiple Windows paths)
    nvidia_smi_paths = [
        "nvidia-smi",
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for smi in nvidia_smi_paths:
        try:
            result = subprocess.run(
                [smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                has_gpu = True
                gpu_name = result.stdout.strip().split("\n")[0]
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
        except Exception:
            pass

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

    import subprocess
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
# Font listing & subtitle preview (ImageMagick)
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
            return sorted(found, reverse=True)[0]  # latest version
    return None


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
    bg_opacity: int = 128,
    text_zh: str = "Minecraft我的世界 村民交易",
    text_en: str = "Minecraft Villager Trade x64",
) -> StreamingResponse:
    """Render a subtitle preview image using ImageMagick."""
    from fastapi.responses import Response as RawResponse
    import subprocess, tempfile

    magick = _detect_imagemagick()
    if not magick:
        raise HTTPException(
            status_code=503,
            detail="ImageMagick 未安装。请安装 ImageMagick 后重试。\n"
                   "下载地址: https://imagemagick.org/script/download.php",
        )

    # Resolve font: empty=default, file path→verify exists, system name→use directly
    if not font:
        font = str(PROJECT_ROOT / "models" / "font" / "Minecraft_font" / "5_Minecraft_AE_zh_en.ttf")
    elif Path(font).is_absolute():
        if not Path(font).is_file():
            raise HTTPException(status_code=400, detail=f"字体文件不存在: {font}")
    elif font.endswith((".ttf", ".otf", ".ttc")) or "/" in font or "\\" in font:
        # Relative file path — resolve against FONT_DIR
        resolved = str(FONT_DIR / font)
        if not Path(resolved).is_file():
            raise HTTPException(status_code=400, detail=f"字体文件不存在: {resolved}")
        font = resolved
    # else: system font name like "SimHei" or "Microsoft-YaHei-Bold" — send directly to ImageMagick

    # Build combined text with interline spacing via newline
    combined = f"{text_zh}\n{text_en}" if text_en else text_zh
    canvas_w, canvas_h = 800, 220
    bg_alpha_pct = int(bg_opacity / 255 * 100)

    tmp_dir = tempfile.gettempdir()
    out_path = os.path.join(tmp_dir, f"_subtitle_preview_{os.getpid()}.png")

    # Use inline text (not @file) to avoid Windows encoding issues with CJK
    args = [
        magick,
        "-size", f"{canvas_w}x{canvas_h}",
        "xc:rgb(30,30,30)",
        "-fill", f"rgba(0,0,0,{bg_alpha_pct}%)",
        "-draw", f"rectangle 20,{canvas_h - 100} {canvas_w - 20},{canvas_h - 10}",
        "-gravity", "south",
        "-encoding", "Unicode",
        "-font", font,
        "-pointsize", str(font_size),
        "-fill", font_color,
        "-stroke", stroke_color,
        "-strokewidth", str(stroke_width),
        "-annotate", "+0+20",
        combined,
        out_path,
    ]

    try:
        result = subprocess.run(
            args,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.error("ImageMagick render failed: %s", result.stderr[:500])
            raise HTTPException(status_code=500, detail=f"ImageMagick 渲染失败: {result.stderr[:500]}")
    except FileNotFoundError:
        logger.error("ImageMagick binary not found")
        raise HTTPException(status_code=503, detail="ImageMagick 未找到")

    if not Path(out_path).is_file():
        raise HTTPException(status_code=500, detail="预览图生成失败")

    img_bytes = Path(out_path).read_bytes()
    try:
        os.remove(out_path)
    except OSError:
        pass

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
    uvicorn.run(app, host="127.0.0.1", port=8000)
