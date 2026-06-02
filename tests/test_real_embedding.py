"""
Test: real WeSpeaker embedding extraction vs random placeholder.

Uses Test_JP.mp4 to verify that real embeddings produce meaningful
speaker separation (intra-speaker cosine >> inter-speaker cosine).

Usage: .venv/Scripts/python tests/test_real_embedding.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

AUDIO_PATH = PROJECT_ROOT / "source_file" / "Test_JP.mp4"
MODEL_DIR = PROJECT_ROOT / "models" / "pyannote" / "speaker-diarization-3.1"
EMBEDDING_DIR = PROJECT_ROOT / "models" / "pyannote" / "wespeaker-voxceleb-resnet34-LM"


def extract_vocals(video_path: Path) -> Path:
    """Extract vocals.wav using ffmpeg (mono 16kHz)."""
    vocals = video_path.with_suffix("").parent / f"{video_path.stem}_test_vocals.wav"
    if vocals.exists():
        print(f"[skip] vocals already exist: {vocals}")
        return vocals

    import subprocess
    from pipeline.utils import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()
    print(f"Extracting vocals → {vocals} ...")
    subprocess.run([
        ffmpeg, "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        str(vocals),
    ], check=True, timeout=120, capture_output=True)
    return vocals


def run_diarization(vocals_path: Path) -> list[tuple]:
    """Run pyannote diarization and return speaker timeline."""
    from pipeline.speaker_diarize import SpeakerDiarizer

    diarizer = SpeakerDiarizer(device="cuda")
    timeline = diarizer.run(str(vocals_path), force=False)
    diarizer.unload_model()
    return timeline


def load_embedding_model():
    """Load the WeSpeaker embedding model, reusing pyannote's compat patches."""
    import torch
    from pyannote.audio import Inference
    from pipeline.speaker_diarize import _pyannote_compat_context

    with _pyannote_compat_context(MODEL_DIR):
        model = Inference(
            "pyannote/wespeaker-voxceleb-resnet34-LM",
            device=torch.device("cuda"),
            use_auth_token=False,
        )
    return model


def extract_real_embeddings(embedding_model, vocals_path, timeline):
    """Extract real WeSpeaker embeddings for each speaker turn."""
    from pyannote.core import Segment

    embeddings: dict[str, list[np.ndarray]] = {}
    for spk_id, start, end, conf in timeline:
        try:
            seg = Segment(start, end)
            emb = embedding_model.crop(str(vocals_path), seg)
            # Inference.crop returns numpy array directly
            if isinstance(emb, np.ndarray):
                embeddings.setdefault(spk_id, []).append(emb)
            else:
                embeddings.setdefault(spk_id, []).append(emb.data.cpu().numpy())
        except Exception as e:
            print(f"  [warn] embed failed for {spk_id} {start:.1f}-{end:.1f}: {e}")

    return embeddings


def extract_random_embeddings(timeline):
    """Current broken approach: random 192-dim vectors."""
    embeddings: dict[str, list[np.ndarray]] = {}
    for spk_id, start, end, conf in timeline:
        rng = np.random.RandomState(int(start * 1000))
        embeddings.setdefault(spk_id, []).append(rng.randn(192))
    return embeddings


def compute_pairwise_cosine(embeddings: dict[str, list[np.ndarray]]):
    """Compute intra-speaker vs inter-speaker cosine similarities."""
    intra_sims = []
    inter_sims = []

    spk_centroids = {}
    for spk, embs in embeddings.items():
        arr = np.stack(embs)
        spk_centroids[spk] = arr.mean(axis=0)

    # Intra-speaker: each turn vs centroid of same speaker
    for spk, embs in embeddings.items():
        centroid = spk_centroids[spk]
        for emb in embs:
            sim = np.dot(emb, centroid) / (np.linalg.norm(emb) * np.linalg.norm(centroid) + 1e-10)
            intra_sims.append(float(sim))

    # Inter-speaker: each speaker's centroid vs other speakers' centroids
    speakers = list(spk_centroids.keys())
    for i in range(len(speakers)):
        for j in range(i + 1, len(speakers)):
            a, b = spk_centroids[speakers[i]], spk_centroids[speakers[j]]
            sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10)
            inter_sims.append(float(sim))

    return intra_sims, inter_sims


def test_cluster_quality(embeddings: dict[str, list[np.ndarray]]):
    """Test if k-means on embeddings can recover the original speaker labels."""
    from sklearn.cluster import KMeans

    n_speakers = len(embeddings)
    if n_speakers < 2:
        return None  # cant test with 1 speaker

    # Flatten: each turn is a sample
    all_embs = []
    all_labels = []
    for idx, (spk, embs) in enumerate(embeddings.items()):
        for emb in embs:
            all_embs.append(emb)
            all_labels.append(idx)

    X = np.stack(all_embs)
    y_true = np.array(all_labels)

    km = KMeans(n_clusters=n_speakers, random_state=42, n_init=10)
    y_pred = km.fit_predict(X)

    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    ari = adjusted_rand_score(y_true, y_pred)
    nmi = normalized_mutual_info_score(y_true, y_pred)

    # purity
    n = len(y_true)
    purity = 0.0
    from collections import Counter
    for cluster in range(n_speakers):
        mask = y_pred == cluster
        if mask.sum() == 0:
            continue
        counts = Counter(y_true[mask])
        purity += counts.most_common(1)[0][1]
    purity /= n

    return {"ari": ari, "nmi": nmi, "purity": purity, "n_samples": n, "n_speakers": n_speakers}


def main():
    print("=" * 60)
    print("Test: Real WeSpeaker embedding vs Random placeholder")
    print("=" * 60)

    # 1. Get vocals
    print("\n[1/5] Preparing vocals ...")
    vocals = extract_vocals(AUDIO_PATH)

    # 2. Run diarization
    print("\n[2/5] Running pyannote speaker diarization ...")
    t0 = time.time()
    timeline = run_diarization(vocals)
    dt = time.time() - t0
    n_speakers = len(set(s[0] for s in timeline))
    print(f"  Done in {dt:.1f}s — {len(timeline)} turns, {n_speakers} speakers")

    for spk in sorted(set(s[0] for s in timeline)):
        turns = [s for s in timeline if s[0] == spk]
        total_dur = sum(s[2] - s[1] for s in turns)
        print(f"  {spk}: {len(turns)} turns, {total_dur:.1f}s total")

    # 3. Extract real embeddings
    print("\n[3/5] Loading WeSpeaker model & extracting REAL embeddings ...")
    emb_model = load_embedding_model()
    real_embs = extract_real_embeddings(emb_model, str(vocals), timeline)

    # 4. Extract random embeddings (current behavior)
    print("\n[4/5] Extracting RANDOM embeddings (current placeholder) ...")
    random_embs = extract_random_embeddings(timeline)

    # 5. Compare
    print("\n[5/5] Comparing ...")
    print("-" * 60)

    r_intra, r_inter = compute_pairwise_cosine(real_embs)
    n_intra, n_inter = compute_pairwise_cosine(random_embs)

    print(f"\n{'Metric':<30} {'REAL':>15} {'RANDOM':>15}")
    print("-" * 60)
    print(f"{'Intra-speaker cos (mean)':<30} {np.mean(r_intra):>15.4f} {np.mean(n_intra):>15.4f}")
    print(f"{'Intra-speaker cos (std)':<30} {np.std(r_intra):>15.4f} {np.std(n_intra):>15.4f}")
    print(f"{'Inter-speaker cos (mean)':<30} {np.mean(r_inter):>15.4f} {np.mean(n_inter):>15.4f}")
    print(f"{'Inter-speaker cos (std)':<30} {np.std(r_inter):>15.4f} {np.std(n_inter):>15.4f}")

    # Separation margin
    real_margin = np.mean(r_intra) - np.mean(r_inter)
    random_margin = np.mean(n_intra) - np.mean(n_inter)
    print(f"\n{'Separation margin':<30} {real_margin:>15.4f} {random_margin:>15.4f}")

    # Clustering test
    print(f"\n{'Clustering (if margin > 0.15 = useful)':}")
    r_cluster = test_cluster_quality(real_embs)
    n_cluster = test_cluster_quality(random_embs)

    if r_cluster:
        print(f"  REAL:   ARI={r_cluster['ari']:.3f} NMI={r_cluster['nmi']:.3f} Purity={r_cluster['purity']:.3f}")
    if n_cluster:
        print(f"  RANDOM: ARI={n_cluster['ari']:.3f} NMI={n_cluster['nmi']:.3f} Purity={n_cluster['purity']:.3f}")

    # Verdict
    print("\n" + "=" * 60)
    if real_margin > 0.15 and random_margin < 0.05:
        print("VERDICT: Real embeddings show clear speaker separation.")
        print("         Random placeholder produces NO meaningful clustering.")
        print("         → Fixing this is critical for drift/cluster/voice features.")
    elif real_margin > random_margin + 0.1:
        print("VERDICT: Real embeddings are significantly better than random.")
        print("         → Worth fixing.")
    else:
        print("VERDICT: Unexpected result — check data quality.")
    print("=" * 60)

    # Cleanup
    del emb_model
    import torch
    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
