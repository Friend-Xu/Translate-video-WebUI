"""
视频/音频通用工具函数 — 文件大小格式化、时长格式化、ffmpeg 路径获取等
"""
import os
import imageio_ffmpeg


def get_ffmpeg_exe() -> str:
    """获取 ffmpeg 可执行文件路径，并确保其目录在 PATH 中"""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    ff_dir = os.path.dirname(ff)
    if ff_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")
    return ff


def format_size(b: int) -> str:
    """字节数 → 人类可读 (B/KB/MB)"""
    if b < 1024:
        return f"{b}B"
    elif b < 1024 ** 2:
        return f"{b / 1024:.1f}KB"
    else:
        return f"{b / 1024 ** 2:.1f}MB"


def fmt_time(s: float) -> str:
    """秒数 → HH:MM:SS"""
    h, r = divmod(int(s), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_timestamp(seconds: float) -> str:
    """秒数 → SRT 时间戳格式 HH:MM:SS,mmm"""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
