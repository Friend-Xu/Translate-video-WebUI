"""
VAD 性能基准测试 — 对比 JIT vs ONNX，不同 window_size

Usage:
    .venv/Scripts/python tests/benchmark_vad.py source_file/ASEX-007/ASEX-007.mp4
    .venv/Scripts/python tests/benchmark_vad.py source_file/ASEX-007/ASEX-007.mp4 --quick
"""

import argparse
import gc
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import torch
import onnxruntime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

VAD_MODEL_DIR = PROJECT_ROOT / "models" / "vad"
VAD_ONNX_PATH = VAD_MODEL_DIR / "silero_vad.onnx"
VAD_JIT_PATH = VAD_MODEL_DIR / "silero_vad.jit"
SILERO_SR = 16000


def extract_audio_ffmpeg(video_path, output_wav, max_seconds=None):
    import subprocess
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
           "-ar", str(SILERO_SR), "-ac", "1"]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd.append(output_wav)
    subprocess.run(cmd, capture_output=True, check=True)


# ── Post-processing: probability list → segments ──────────────────────
def probs_to_segments(probs, window_size, sr, threshold=0.25,
                      min_speech_ms=250, min_silence_ms=250, speech_pad_ms=30):
    """与 utils_vad.py get_speech_timestamps 完全一致的后处理逻辑"""
    min_speech_samples = sr * min_speech_ms / 1000
    min_silence_samples = sr * min_silence_ms / 1000
    speech_pad_samples = sr * speech_pad_ms / 1000
    audio_length_samples = len(probs) * window_size

    triggered = False
    speeches = []
    current_speech = {}
    neg_threshold = threshold - 0.15
    temp_end = 0

    for i, sp in enumerate(probs):
        if sp >= threshold and temp_end:
            temp_end = 0
        if sp >= threshold and not triggered:
            triggered = True
            current_speech['start'] = window_size * i
            continue
        if sp < neg_threshold and triggered:
            if not temp_end:
                temp_end = window_size * i
            if (window_size * i) - temp_end < min_silence_samples:
                continue
            else:
                current_speech['end'] = temp_end
                if (current_speech['end'] - current_speech['start']) > min_speech_samples:
                    speeches.append(current_speech)
                temp_end = 0
                current_speech = {}
                triggered = False
                continue

    if current_speech and (audio_length_samples - current_speech['start']) > min_speech_samples:
        current_speech['end'] = audio_length_samples
        speeches.append(current_speech)

    for i, s in enumerate(speeches):
        if i == 0:
            s['start'] = int(max(0, s['start'] - speech_pad_samples))
        if i != len(speeches) - 1:
            silence_dur = speeches[i + 1]['start'] - s['end']
            if silence_dur < 2 * speech_pad_samples:
                s['end'] += int(silence_dur // 2)
                speeches[i + 1]['start'] = int(max(0, speeches[i + 1]['start'] - silence_dur // 2))
            else:
                s['end'] = int(min(audio_length_samples, s['end'] + speech_pad_samples))
                speeches[i + 1]['start'] = int(max(0, speeches[i + 1]['start'] - speech_pad_samples))
        else:
            s['end'] = int(min(audio_length_samples, s['end'] + speech_pad_samples))

    return [(s['start'] / sr, s['end'] / sr) for s in speeches]


# ── Approach A: JIT window loop (current implementation) ───────────────
def load_jit():
    m = torch.jit.load(str(VAD_JIT_PATH), map_location="cpu")
    m.eval()
    return m


def vad_jit(audio_1d, model, window_size=512, threshold=0.25):
    model.reset_states()
    probs = []
    total = len(audio_1d)
    for start in range(0, total, window_size):
        chunk = audio_1d[start:start + window_size]
        if len(chunk) < window_size:
            chunk = torch.nn.functional.pad(chunk, (0, window_size - len(chunk)))
        probs.append(model(chunk.unsqueeze(0), 16000).item())
    return probs_to_segments(probs, window_size, 16000, threshold)


# ── Approach B: ONNX per-window (same loop, ONNX backend) ─────────────
def load_onnx(intra_threads=4):
    s = onnxruntime.InferenceSession(str(VAD_ONNX_PATH), providers=['CPUExecutionProvider'])
    s.intra_op_num_threads = intra_threads
    s.inter_op_num_threads = 1
    return s


def vad_onnx(audio_1d, session, window_size=512, threshold=0.25):
    h = np.zeros((2, 1, 64), dtype=np.float32)
    c = np.zeros((2, 1, 64), dtype=np.float32)

    x = audio_1d.unsqueeze(0)
    total = x.shape[1]
    if total % window_size:
        x = torch.nn.functional.pad(x, (0, window_size - (total % window_size)))

    probs = []
    for i in range(0, x.shape[1], window_size):
        chunk = x[:, i:i + window_size]
        ort_in = {'input': chunk.numpy().astype(np.float32), 'h': h, 'c': c,
                   'sr': np.array(16000, dtype=np.int64)}
        out, h, c = session.run(None, ort_in)
        probs.append(float(out.squeeze()))

    return probs_to_segments(probs, window_size, 16000, threshold)


# ── Comparison ────────────────────────────────────────────────────────
def compare_segments(ref, test):
    if len(ref) != len(test):
        return False, f"段数不同: {len(ref)} vs {len(test)}"
    diffs = []
    for (rs, re), (ts, te) in zip(ref, test):
        diffs.append(abs(rs - ts))
        diffs.append(abs(re - te))
    avg = sum(diffs) / len(diffs)
    return avg < 0.15, f"avg_diff={avg:.3f}s, max_diff={max(diffs):.3f}s"


# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--duration", type=float, default=600)
    args = parser.parse_args()

    quick = args.quick
    dur = args.duration if quick else None

    print(f"{'='*65}")
    print(f"VAD Benchmark: {os.path.basename(args.video)}")
    print(f"模式: {'前 {:.0f}s 快速测试'.format(dur) if quick else '全量'}")
    print(f"{'='*65}")

    # Extract audio
    print("\n[1] 提取音频 (ffmpeg 16kHz mono)...")
    t0 = time.time()
    wav = os.path.join(tempfile.gettempdir(), f"vad_bench_{os.urandom(4).hex()}.wav")
    extract_audio_ffmpeg(args.video, wav, max_seconds=dur)
    t_extract = time.time() - t0
    with wave.open(wav, 'rb') as wf:
        audio_dur = wf.getnframes() / wf.getframerate()
    print(f"    耗时: {t_extract:.1f}s, 音频: {audio_dur:.0f}s")

    # Load audio
    print("[2] 加载音频...")
    import soundfile as sf
    import torchaudio
    t0 = time.time()
    audio_np, sr = sf.read(wav)
    if audio_np.ndim > 1:
        audio_np = audio_np.mean(axis=1)
    audio = torch.from_numpy(audio_np).float()
    if sr != SILERO_SR:
        audio = torchaudio.functional.resample(audio.unsqueeze(0), sr, SILERO_SR).squeeze(0)
    t_load = time.time() - t0
    print(f"    耗时: {t_load:.1f}s, samples: {len(audio)}")

    results = {}

    # A: JIT 512 (baseline)
    print("\n[3] JIT window_size=512 (当前默认)...")
    jit = load_jit()
    gc.collect()
    t0 = time.time()
    seg_a = vad_jit(audio, jit, 512)
    t_a = time.time() - t0
    print(f"    耗时: {t_a:.1f}s, 段数: {len(seg_a)}, 倍速: {audio_dur/t_a:.0f}x")
    results['JIT-512'] = {'time': t_a, 'n': len(seg_a), 'seg': seg_a}

    # B: JIT 1536
    print("[4] JIT window_size=1536...")
    jit.reset_states()
    gc.collect()
    t0 = time.time()
    seg_b = vad_jit(audio, jit, 1536)
    t_b = time.time() - t0
    print(f"    耗时: {t_b:.1f}s, 段数: {len(seg_b)}, 倍速: {audio_dur/t_b:.0f}x")
    results['JIT-1536'] = {'time': t_b, 'n': len(seg_b), 'seg': seg_b}

    # C: ONNX 512
    print("[5] ONNX window_size=512...")
    onx = load_onnx()
    gc.collect()
    t0 = time.time()
    seg_c = vad_onnx(audio, onx, 512)
    t_c = time.time() - t0
    print(f"    耗时: {t_c:.1f}s, 段数: {len(seg_c)}, 倍速: {audio_dur/t_c:.0f}x")
    results['ONNX-512'] = {'time': t_c, 'n': len(seg_c), 'seg': seg_c}

    # D: ONNX 1536
    print("[6] ONNX window_size=1536...")
    gc.collect()
    t0 = time.time()
    seg_d = vad_onnx(audio, onx, 1536)
    t_d = time.time() - t0
    print(f"    耗时: {t_d:.1f}s, 段数: {len(seg_d)}, 倍速: {audio_dur/t_d:.0f}x")
    results['ONNX-1536'] = {'time': t_d, 'n': len(seg_d), 'seg': seg_d}

    # Summary
    print(f"\n{'='*65}")
    print(f"{'方案':<16} {'耗时':>8} {'段数':>6} {'加速比':>8} {'倍速':>8} {'一致性':>12}")
    print(f"{'-'*65}")
    baseline = results['JIT-512']['time']
    ref_seg = results['JIT-512']['seg']
    for name, r in results.items():
        speedup = baseline / r['time']
        rt = audio_dur / r['time']
        ok, msg = compare_segments(ref_seg, r['seg'])
        status = '✓ ' + msg if ok else '✗ ' + msg
        print(f"{name:<16} {r['time']:>7.1f}s {r['n']:>5} {speedup:>7.1f}x {rt:>7.0f}x {status:<35}")

    os.remove(wav)


if __name__ == "__main__":
    main()
