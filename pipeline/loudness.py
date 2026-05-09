"""
响度分析模块 — EBU R128 响度测量与背景乐增益计算。

使用 ffmpeg loudnorm 滤波器 + volumedetect 双重测量，
无需额外 Python 依赖。

方案:
  1. 用 ffmpeg volumedetect 测量原始音频和 no_vocals.wav 的 RMS 电平
  2. 差值即为 Demucs 分离造成的音量损失
  3. 补偿此差值，使背景乐恢复到原始音频的感知响度
  4. 同时支持 loudnorm (EBU R128 / ITU-R BS.1770-4) 精确测量
"""

import json
import os
import re
import subprocess

from pipeline.logger import get_logger

logger = get_logger(__name__)


def measure_rms(wav_path: str) -> float | None:
    """用 ffmpeg volumedetect 测量 RMS 电平 (dB)。"""
    if not os.path.isfile(wav_path):
        logger.warning(f"文件不存在: {wav_path}")
        return None

    from pipeline.utils import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", wav_path,
             "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"volumedetect 执行失败: {e}")
        return None

    stderr = result.stderr
    match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", stderr)
    if match:
        return float(match.group(1))
    logger.warning(f"volumedetect 未找到 mean_volume: {stderr[-200:]}")
    return None


def measure_loudness(wav_path: str) -> dict | None:
    """用 ffmpeg loudnorm 测量音频响度 (EBU R128 / ITU-R BS.1770-4)。

    Returns:
        {"input_i": integrated_LUFS, "input_tp": true_peak_dBTP,
         "input_lra": loudness_range_LU, "input_thresh": noise_threshold_dB}
        失败返回 None
    """
    if not os.path.isfile(wav_path):
        logger.warning(f"文件不存在: {wav_path}")
        return None

    from pipeline.utils import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", wav_path,
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"loudnorm 执行失败: {e}")
        return None

    stderr = result.stderr
    try:
        json_start = stderr.index("{")
        json_str = stderr[json_start:]
        data = json.loads(json_str)
        return {
            "input_i": float(data.get("input_i", -99)),
            "input_tp": float(data.get("input_tp", -99)),
            "input_lra": float(data.get("input_lra", 0)),
            "input_thresh": float(data.get("input_thresh", -70)),
        }
    except (ValueError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"loudnorm JSON 解析失败: {e}")
        return None


def calculate_bgm_gain(
    original_path: str,
    bgm_path: str,
    target_ratio: float = 1.0,
) -> float:
    """计算背景乐需要的增益 (dB)，补偿 Demucs 分离造成的音量损失。

    策略:
      测量原始音频和 no_vocals.wav 的 RMS 电平差，
      差值即为 Demucs 造成的音量改变量。
      按 target_ratio 比例应用补偿（1.0=完全补偿, 0.5=一半补偿）。

    Args:
        original_path: 原始音频路径 (Demucs 分离前)
        bgm_path: 背景乐路径 (no_vocals.wav)
        target_ratio: BGM 音量比例 (0.0~2.0, 1.0=自动补偿)

    Returns:
        增益值 (dB)，直接用于 ffmpeg volume 滤波器
    """
    if target_ratio <= 0:
        return -70.0

    orig_rms = measure_rms(original_path)
    bgm_rms = measure_rms(bgm_path)

    if orig_rms is None or bgm_rms is None:
        logger.warning("响度测量失败，跳过增益补偿")
        return 0.0

    gain_db = orig_rms - bgm_rms
    gain_db *= target_ratio

    gain_db = max(-12.0, min(12.0, gain_db))

    logger.info(
        f"BGM 增益: 原始={orig_rms:.1f} dB, BGM={bgm_rms:.1f} dB, "
        f"补偿={gain_db:+.1f} dB (ratio={target_ratio:.2f})"
    )
    return gain_db


def apply_gain_to_wav(
    src_path: str,
    dst_path: str,
    gain_db: float,
) -> str:
    """对 WAV 文件应用 ffmpeg volume 增益。

    Args:
        src_path: 源 WAV 路径
        dst_path: 目标 WAV 路径
        gain_db: 增益值 (dB)

    Returns:
        dst_path
    """
    if abs(gain_db) < 0.1:
        if src_path != dst_path:
            import shutil
            shutil.copy2(src_path, dst_path)
        return dst_path

    from pipeline.utils import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    gain_str = f"{gain_db:+.1f}dB"
    logger.info(f"应用增益 {gain_str} → {os.path.basename(dst_path)}")

    subprocess.run(
        [ffmpeg, "-y", "-i", src_path,
         "-af", f"volume={gain_str}",
         "-acodec", "pcm_s16le", dst_path],
        capture_output=True, check=True,
    )
    return dst_path
