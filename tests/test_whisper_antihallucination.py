"""
测试 faster-whisper 防幻觉参数的实际效果。

对比两组参数：
  Group A（当前）: beam_size=2, condition_on_previous_text=True, 无惩罚
  Group B（优化）: beam_size=5, condition_on_previous_text=False,
                  repetition_penalty=1.5, no_repeat_ngram_size=2

使用真实视频的音频片段，验证:
  1. 参数是否可以被 faster-whisper 1.2.1 接受（语法正确性）
  2. 幻觉片段（如 "2025." 独立成段）是否减少
  3. 转录质量是否下降

用法:
    .venv/Scripts/python tests/test_whisper_antihallucination.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_PROJECT = os.path.join(
    PROJECT_ROOT, "source_file",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric_project",
)
AUDIO_PATH = os.path.join(VIDEO_PROJECT, "01_extract", "audio.wav")
WHISPER_MODEL = os.path.join(PROJECT_ROOT, "models", "whisper", "turbo")


def load_audio_segment(path: str, start: float, duration: float):
    """加载音频片段（16kHz mono float32）"""
    import soundfile as sf
    import numpy as np
    audio, sr = sf.read(path, start=int(start * 16000),
                        frames=int(duration * 16000))
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    return audio.astype(np.float32)


def transcribe_with_params(audio, params: dict, label: str):
    """用指定参数转录音频，返回 segment 列表"""
    from faster_whisper import WhisperModel

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  参数: beam_size={params.get('beam_size')}, "
          f"condition_on_prev={params.get('condition_on_previous_text')}, "
          f"repetition_penalty={params.get('repetition_penalty')}, "
          f"no_repeat_ngram={params.get('no_repeat_ngram_size')}")
    print(f"{'='*70}")

    # 每次用独立模型实例，避免缓存干扰
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                         cpu_threads=4, num_workers=1)

    t0 = time.time()
    segments, info = model.transcribe(audio, **params)
    results = []
    for seg in segments:
        results.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [{"word": w.word, "start": round(w.start, 2) if w.start else None,
                       "end": round(w.end, 2) if w.end else None}
                      for w in (seg.words or [])],
        })
    elapsed = time.time() - t0

    print(f"  语言: {info.language} (prob={info.language_probability:.2f})")
    print(f"  耗时: {elapsed:.1f}s, 段数: {len(results)}")
    for seg in results:
        dur = seg["end"] - seg["start"]
        flags = []
        if len(seg["text"]) < 5:
            flags.append("SHORT")
        if dur < 0.5 and len(seg["text"]) > 1:
            flags.append("TINY-DUR")
        if dur > 10 and len(seg["text"].split()) < 5:
            flags.append("LONG-DUR")
        flag_str = f"  <-- {' '.join(flags)}" if flags else ""
        print(f"  [{seg['start']:6.2f}-{seg['end']:6.2f}] "
              f"dur={dur:5.2f}s  \"{seg['text'][:80]}\"{flag_str}")

    overlaps = sum(1 for i in range(1, len(results))
                   if results[i - 1]["end"] > results[i]["start"])

    del model
    return results, elapsed, overlaps


def main():
    if not os.path.isfile(AUDIO_PATH):
        print(f"音频文件不存在: {AUDIO_PATH}")
        sys.exit(1)

    print(f"音频: {AUDIO_PATH}")
    print(f"模型: {WHISPER_MODEL}")
    print(f"测试范围: 0s - 35s（包含已知问题区域 'October' → '2025.' → 'This list'）")

    audio = load_audio_segment(AUDIO_PATH, 0, 35)

    base_params = {
        "language": "en",
        "word_timestamps": True,
        "vad_filter": False,
    }

    # ── Group A: 当前参数 ──
    params_a = {
        **base_params,
        "beam_size": 2,
        "condition_on_previous_text": True,
        "repetition_penalty": 1,
        "no_repeat_ngram_size": 0,
    }
    segs_a, time_a, overlaps_a = transcribe_with_params(audio, params_a, "Group A: 当前参数")

    # ── Group B: 优化参数 ──
    params_b = {
        **base_params,
        "beam_size": 5,
        "condition_on_previous_text": False,
        "repetition_penalty": 1.5,
        "no_repeat_ngram_size": 2,
    }
    segs_b, time_b, overlaps_b = transcribe_with_params(audio, params_b, "Group B: 优化参数")

    # ── 对比分析 ──
    print(f"\n{'='*70}")
    print(f"  对比分析")
    print(f"{'='*70}")

    short_a = sum(1 for s in segs_a if len(s["text"]) < 5)
    short_b = sum(1 for s in segs_b if len(s["text"]) < 5)
    tiny_a = sum(1 for s in segs_a if s["end"] - s["start"] < 0.5 and len(s["text"]) > 1)
    tiny_b = sum(1 for s in segs_b if s["end"] - s["start"] < 0.5 and len(s["text"]) > 1)

    print(f"  {'':20s} {'Group A (当前)':>15s} {'Group B (优化)':>15s}")
    print(f"  {'-'*50}")
    print(f"  {'段数':20s} {len(segs_a):15d} {len(segs_b):15d}")
    print(f"  {'耗时':20s} {time_a:14.1f}s {time_b:14.1f}s")
    print(f"  {'短片段 (<5字符)':20s} {short_a:15d} {short_b:15d}")
    print(f"  {'极短时长 (<0.5s)':20s} {tiny_a:15d} {tiny_b:15d}")
    print(f"  {'重叠段':20s} {overlaps_a:15d} {overlaps_b:15d}")

    print(f"\n  文本对比 (前 10 段):")
    for i in range(min(max(len(segs_a), len(segs_b)), 10)):
        text_a = segs_a[i]["text"][:60] if i < len(segs_a) else "(无)"
        text_b = segs_b[i]["text"][:60] if i < len(segs_b) else "(无)"
        match = "✓" if text_a == text_b else "✗"
        print(f"  [{i:2d}] {match} A: {text_a}")
        if text_a != text_b:
            print(f"       B: {text_b}")


if __name__ == "__main__":
    main()
