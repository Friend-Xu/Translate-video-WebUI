"""
Audio time-stretching via Rubber Band (pyrubberband).

Used as a post-processing step when the TTS engine doesn't support native
rate control (e.g. ChatTTS). Rubber Band's phase vocoder with transient
detection preserves speech quality better than video speed adjustment.
"""
from __future__ import annotations

import os

_RUBBERBAND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "tools", "rubberband",
                               "rubberband-3.3.0-gpl-executable-windows")
if os.path.isdir(_RUBBERBAND_DIR):
    os.environ.setdefault("PATH", os.environ.get("PATH", "") +
                          os.pathsep + _RUBBERBAND_DIR)


def stretch_audio(input_path: str, output_path: str, rate: float) -> float:
    """Time-stretch audio using Rubber Band.

    Args:
        input_path: Input WAV file path.
        output_path: Output WAV file path.
        rate: Speed multiplier (>1 = faster/shorter, <1 = slower/longer).

    Returns:
        New duration in seconds.
    """
    import soundfile as sf
    import pyrubberband as pyrb

    y, sr = sf.read(input_path)
    y_stretched = pyrb.time_stretch(y, sr, rate,
        rbargs={'--fine': '', '-3': '', '--formant': ''})
    sf.write(output_path, y_stretched, sr)
    return len(y_stretched) / sr


def compute_stretch_rate(wav_time: float, target_time: float,
                          min_rate: float = 0.6, max_rate: float = 1.5) -> float | None:
    """Compute the stretch rate needed to fit audio into target duration.

    Args:
        wav_time: Current audio duration in seconds.
        target_time: Target duration in seconds.
        min_rate: Maximum speed-up allowed (lower = faster, e.g. 0.6 = 1.67x).
        max_rate: Maximum slow-down allowed.

    Returns:
        Rate value for stretch_audio(), or None if within tolerance.
    """
    if wav_time <= 0 or target_time <= 0:
        return None

    ratio = wav_time / target_time

    # Within 5% — no adjustment needed
    if 0.95 <= ratio <= 1.05:
        return None

    rate = ratio  # ratio > 1 → need to speed up

    # Clamp to safe range
    if rate < min_rate:
        rate = min_rate
    elif rate > max_rate:
        rate = max_rate

    return rate
