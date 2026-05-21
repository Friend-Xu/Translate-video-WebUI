"""
Standalone emotion2vec test — test emotion extraction from speech audio.

Uses Alibaba DAMO's emotion2vec+ model to extract emotion labels and embedding
vectors. All output logged to file for reliable capture.

Usage:
    tests\_run_emotion2vec.bat
"""

import os
import sys
import time
import json
import numpy as np

# ── Config ──────────────────────────────────────────
PROJ_ROOT = r"D:\Workspace\Translate_video"
AUDIO_PATH = os.path.join(PROJ_ROOT, r"source_file\test_project\01_extract\vocals.wav")
OUTPUT_DIR = os.path.join(PROJ_ROOT, r"tests\emotion2vec_output")
LOG_PATH = os.path.join(PROJ_ROOT, r"tests\_emotion2vec_test.log")
MODEL_NAME = "iic/emotion2vec_plus_large"  # 5 classes: angry/happy/neutral/sad/unknown

os.makedirs(OUTPUT_DIR, exist_ok=True)

_LOG_FH = open(LOG_PATH, "w", encoding="utf-8", buffering=1)


def _log(*args):
    """Print to both log file and stdout."""
    msg = " ".join(str(a) for a in args)
    _LOG_FH.write(msg + "\n")
    _LOG_FH.flush()
    print(msg)
    sys.stdout.flush()


def test_utterance_level(model, audio_path: str):
    """Extract one emotion vector for the entire utterance."""
    _log("\n" + "=" * 60)
    _log("TEST 1: Utterance-level emotion extraction")
    _log("=" * 60)

    t0 = time.time()
    result = model.generate(
        input=audio_path,
        output_dir=os.path.join(OUTPUT_DIR, "utterance"),
        granularity="utterance",
        extract_embedding=True,
    )
    _log(f"Time: {time.time() - t0:.2f}s")
    _log(f"Result: {json.dumps(result, indent=2, ensure_ascii=False, default=str)[:2000]}")

    if result and len(result) > 0:
        item = result[0]
        _log(f"Keys: {list(item.keys()) if isinstance(item, dict) else 'N/A'}")

        emb_dir = os.path.join(OUTPUT_DIR, "utterance")
        if os.path.isdir(emb_dir):
            for f in os.listdir(emb_dir):
                fpath = os.path.join(emb_dir, f)
                if f.endswith(".npy"):
                    emb = np.load(fpath)
                    _log(f"Embedding: {f} shape={emb.shape} dtype={emb.dtype}")
                    _log(f"  min={emb.min():.4f}  max={emb.max():.4f}  mean={emb.mean():.4f}")
                    flat = emb.flatten()
                    _log(f"  first 10 dims: {flat[:10].tolist()}")

    return result


def test_frame_level(model, audio_path: str):
    """Extract frame-level emotion features (50Hz)."""
    _log("\n" + "=" * 60)
    _log("TEST 2: Frame-level emotion extraction (50 fps)")
    _log("=" * 60)

    t0 = time.time()
    result = model.generate(
        input=audio_path,
        output_dir=os.path.join(OUTPUT_DIR, "frame"),
        granularity="frame",
        extract_embedding=True,
    )
    _log(f"Time: {time.time() - t0:.2f}s")

    frame_dir = os.path.join(OUTPUT_DIR, "frame")
    if os.path.isdir(frame_dir):
        for f in sorted(os.listdir(frame_dir)):
            fpath = os.path.join(frame_dir, f)
            if f.endswith(".npy"):
                emb = np.load(fpath)
                _log(f"Frame embedding: {f} shape={emb.shape} dtype={emb.dtype}")

    return result


def test_short_segments(model, audio_path: str, segment_dur: float = 5.0):
    """Extract emotion from short audio segments (simulate TTS subtitle chunks)."""
    _log("\n" + "=" * 60)
    _log(f"TEST 3: Short-segment extraction (~{segment_dur}s chunks)")
    _log("=" * 60)

    import subprocess

    total_dur = float(subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path], text=True
    ).strip())
    _log(f"Total audio duration: {total_dur:.1f}s")

    results = []
    seg_dir = os.path.join(OUTPUT_DIR, "segments")
    os.makedirs(seg_dir, exist_ok=True)

    for seg_idx, start in enumerate(np.arange(0, total_dur - segment_dur, segment_dur)):
        if seg_idx >= 5:
            break
        end = min(start + segment_dur, total_dur)
        seg_path = os.path.join(seg_dir, f"seg_{seg_idx:03d}_{start:.1f}-{end:.1f}.wav")

        subprocess.run([
            "ffmpeg", "-y", "-v", "quiet",
            "-i", audio_path,
            "-ss", str(start), "-t", str(segment_dur),
            "-ac", "1", "-ar", "16000",
            seg_path
        ], check=True)

        t0 = time.time()
        result = model.generate(
            input=seg_path,
            output_dir=os.path.join(seg_dir, f"emb_{seg_idx:03d}"),
            granularity="utterance",
            extract_embedding=True,
        )
        elapsed = time.time() - t0

        emotion_info = "N/A"
        if result and len(result) > 0:
            emotion_info = str(result[0])[:300]

        _log(f"  seg_{seg_idx:03d} [{start:.1f}s-{end:.1f}s] {elapsed:.2f}s -> {emotion_info}")
        results.append({"start": start, "end": end, "result": result})

    return results


def summarize():
    """Compare embeddings across segments."""
    _log("\n" + "=" * 60)
    _log("SUMMARY: Embedding similarity across segments")
    _log("=" * 60)

    emb_dir = os.path.join(OUTPUT_DIR, "segments")
    if not os.path.isdir(emb_dir):
        _log("No segment embeddings directory found")
        return

    embeddings = []
    labels = []

    for d in sorted(os.listdir(emb_dir)):
        dpath = os.path.join(emb_dir, d)
        if not os.path.isdir(dpath) or not d.startswith("emb_"):
            continue
        for f in os.listdir(dpath):
            if f.endswith(".npy"):
                emb = np.load(os.path.join(dpath, f))
                embeddings.append(emb.flatten())
                labels.append(d)
                break

    if len(embeddings) < 2:
        _log(f"Not enough segment embeddings for comparison (got {len(embeddings)})")
        return

    embeddings = np.stack(embeddings)
    _log(f"Collected {len(embeddings)} segment embeddings, shape={embeddings.shape}")

    from numpy.linalg import norm
    sims = np.zeros((len(embeddings), len(embeddings)))
    for i in range(len(embeddings)):
        for j in range(len(embeddings)):
            sims[i, j] = np.dot(embeddings[i], embeddings[j]) / (
                norm(embeddings[i]) * norm(embeddings[j]) + 1e-8
            )

    _log("\nCosine similarity matrix:")
    short_labels = [l.split("_")[1] for l in labels]
    header = "        " + "  ".join(short_labels)
    _log(header)
    for i, label in enumerate(short_labels):
        row = "  ".join(f"{sims[i][j]:.3f}" for j in range(len(short_labels)))
        _log(f"  {label}: {row}")

    dim_vars = embeddings.var(axis=0)
    top_dims = np.argsort(dim_vars)[-10:][::-1]
    _log(f"\nTop-10 most variable dimensions: {top_dims.tolist()}")
    _log(f"Variance range: [{dim_vars.min():.6f}, {dim_vars.max():.6f}]")


def main():
    _log(f"Audio: {AUDIO_PATH}")
    _log(f"Model: {MODEL_NAME}")
    _log(f"Output dir: {OUTPUT_DIR}")
    _log(f"Log file: {LOG_PATH}")

    from funasr import AutoModel

    _log("\nLoading emotion2vec model (first run downloads from ModelScope)...")
    t0 = time.time()
    model = AutoModel(
        model=MODEL_NAME,
        hub="ms",
        disable_update=True,
    )
    _log(f"Model loaded in {time.time() - t0:.1f}s")

    test_utterance_level(model, AUDIO_PATH)
    test_frame_level(model, AUDIO_PATH)
    test_short_segments(model, AUDIO_PATH)
    summarize()

    _log("\n" + "=" * 60)
    _log(f"Done. Output: {OUTPUT_DIR}")
    _log(f"Log: {LOG_PATH}")
    _log("=" * 60)


if __name__ == "__main__":
    main()
