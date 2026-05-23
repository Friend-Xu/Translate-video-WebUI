"""
VAD A/B 对比测试：外部 Silero VAD vs faster-whisper 内置 VAD

对比指标:
  1. 段数、段长分布
  2. 短幻觉片段数（<5字符独立成段）
  3. 重叠段数
  4. 已知问题区域 "October 2025" 是否拆开
  5. 总耗时

用法:
    .venv/Scripts/python tests/test_vad_comparison.py
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


def load_audio(path: str):
    import soundfile as sf
    import numpy as np
    audio, sr = sf.read(path)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    return audio.astype(np.float32)


def transcribe_with_external_vad(audio, model, sr=16000):
    """Group A: 外部 Silero VAD → whisper vad_filter=False"""
    from SRT.VAD_Segmenter import VAD_Segmenter
    import tempfile
    import soundfile as sf
    import numpy as np

    print("\n  [外部 VAD] Silero VAD 分段...")
    t0 = time.time()

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio, sr)
    tmp.close()

    vad = VAD_Segmenter(tmp.name)
    vad_segments = vad.get_segments(force=True)
    vad_time = time.time() - t0
    os.unlink(tmp.name)

    print(f"  [外部 VAD] 段数: {len(vad_segments)}, 耗时: {vad_time:.1f}s")
    for s, e in vad_segments[:6]:
        print(f"    [{s:7.1f}s - {e:7.1f}s] dur={e-s:6.1f}s")
    if len(vad_segments) > 6:
        print(f"    ... 共 {len(vad_segments)} 段")

    print(f"  [外部 VAD] 转录中...")
    t1 = time.time()
    all_segments = []
    for seg_start, seg_end in vad_segments:
        seg_audio = audio[int(seg_start * sr):int(seg_end * sr)]
        if len(seg_audio) < sr * 0.1:
            continue
        seg_audio = seg_audio.astype(np.float32)
        segments, info = model.transcribe(
            seg_audio, language="en", word_timestamps=True,
            beam_size=5, vad_filter=False,
        )
        for seg in segments:
            all_segments.append({
                "start": round(seg.start + seg_start, 2),
                "end": round(seg.end + seg_start, 2),
                "text": seg.text.strip(),
            })

    transcribe_time = time.time() - t1
    return all_segments, vad_time, transcribe_time


def transcribe_with_builtin_vad(audio, model):
    """Group B: whisper 内置 VAD (vad_filter=True)"""
    print("\n  [内置 VAD] 转录中 (vad_filter=True)...")
    t0 = time.time()

    segments, info = model.transcribe(
        audio, language="en", word_timestamps=True,
        beam_size=5, vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 500,
            "max_speech_duration_s": 20,
            "speech_pad_ms": 400,
        },
    )

    all_segments = []
    for seg in segments:
        all_segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })

    transcribe_time = time.time() - t0
    return all_segments, 0, transcribe_time


def analyze(segments: list, label: str) -> dict:
    durs = [s["end"] - s["start"] for s in segments]
    stats = {
        "label": label, "count": len(segments),
        "short": sum(1 for s in segments if len(s["text"]) < 5),
        "tiny_dur": sum(1 for s in segments if
                        s["end"] - s["start"] < 0.5 and len(s["text"]) > 1),
        "overlaps": sum(1 for i in range(1, len(segments))
                        if segments[i - 1]["end"] > segments[i]["start"]),
        "october_2025_split": False,
        "dur_min": min(durs) if durs else 0,
        "dur_max": max(durs) if durs else 0,
        "dur_avg": sum(durs) / len(durs) if durs else 0,
        "dur_median": sorted(durs)[len(durs) // 2] if durs else 0,
    }
    for i in range(len(segments) - 1):
        a = segments[i]["text"].lower()
        b = segments[i + 1]["text"].lower()
        if "october" in a and b.strip().startswith("2025"):
            stats["october_2025_split"] = True
    return stats


def main():
    if not os.path.isfile(AUDIO_PATH):
        print(f"音频不存在: {AUDIO_PATH}")
        sys.exit(1)

    info = __import__("soundfile").info(AUDIO_PATH)
    total_dur = info.frames / info.samplerate
    print(f"模型: turbo | 时长: {total_dur:.0f}s ({total_dur/60:.1f}min)")

    audio = load_audio(AUDIO_PATH)

    from faster_whisper import WhisperModel
    print("\n加载模型 (GPU)...")
    model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")

    print(f"\n{'='*60}")
    print("  Group A: 外部 Silero VAD → whisper (vad_filter=False)")
    print(f"{'='*60}")
    segs_a, vt_a, tt_a = transcribe_with_external_vad(audio, model)

    print(f"\n{'='*60}")
    print("  Group B: whisper 内置 VAD (vad_filter=True)")
    print(f"{'='*60}")
    segs_b, _, tt_b = transcribe_with_builtin_vad(audio, model)

    del model

    sa = analyze(segs_a, "外部 VAD")
    sb = analyze(segs_b, "内置 VAD")

    total_a = vt_a + tt_a
    total_b = tt_b

    print(f"\n{'='*60}")
    print(f"  对比分析")
    print(f"{'='*60}")
    print(f"  {'指标':30s} {'外部 VAD':>12s} {'内置 VAD':>12s}")
    print(f"  {'-'*54}")
    for key, label in [
        ("count", "段数"), ("short", "短片段 <5字符"),
        ("overlaps", "重叠段"), ("dur_avg", "平均段长 (s)"),
        ("dur_median", "中位段长 (s)"), ("dur_max", "最长段 (s)"),
    ]:
        va, vb = sa[key], sb[key]
        fmt = "{:12.1f}" if isinstance(va, float) else "{:12d}"
        print(f"  {label:30s} " + fmt.format(va) + fmt.format(vb))
    print(f"  {'总耗时 (s)':30s} {total_a:12.1f} {total_b:12.1f}")
    print(f"  October/2025 分割:      外部={sa['october_2025_split']}  内置={sb['october_2025_split']}")

    print(f"\n  ── 外部 VAD 前 8 段 ──")
    for s in segs_a[:8]:
        print(f"  [{s['start']:6.1f}-{s['end']:6.1f}] {s['text'][:80]}")

    print(f"\n  ── 内置 VAD 前 8 段 ──")
    for s in segs_b[:8]:
        print(f"  [{s['start']:6.1f}-{s['end']:6.1f}] {s['text'][:80]}")


if __name__ == "__main__":
    main()
