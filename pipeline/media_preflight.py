"""
Media preflight — detect DASH-separated video/audio and remux before pipeline.

Typical case: YouTube DASH downloads produce video-only MP4 + separate audio
file (MP3/M4A). The pipeline needs a single file with both streams.

This module provides:
- check_audio_stream() — does the video have an audio track?
- find_companion_audio() — scan same dir for likely audio partner
- get_media_duration() — ffmpeg -i duration
- compare_durations() — report drift between video and audio
- check_defects() — MediaValidator diagnosis on video
- mux_video_audio() — ffmpeg stream-copy merge
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from pipeline.logger import get_logger

logger = get_logger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".opus", ".aac", ".ogg", ".flac", ".wma", ".webm"}


@dataclass
class PreflightResult:
    """Result of analyzing a video file before pipeline execution."""

    video_path: str = ""
    has_audio: bool = False
    video_duration: float = 0.0
    audio_duration: float = 0.0
    duration_match: bool = True
    duration_diff_sec: float = 0.0
    defects: list[dict] = field(default_factory=list)
    companion_audio: str = ""
    suggested_action: str = ""


def _get_ffmpeg() -> str:
    from pipeline.utils import get_ffmpeg_exe
    return get_ffmpeg_exe()


def _parse_duration(ffmpeg_stderr: str) -> float:
    """Extract Duration in seconds from ffmpeg -i stderr."""
    for line in ffmpeg_stderr.split("\n"):
        if "Duration:" in line:
            dur_str = line.split(",")[0].replace("Duration:", "").strip()
            try:
                hh, mm, ss = dur_str.replace(",", ".").split(":")
                return float(hh) * 3600 + float(mm) * 60 + float(ss)
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def check_audio_stream(video_path: str) -> bool:
    """Return True if the video file contains at least one audio stream."""
    ffmpeg = _get_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-i", video_path], capture_output=True, text=True,
    )
    return any("Audio:" in line for line in result.stderr.split("\n"))


def get_media_duration(file_path: str) -> float:
    """Get container duration (CD) of a media file in seconds via ffmpeg -i."""
    ffmpeg = _get_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-i", file_path], capture_output=True, text=True,
    )
    return _parse_duration(result.stderr)


def get_decoded_duration(file_path: str) -> float:
    """Get decoded audio duration (ADD) by actually decoding the file.

    Runs ffmpeg to decode every audio frame and measures the real sample count,
    avoiding container-metadata bias.
    """
    ffmpeg = _get_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-i", file_path, "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    for line in result.stderr.split("\n"):
        if "time=" in line:
            # Last "time=HH:MM:SS.XX" line has the final decoded timestamp
            pass
    # Parse all time= hits and take the last one
    times = []
    for line in result.stderr.split("\n"):
        if "time=" in line:
            ts = line.split("time=")[1].split()[0]
            try:
                hh, mm, ss = ts.split(":")
                times.append(float(hh) * 3600 + float(mm) * 60 + float(ss))
            except (ValueError, TypeError):
                pass
    return times[-1] if times else 0.0


def find_companion_audio(video_path: str) -> str:
    """Scan the video's directory for a companion audio file.

    Heuristic:
    1. If the directory contains exactly one MP4 + one audio file → auto-pair.
    2. If multiple audio files, pick the one whose name is most similar to the video.
    3. Otherwise return empty string.
    """
    directory = os.path.dirname(video_path)
    if not os.path.isdir(directory):
        return ""

    video_name = os.path.splitext(os.path.basename(video_path))[0].lower()

    audio_files = []
    video_count = 0
    try:
        for entry in os.listdir(directory):
            ext = os.path.splitext(entry)[1].lower()
            if ext in AUDIO_EXTENSIONS:
                audio_files.append(os.path.join(directory, entry))
            elif ext in {".mp4", ".mkv", ".avi", ".mov", ".webm"}:
                video_count += 1
    except PermissionError:
        return ""

    if not audio_files:
        return ""

    # Case 1: single MP4 + single audio → auto-pair
    if video_count == 1 and len(audio_files) == 1:
        return audio_files[0]

    # Case 2: multiple audio files → pick by name similarity
    best = ""
    best_score = 0
    for af in audio_files:
        af_name = os.path.splitext(os.path.basename(af))[0].lower()
        score = _name_similarity(video_name, af_name)
        if score > best_score:
            best_score = score
            best = af
    return best if best_score > 0.1 else ""


def _name_similarity(a: str, b: str) -> float:
    """Crude token-overlap score for matching filenames."""
    import re
    tokens_a = set(re.findall(r"\w+", a))
    tokens_b = set(re.findall(r"\w+", b))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / min(len(tokens_a), len(tokens_b))


def compare_durations(video_path: str, audio_path: str) -> tuple[float, float, float]:
    """Return (video_duration, audio_duration, diff_seconds)."""
    vd = get_media_duration(video_path)
    ad = get_media_duration(audio_path)
    diff = abs(vd - ad) if (vd > 0 and ad > 0) else 0.0
    return vd, ad, diff


def check_defects(video_path: str) -> list[dict]:
    """Run MediaValidator on the video and return defect list."""
    try:
        from SRT.MediaValidator import MediaValidator  # type: ignore[import-not-found]
        validator = MediaValidator()
        diagnosis = validator.diagnose(video_path)

        m = diagnosis.metrics
        defects = []
        if diagnosis.status == "defect":
            defects.append({
                "type": diagnosis.defect_type or "unknown",
                "name": diagnosis.defect_name or "",
                "severity": diagnosis.severity or "minor",
                "details": diagnosis.details or "",
                "action": diagnosis.suggested_action or "",
                "container_duration": round(m.container_duration, 3) if m else 0.0,
                "audio_duration": round(m.decoded_audio_duration, 3) if m else 0.0,
                "drift_pct": round(m.drift_rate_pct, 2) if m else 0.0,
            })
        return defects
    except Exception:
        logger.warning("MediaValidator unavailable", exc_info=True)
        return []


def analyze(video_path: str, audio_path: str = "") -> dict:
    """Full preflight analysis.

    Returns a dict suitable for JSON serialization to the frontend.
    """
    if not os.path.isfile(video_path):
        return {"error": f"视频文件不存在: {video_path}"}

    has_audio = check_audio_stream(video_path)
    video_cd = get_media_duration(video_path)
    video_add = get_decoded_duration(video_path)

    # Find companion audio
    companion = audio_path if (audio_path and os.path.isfile(audio_path)) else ""
    if not companion:
        companion = find_companion_audio(video_path)

    # Duration comparison (container vs decoded for both files)
    audio_cd = 0.0
    audio_add = 0.0
    duration_diff = 0.0
    duration_match = True
    if companion:
        audio_cd = get_media_duration(companion)
        audio_add = get_decoded_duration(companion)
        cd_diff = abs(video_cd - audio_cd) if (video_cd > 0 and audio_cd > 0) else 0.0
        add_diff = abs(video_add - audio_add) if (video_add > 0 and audio_add > 0) else 0.0
        # Prefer decoded comparison when both are available; fallback to container
        if video_add > 0 and audio_add > 0:
            duration_diff = add_diff
        else:
            duration_diff = cd_diff
        duration_match = duration_diff < 3.0

    # Defect check (skip C2 when no audio stream — expected for DASH)
    defects = check_defects(video_path) if has_audio else []

    # Suggested action
    if has_audio:
        action = "ok"
    elif companion:
        action = "mux" if duration_match else "mux_drift"
    else:
        action = "no_audio"

    return {
        "video_path": video_path,
        "has_audio": has_audio,
        "video_container_duration": round(video_cd, 2),
        "video_decoded_duration": round(video_add, 2),
        "video_internal_drift": round(abs(video_cd - video_add), 2) if (video_cd > 0 and video_add > 0) else 0.0,
        "audio_container_duration": round(audio_cd, 2),
        "audio_decoded_duration": round(audio_add, 2),
        "audio_internal_drift": round(abs(audio_cd - audio_add), 2) if (audio_cd > 0 and audio_add > 0) else 0.0,
        "duration_match": duration_match,
        "duration_diff_sec": round(duration_diff, 2),
        "defects": defects,
        "companion_audio": companion,
        "suggested_action": action,
    }


def mux_video_audio(video_path: str, audio_path: str, output_path: str = "") -> str:
    """Merge video and audio using ffmpeg stream-copy.

    Uses aresample to align audio timeline with video container duration,
    avoiding content truncation (no -shortest). Video stream is copied losslessly.

    Args:
        video_path: Video-only MP4 file.
        audio_path: Separate audio file.
        output_path: Destination path. Defaults to <video>_muxed.mp4.

    Returns:
        Path to the merged file.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    if not output_path:
        stem = os.path.splitext(video_path)[0]
        output_path = f"{stem}_muxed.mp4"

    video_duration = get_media_duration(video_path)

    ffmpeg = _get_ffmpeg()
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-af", "aresample=async=1:first_pts=0",
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]
    if video_duration > 0:
        cmd.extend(["-t", str(video_duration)])
    cmd.append(output_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        err = result.stderr.strip()[-400:] if result.stderr else "unknown error"
        raise RuntimeError(f"ffmpeg 合并失败: {err}")

    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("合并后的输出文件为空")

    logger.info(f"合并完成: {output_path}")
    return output_path
