"""
Compare three approaches for fixing wav2vec2 alignment truncation:

  A: Split long segments into sub-10s chunks before alignment (VAD-slice approach)
  B: Add word boundary "|" symbols to alignment text (whisperX PR #1019)
  C: Current behavior (one giant 40s segment) — baseline

Usage:
    python tests/compare_alignment_fixes.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import numpy as np
import soundfile as sf

AUDIO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "source_file", "test_out", "test.wav")
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models", "whisper", "turbo")
ALIGN_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "models", "wav2vec2", "en")

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)  # whisperx_local is a package under project root


def load_audio():
    audio, sr = sf.read(AUDIO_PATH)
    return audio.astype(np.float32), sr


def load_align_model():
    from whisperx_local.alignment import load_align_model as lam
    if os.path.isdir(ALIGN_MODEL_PATH) and os.path.isfile(
        os.path.join(ALIGN_MODEL_PATH, "config.json")
    ):
        return lam(language_code="en", device="cuda", model_name=ALIGN_MODEL_PATH)
    return lam(language_code="en", device="cuda")


def run_alignment(segments, align_model, align_metadata, audio):
    from whisperx_local.alignment import align
    result = align(segments, align_model, align_metadata,
                   audio, device="cuda", return_char_alignments=False)
    return result.get("segments", segments)


def get_stats(name, segments):
    if not segments:
        return 0, 0, 0
    return segments[0]["start"], segments[-1]["end"], \
           sum(len(s.get("words", [])) for s in segments)


def split_long_segments(segments, max_dur=10.0):
    """Split segments > max_dur at natural word gaps or evenly by time."""
    result = []
    for seg in segments:
        duration = seg["end"] - seg["start"]
        if duration <= max_dur:
            result.append(seg)
            continue

        words = seg.get("words", [])
        if len(words) < 2:
            mid = seg["start"] + duration / 2
            result.append({**seg, "end": mid})
            result.append({**seg, "start": mid, "words": []})
            continue

        # Split evenly by word count to keep chunks ~max_dur
        words_per_chunk = max(1, len(words) // max(2, int(duration / max_dur) + 1))
        for chunk_start_idx in range(0, len(words), words_per_chunk):
            chunk_end_idx = min(chunk_start_idx + words_per_chunk, len(words))
            chunk_words = words[chunk_start_idx:chunk_end_idx]
            if not chunk_words:
                continue
            chunk_text = " ".join(w.get("word", "") for w in chunk_words)
            c_start = chunk_words[0].get("start", seg["start"])
            c_end = chunk_words[-1].get("end", seg["start"])
            result.append({
                "text": chunk_text, "start": c_start, "end": c_end,
                "words": chunk_words,
            })
    return result


def align_with_boundary_fix(audio_1d, raw_segments, model, metadata):
    """Run alignment with PR #1019 boundary symbol fix (| at start/end)."""
    import torch
    import pandas as pd
    from whisperx_local.alignment import (
        get_trellis, backtrack_beam, merge_repeats, interpolate_nans,
    )
    from whisperx_local.alignment import LANGUAGES_WITHOUT_SPACES, PUNKT_ABBREVIATIONS
    from nltk.tokenize.punkt import PunktParameters, PunktSentenceTokenizer

    model_dictionary = metadata["vocab"]
    model_type = metadata["type"]

    # Preprocess with boundary symbols
    processed = []
    for seg in raw_segments:
        text = seg["text"]
        num_leading = len(text) - len(text.lstrip())
        num_trailing = len(text) - len(text.rstrip())

        clean_char, clean_cdx = [], []
        for cdx, char in enumerate(text):
            char_ = char.lower().replace(" ", "|")
            if cdx < num_leading or cdx > len(text) - num_trailing - 1:
                pass
            elif char_ in model_dictionary:
                clean_char.append(char_)
                clean_cdx.append(cdx)

        # PR #1019: add leading and trailing word boundary
        if clean_char and clean_char[0] != "|":
            clean_char.insert(0, "|")
        if clean_char and clean_char[-1] != "|":
            clean_char.append("|")

        punkt_param = PunktParameters()
        punkt_param.abbrev_types = set(PUNKT_ABBREVIATIONS)
        sentence_splitter = PunktSentenceTokenizer(punkt_param)
        sentence_spans = list(sentence_splitter.span_tokenize(text))

        seg_copy = dict(seg)
        seg_copy["clean_char"] = clean_char
        seg_copy["clean_cdx"] = clean_cdx
        seg_copy["sentence_spans"] = sentence_spans
        processed.append(seg_copy)

    # Alignment proper (same as original align())
    aligned_segments = []
    for segment in processed:
        t1, t2, text = segment["start"], segment["end"], segment["text"]
        aligned_seg = {"start": t1, "end": t2, "text": text, "words": [], "chars": None}

        clean_char = segment.get("clean_char", [])
        if len(clean_char) == 0:
            aligned_segments.append(aligned_seg)
            continue

        text_clean = "".join(clean_char)
        tokens = [model_dictionary.get(c, -1) for c in text_clean]

        f1, f2 = int(t1 * 16000), int(t2 * 16000)
        waveform_segment = audio_1d[:, f1:f2]

        if waveform_segment.shape[-1] < 400:
            waveform_segment = torch.nn.functional.pad(
                waveform_segment, (0, 400 - waveform_segment.shape[-1])
            )
            lengths = torch.as_tensor([waveform_segment.shape[-1]]).to("cuda")
        else:
            lengths = None

        with torch.inference_mode():
            if model_type == "torchaudio":
                emissions, _ = model(waveform_segment.to("cuda"), lengths=lengths)
            else:
                emissions = model(waveform_segment.to("cuda")).logits
            emissions = torch.log_softmax(emissions, dim=-1)

        emission = emissions[0].cpu().detach()

        blank_id = 0
        for char, code in model_dictionary.items():
            if char in ("[pad]", "<pad>"):
                blank_id = code

        trellis = get_trellis(emission, tokens, blank_id)
        path = backtrack_beam(trellis, emission, tokens, blank_id, beam_width=2)

        if path is None:
            aligned_segments.append(aligned_seg)
            continue

        char_segments = merge_repeats(path, text_clean)
        duration = t2 - t1
        ratio = duration * waveform_segment.size(0) / (trellis.size(0) - 1)

        char_arr = []
        for ci, cs in enumerate(char_segments):
            c = text_clean[ci] if ci < len(text_clean) else ""
            char_arr.append({
                "char": c, "start": round(cs.start * ratio + t1, 3),
                "end": round(cs.end * ratio + t1, 3), "score": cs.score,
            })
        char_arr = pd.DataFrame(char_arr)

        # Build word segments (simplified)
        sentence_spans = segment.get("sentence_spans", [(0, len(text))])
        for sstart, send in sentence_spans:
            s_chars = char_arr.iloc[sstart:send+1] if send < len(char_arr) else char_arr.iloc[sstart:]
            if len(s_chars) == 0:
                continue
            s_start = s_chars["start"].min()
            s_end = s_chars["end"].max()
            aligned_segments.append({
                "text": text[sstart:send],
                "start": s_start, "end": s_end,
                "words": [],
            })

    return aligned_segments


def main():
    print("=" * 70)
    print("  Alignment Fix: Split vs Boundary Symbols vs Baseline")
    print("=" * 70)

    print("\nLoading audio and models...")
    audio_1d, sr = load_audio()
    audio_2d = audio_1d[np.newaxis, :]
    audio_dur = audio_1d.shape[0] / sr
    print(f"  Audio: {audio_dur:.3f}s")

    from faster_whisper import WhisperModel
    wh_model = WhisperModel(MODEL_PATH, device="cuda", compute_type="float16",
                            cpu_threads=0, num_workers=1)
    raw_segs, _ = wh_model.transcribe(audio_1d, language="en", word_timestamps=True,
                                       beam_size=2, vad_filter=False)
    raw_segments = []
    for seg in raw_segs:
        words = [{"word": w.word.strip(), "start": round(w.start, 3),
                  "end": round(w.end, 3)} for w in (seg.words or [])]
        raw_segments.append({"text": seg.text, "start": round(seg.start, 3),
                             "end": round(seg.end, 3), "words": words})

    raw_end = raw_segments[-1]["end"]
    total_words = sum(len(s["words"]) for s in raw_segments)
    print(f"  Raw whisper: {len(raw_segments)} segments, {total_words} words, ends at {raw_end:.3f}s")

    # Build merged segment (simulating _group_into_segments)
    all_words = []
    for seg in raw_segments:
        all_words.extend(seg["words"])
    merged = {"text": " ".join(w["word"] for w in all_words),
              "start": all_words[0]["start"], "end": all_words[-1]["end"],
              "words": all_words}
    print(f"  Merged: 1 segment, [{merged['start']:.3f} - {merged['end']:.3f}] "
          f"({merged['end']-merged['start']:.1f}s)")

    t0 = time.time()
    align_model, align_metadata = load_align_model()
    print(f"  Align model loaded in {time.time() - t0:.1f}s")

    # ── C: Baseline ──
    print("\n" + "-" * 70)
    print("  C: BASELINE — one {:.0f}s segment".format(merged["end"] - merged["start"]))
    print("-" * 70)
    t0 = time.time()
    aligned_c = run_alignment([copy.deepcopy(merged)], align_model, align_metadata, audio_2d)
    c_start, c_end, c_words = get_stats("C", aligned_c)
    print(f"  Coverage: [{c_start:.3f} - {c_end:.3f}s], {c_words} words, "
          f"loss={raw_end-c_end:.3f}s, time={time.time()-t0:.1f}s")

    # ── A: Split ──
    print("\n" + "-" * 70)
    print("  A: SPLIT — split into <10s chunks before alignment")
    print("-" * 70)
    split_segs = split_long_segments([merged])
    print(f"  Split into {len(split_segs)} chunks:")
    for s in split_segs:
        print(f"    [{s['start']:.3f} - {s['end']:.3f}] ({s['end']-s['start']:.1f}s, "
              f"{len(s.get('words',[]))} words)")
    t0 = time.time()
    aligned_a = run_alignment([copy.deepcopy(s) for s in split_segs], align_model, align_metadata, audio_2d)
    a_start, a_end, a_words = get_stats("A", aligned_a)
    print(f"  Coverage: [{a_start:.3f} - {a_end:.3f}s], {a_words} words, "
          f"loss={raw_end-a_end:.3f}s, time={time.time()-t0:.1f}s")

    # ── B: Boundary symbols ──
    print("\n" + "-" * 70)
    print("  B: BOUNDARY — add | symbols (PR #1019)")
    print("-" * 70)
    t0 = time.time()
    try:
        aligned_b = align_with_boundary_fix(audio_2d, [merged], align_model, align_metadata)
        b_start, b_end, b_words = get_stats("B", aligned_b)
        print(f"  Coverage: [{b_start:.3f} - {b_end:.3f}s], {b_words} words, "
              f"loss={raw_end-b_end:.3f}s, time={time.time()-t0:.1f}s")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        b_end = 0

    # ── Comparison ──
    print("\n" + "=" * 70)
    print("  RESULT")
    print("=" * 70)
    print(f"\n  Raw whisper ends at: {raw_end:.3f}s")
    print(f"  {'Approach':<35} {'End':>8} {'Loss':>8} {'Verdict':>10}")
    print(f"  {'-'*65}")
    for name, end_val in [("C: Baseline (current pipeline)", c_end),
                           ("A: Split before alignment", a_end),
                           ("B: Boundary symbols (PR #1019)", b_end)]:
        loss = raw_end - end_val
        verdict = "OK" if loss < 0.5 else ("WARN" if loss < 2.0 else "FAIL")
        print(f"  {name:<35} {end_val:>8.3f}s {loss:>7.3f}s {verdict:>10}")

    # Best approach
    losses = {"Split": raw_end - a_end, "Boundary": raw_end - b_end, "Baseline": raw_end - c_end}
    best = min(losses, key=losses.get)
    print(f"\n  Best approach: {best} (loss={losses[best]:.3f}s)")


if __name__ == "__main__":
    main()
