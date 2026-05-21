"""
SRT timeline emotion extraction from vocals.wav.

Parses SRT → extracts per-segment audio via ffmpeg → runs emotion2vec
→ outputs JSON with per-segment emotion labels + scores + ChatTTS prompts.

Standalone — respects the principle of not modifying pipeline code.

Usage:
    tests\_run_emotion2vec_srt.bat

Output:
    tests/emotion2vec_output/srt_segments/srt_emotions.json
"""

import json
import os
import subprocess
import sys
import time
import numpy as np

PROJ_ROOT = r"D:\Workspace\Translate_video"
AUDIO_PATH = os.path.join(PROJ_ROOT, r"source_file\test_project\01_extract\vocals.wav")
SRT_PATH = os.path.join(PROJ_ROOT, r"source_file\test_project\02_translate\machine.srt")
OUTPUT_DIR = os.path.join(PROJ_ROOT, r"tests\emotion2vec_output\srt_segments")
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "srt_emotions.json")
LOG_PATH = os.path.join(PROJ_ROOT, r"tests\_emotion2vec_srt.log")
MIN_SEGMENT_DUR = 1.0  # skip segments shorter than this

os.makedirs(OUTPUT_DIR, exist_ok=True)

_LOG_FH = open(LOG_PATH, "w", encoding="utf-8", buffering=1)


def _log(*args):
    msg = " ".join(str(a) for a in args)
    _LOG_FH.write(msg + "\n")
    _LOG_FH.flush()
    print(msg, flush=True)


# ── Emotion → ChatTTS prompt mapping (from Phase 2) ──────────

EMOTION_PROMPT_MAP = {
    "生气/angry":     (3, 0, 2),
    "厌恶/disgusted":  (1, 0, 4),
    "恐惧/fearful":   (2, 0, 4),
    "开心/happy":     (6, 1, 4),
    "中立/neutral":   (2, 0, 5),
    "其他/other":     (2, 0, 5),
    "难过/sad":       (1, 0, 6),
    "吃惊/surprised": (4, 0, 3),
    "<unk>":          (2, 0, 5),
}

LABEL_ORDER = [
    "生气/angry", "厌恶/disgusted", "恐惧/fearful",
    "开心/happy", "中立/neutral", "其他/other",
    "难过/sad", "吃惊/surprised", "<unk>",
]


def scores_to_prompt(scores: list) -> str:
    """Weighted-blend scores into a ChatTTS prompt string."""
    oral = sum(
        EMOTION_PROMPT_MAP[label][0] * score
        for label, score in zip(LABEL_ORDER, scores)
        if label in EMOTION_PROMPT_MAP
    )
    laugh = sum(
        EMOTION_PROMPT_MAP[label][1] * score
        for label, score in zip(LABEL_ORDER, scores)
        if label in EMOTION_PROMPT_MAP
    )
    break_ = sum(
        EMOTION_PROMPT_MAP[label][2] * score
        for label, score in zip(LABEL_ORDER, scores)
        if label in EMOTION_PROMPT_MAP
    )
    return f"[oral_{max(0, min(9, int(round(oral))))}][laugh_{max(0, min(2, int(round(laugh))))}][break_{max(0, min(7, int(round(break_))))}]"


# ── SRT Parser ────────────────────────────────────────────────

def _ts_to_sec(ts: str) -> float:
    """Convert HH:MM:SS,mmm to seconds."""
    parts = ts.replace(",", ":").replace(".", ":").split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000.0


def parse_srt(path: str) -> list:
    """Parse SRT into list of {index, start_sec, end_sec, text}. Uses simple
    line-by-line parsing to avoid regex catastrophic backtracking."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().replace("\r\n", "\n").split("\n")

    segments = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Skip empty lines
        if not line:
            i += 1
            continue
        # Try to parse as segment index
        try:
            idx = int(line)
        except ValueError:
            i += 1
            continue

        # Next line should be timestamp
        i += 1
        if i >= len(lines):
            break
        ts_line = lines[i].strip()
        if "-->" not in ts_line:
            continue

        parts = ts_line.split("-->")
        start = _ts_to_sec(parts[0].strip())
        end = _ts_to_sec(parts[1].strip())

        # Collect text lines until empty line or next number
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            # Stop if next line looks like an index
            stripped = lines[i].strip()
            if stripped.isdigit():
                break
            text_lines.append(stripped)
            i += 1

        text = " ".join(text_lines)
        segments.append({
            "index": idx,
            "start_sec": start,
            "end_sec": end,
            "duration": round(end - start, 3),
            "text": text,
        })

    _log(f"Parsed {len(segments)} segments from SRT")
    return segments


# ── Main ──────────────────────────────────────────────────────

def main():
    _log("SRT Timeline Emotion Extraction")
    _log(f"Audio: {AUDIO_PATH}")
    _log(f"SRT:   {SRT_PATH}")
    _log(f"Output: {OUTPUT_JSON}")
    _log("")

    segments = parse_srt(SRT_PATH)
    for seg in segments[:3]:
        _log(f"  [{seg['index']}] {seg['start_sec']:.1f}s-{seg['end_sec']:.1f}s "
             f"({seg['duration']:.1f}s): {seg['text'][:60]}...")

    # Global emotion
    _log("\n--- Global emotion ---")
    from funasr import AutoModel

    model = AutoModel(model="iic/emotion2vec_plus_large", hub="ms", disable_update=True)

    t0 = time.time()
    global_result = model.generate(input=AUDIO_PATH, output_dir=None, granularity="utterance")
    global_elapsed = time.time() - t0

    global_info = {}
    if global_result and len(global_result) > 0:
        item = global_result[0]
        g_scores = item["scores"]
        g_labels = item["labels"]
        top = sorted(zip(g_labels, g_scores), key=lambda x: x[1], reverse=True)
        global_info = {
            "top_emotions": [(l, round(s, 4)) for l, s in top[:3]],
            "prompt": scores_to_prompt(g_scores),
            "elapsed_s": round(global_elapsed, 2),
        }
        _log(f"  Top: {global_info['top_emotions']}")
        _log(f"  Prompt: {global_info['prompt']} ({global_elapsed:.2f}s)")

    # Per-segment extraction
    _log("\n--- Per-segment extraction ---")
    results = []

    for seg in segments:
        start = seg["start_sec"]
        end = seg["end_sec"]
        dur = seg["duration"]

        if dur < MIN_SEGMENT_DUR:
            _log(f"  [{seg['index']}] SKIP ({dur:.1f}s < {MIN_SEGMENT_DUR}s)")
            results.append({
                "index": seg["index"],
                "start_sec": start,
                "end_sec": end,
                "duration": dur,
                "text": seg["text"],
                "emotion": None,
                "prompt": None,
                "warning": f"segment too short ({dur:.1f}s)",
            })
            continue

        seg_wav = os.path.join(OUTPUT_DIR, f"seg_{seg['index']:03d}.wav")
        subprocess.run([
            "ffmpeg", "-y", "-v", "quiet",
            "-i", AUDIO_PATH,
            "-ss", str(start), "-t", str(dur + 0.1),
            "-ac", "1", "-ar", "16000",
            seg_wav,
        ], check=True)

        t0 = time.time()
        result = model.generate(input=seg_wav, output_dir=None, granularity="utterance")
        elapsed = time.time() - t0

        if result and len(result) > 0:
            item = result[0]
            scores = item["scores"]
            labels = item["labels"]
            prompt = scores_to_prompt(scores)
            top = sorted(zip(labels, scores), key=lambda x: x[1], reverse=True)

            entry = {
                "index": seg["index"],
                "start_sec": start,
                "end_sec": end,
                "duration": dur,
                "text": seg["text"],
                "emotion": {
                    "top_label": top[0][0],
                    "top_score": round(top[0][1], 4),
                    "top3": [(l, round(s, 4)) for l, s in top[:3]],
                    "all_scores": [round(s, 4) for s in scores],
                },
                "prompt": prompt,
                "elapsed_s": round(elapsed, 3),
            }
        else:
            entry = {
                "index": seg["index"],
                "start_sec": start,
                "end_sec": end,
                "duration": dur,
                "text": seg["text"],
                "emotion": None,
                "prompt": None,
                "error": "emotion2vec returned no result",
            }

        results.append(entry)
        status = entry["emotion"]["top_label"] if entry["emotion"] else "FAIL"
        _log(f"  [{entry['index']}] {status} -> {entry.get('prompt', 'N/A')} "
             f"({entry.get('elapsed_s', 0):.3f}s)")

    output = {
        "source": {"audio": AUDIO_PATH, "srt": SRT_PATH},
        "global": global_info,
        "segments": results,
        "summary": {
            "total_segments": len(results),
            "extracted": sum(1 for r in results if r.get("emotion")),
            "skipped": sum(1 for r in results if r.get("warning")),
            "failed": sum(1 for r in results if r.get("error")),
        },
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    _log(f"\n--- Summary ---")
    _log(f"  Total: {output['summary']['total_segments']}")
    _log(f"  Extracted: {output['summary']['extracted']}")
    _log(f"  Skipped: {output['summary']['skipped']}")
    _log(f"  Failed: {output['summary']['failed']}")
    _log(f"  Output: {OUTPUT_JSON}")
    _log("Done.")


if __name__ == "__main__":
    main()
