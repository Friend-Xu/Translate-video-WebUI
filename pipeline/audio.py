"""
音频提取模块 — 视频→WAV，自动 aresample 修复 C2 缺陷 (NODE 2)

接口:
    need_extract_audio(wav_path, ffmpeg_exe, expected_sec, diagnosis) -> bool
        检查已有 WAV 是否可用，返回是否需要重新提取

    extract_audio_with_fix(video_path, wav_path, duration_sec, ffmpeg_exe) -> float
        提取音频 + 自动 aresample 修复，返回 WAV 实际时长

    get_wav_duration(wav_path, ffmpeg_exe) -> float
        获取 WAV 文件时长
"""
import os
import re
import subprocess


def get_wav_duration(wav_path: str, ffmpeg_exe: str) -> float:
    """通过 ffmpeg -i 获取 WAV 文件的时长"""
    r = subprocess.run([ffmpeg_exe, "-i", wav_path], capture_output=True, text=True)
    for line in r.stderr.split("\n"):
        if "Duration:" in line:
            dur_str = line.split(",")[0].replace("Duration:", "").strip()
            hh, mm, ss = [float(x) for x in dur_str.replace(",", ".").split(":")]
            return hh * 3600 + mm * 60 + ss
    return 0.0


def need_extract_audio(wav_path: str, ffmpeg_exe: str,
                       expected_sec: float, diagnosis) -> bool:
    """
    判断是否需要重新提取音频。

    Args:
        wav_path: WAV 文件路径
        ffmpeg_exe: ffmpeg 可执行路径
        expected_sec: 期望的时长（视频容器时长）
        diagnosis: MediaValidator 诊断结果

    Returns:
        True 表示需要重新提取，False 表示现有 WAV 可用
    """
    if not os.path.exists(wav_path):
        return True

    wav_sec = get_wav_duration(wav_path, ffmpeg_exe)
    if wav_sec > 0 and abs(wav_sec - expected_sec) < 2.0 and diagnosis.status == "ok":
        return False  # WAV 时长匹配且无缺陷，无需重提

    os.remove(wav_path)
    return True


def extract_audio_with_fix(video_path: str, wav_path: str,
                           duration_sec: float, ffmpeg_exe: str,
                           sr: int = 16000, ch: int = 1) -> float:
    """
    提取音频 + 自动 aresample 修复 C2 缺陷。

    策略:
        - 有容器时长 (duration_sec > 0):
          aresample=async=1:first_pts=0 + -t <duration_sec>
          让 ffmpeg 输出精确对齐容器时长
        - 无容器时长:
          裸提取（无修复）

    Returns:
        WAV 实际时长（秒）
    """
    cmd = [
        ffmpeg_exe, "-y",
        "-i", video_path,
        "-vn",
        "-af", "aresample=async=1:first_pts=0",
        "-c:a", "pcm_s16le",
        "-ar", str(sr),
        "-ac", str(ch),
        "-t", str(duration_sec),
        wav_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg 提取失败: {r.stderr[:200]}")

    wav_sec = get_wav_duration(wav_path, ffmpeg_exe)
    return wav_sec


def extract_audio_bare(video_path: str, wav_path: str, ffmpeg_exe: str,
                       sr: int = 16000, ch: int = 1) -> float:
    """裸提取音频（无修复），作为无 CD 时的兜底"""
    cmd = [
        ffmpeg_exe, "-y", "-i", video_path, "-vn",
        "-c:a", "pcm_s16le", "-ar", str(sr), "-ac", str(ch),
        wav_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    return get_wav_duration(wav_path, ffmpeg_exe)
