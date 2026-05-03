"""
视频元数据采集模块 — 通过 ffmpeg -i 解析容器信息 (NODE 1)

接口:
    get_video_info(video_path, ffmpeg_exe) -> dict
        {
            "path": str,
            "size": int,
            "duration_str": str,
            "duration_sec": float,
            "bitrate": str,
            "video_codec": str,
            "audio_codec": str,
        }
"""
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoInfo:
    path: str
    size: int
    duration_str: str
    duration_sec: float
    bitrate: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0


def get_video_info(video_path: str, ffmpeg_exe: str) -> VideoInfo:
    """
    解析视频文件元数据。

    通过 ffmpeg -i 读取 Duration / Stream 信息（输出在 stderr）。
    """
    result = subprocess.run(
        [ffmpeg_exe, "-i", video_path],
        capture_output=True, text=True
    )
    stderr_text = result.stderr

    duration_str = ""
    bitrate_str = ""
    video_codec = ""
    audio_codec = ""
    width = 0
    height = 0

    for line in stderr_text.split("\n"):
        if "Duration:" in line:
            duration_str = line.split(",")[0].replace("Duration:", "").strip()
            bitrate_str = line.split(",")[-1].replace("bitrate:", "").strip()
        if "Stream #0:0" in line and "Video:" in line:
            video_codec = line.split("Video:")[1].strip().split(",")[0]
            res_match = re.search(r"(\d{3,5})x(\d{3,5})", line)
            if res_match:
                width = int(res_match.group(1))
                height = int(res_match.group(2))
        if "Stream #0:1" in line and "Audio:" in line:
            audio_codec = line.split("Audio:")[1].strip().split(",")[0]

    h, m, s = [float(x) for x in duration_str.replace(",", ".").split(":")]
    duration_sec = h * 3600 + m * 60 + s

    return VideoInfo(
        path=video_path,
        size=os.path.getsize(video_path),
        duration_str=duration_str,
        duration_sec=duration_sec,
        bitrate=bitrate_str,
        video_codec=video_codec,
        audio_codec=audio_codec,
        width=width,
        height=height,
    )


def diagnose_defect(video_path: str) -> "DiagnosisResult":
    """
    简化的 MediaValidator 诊断封装。

    返回 MediaValidator.DiagnosisResult，包含 C2 缺陷检测结果。
    导入 MediaValidator 仅在此处，调用者无需关心。
    """
    from MediaValidator import MediaValidator
    validator = MediaValidator()
    return validator.diagnose(video_path)
