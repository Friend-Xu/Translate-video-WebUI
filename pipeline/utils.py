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


def safe_replace(src: str, dst: str) -> None:
    """原子替换文件，Windows PermissionError 兼容。

    os.replace 在 Windows 上可能因杀毒软件/文件锁导致 PermissionError。
    此函数在 PermissionError 时回退为先删目标文件再重试。
    """
    try:
        os.replace(src, dst)
    except PermissionError:
        if os.path.isfile(dst):
            os.remove(dst)
        os.replace(src, dst)


def fmt_timestamp(seconds: float) -> str:
    """秒数 → SRT 时间戳格式 HH:MM:SS,mmm"""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
