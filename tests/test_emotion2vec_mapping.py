"""
Emotion label → ChatTTS prompt token mapping research.

Tests the mapping from emotion2vec 9-class emotion scores to ChatTTS
[oral_X][laugh_Y][break_Z] prompt tokens. Uses weighted blending so
subtle emotion mixtures produce nuanced prompts.

Standalone — no modification to pipeline code.

Usage:
    tests\_run_emotion2vec_mapping.bat
"""

import json
import os
import sys
import time

PROJ_ROOT = r"D:\Workspace\Translate_video"
AUDIO_PATH = os.path.join(PROJ_ROOT, r"source_file\test_project\01_extract\vocals.wav")
OUTPUT_DIR = os.path.join(PROJ_ROOT, r"tests\emotion2vec_output\mapping")
LOG_PATH = os.path.join(PROJ_ROOT, r"tests\_emotion2vec_mapping.log")

_LOG_FH = open(LOG_PATH, "w", encoding="utf-8", buffering=1)


def _log(*args):
    msg = " ".join(str(a) for a in args)
    _LOG_FH.write(msg + "\n")
    _LOG_FH.flush()
    print(msg, flush=True)


# ── Emotion → ChatTTS prompt mapping ──────────────────────────
# Each emotion maps to (oral, laugh, break)
# oral: 0=formal → 9=colloquial
# laugh: 0=none → 2=frequent
# break: 0=no pauses → 7=long pauses

EMOTION_PROMPT_MAP = {
    "生气/angry":     (3, 0, 2),   # rapid, short pauses
    "厌恶/disgusted":  (1, 0, 4),   # stiff, hesitant
    "恐惧/fearful":   (2, 0, 4),   # somewhat formal, hesitant pauses
    "开心/happy":     (6, 1, 4),   # colloquial, light laughter, moderate pace
    "中立/neutral":   (2, 0, 5),   # current default — balanced
    "其他/other":     (2, 0, 5),   # same as neutral
    "难过/sad":       (1, 0, 6),   # formal, long pauses
    "吃惊/surprised": (4, 0, 3),   # somewhat colloquial, short pauses
    "<unk>":          (2, 0, 5),   # conservative default
}

# Labels order from emotion2vec+ large model output
LABEL_ORDER = [
    "生气/angry", "厌恶/disgusted", "恐惧/fearful",
    "开心/happy", "中立/neutral", "其他/other",
    "难过/sad", "吃惊/surprised", "<unk>",
]


def scores_to_prompt_blended(scores: list) -> tuple:
    """
    Weighted blending: each emotion contributes to the final prompt
    proportional to its confidence score.
    """
    oral = 0.0
    laugh = 0.0
    break_ = 0.0
    contributions = {}

    for label, score in zip(LABEL_ORDER, scores):
        if label in EMOTION_PROMPT_MAP:
            o, l, b = EMOTION_PROMPT_MAP[label]
            w = score
            oral += o * w
            laugh += l * w
            break_ += b * w
            if w > 0.01:
                contributions[label] = {"weight": round(w, 4), "prompt": f"[oral_{o}][laugh_{l}][break_{b}]"}

    oral_i = max(0, min(9, int(round(oral))))
    laugh_i = max(0, min(2, int(round(laugh))))
    break_i = max(0, min(7, int(round(break_))))

    sorted_contribs = dict(
        sorted(contributions.items(), key=lambda x: x[1]["weight"], reverse=True)
    )

    prompt = f"[oral_{oral_i}][laugh_{laugh_i}][break_{break_i}]"
    debug = {
        "prompt": prompt,
        "raw_values": {"oral": round(oral, 3), "laugh": round(laugh, 3), "break": round(break_, 3)},
        "top_emotions": list(sorted_contribs.items())[:3],
    }
    return prompt, debug


def scores_to_prompt_max(scores: list) -> tuple:
    """Hard selection: use the highest-confidence emotion's prompt."""
    max_idx = max(range(len(scores)), key=lambda i: scores[i])
    label = LABEL_ORDER[max_idx]
    o, l, b = EMOTION_PROMPT_MAP[label]
    prompt = f"[oral_{o}][laugh_{l}][break_{b}]"
    return prompt, {"label": label, "score": round(scores[max_idx], 4)}


def test_mapping_table():
    """Show the full mapping table."""
    _log("=" * 60)
    _log("EMOTION -> CHATTS PROMPT MAPPING TABLE")
    _log("=" * 60)
    _log(f"{'Emotion':<22s} {'oral':>5s} {'laugh':>5s} {'break':>5s}  Prompt")
    _log("-" * 60)
    for label in LABEL_ORDER:
        o, l, b = EMOTION_PROMPT_MAP[label]
        prompt = f"[oral_{o}][laugh_{l}][break_{b}]"
        _log(f"{label:<22s} {o:5d} {l:5d} {b:5d}  {prompt}")
    _log("")


def test_pure_emotions():
    """Verify each pure emotion produces the expected prompt."""
    _log("=" * 60)
    _log("PURE EMOTION TESTS (100% confidence)")
    _log("=" * 60)
    for i, label in enumerate(LABEL_ORDER):
        scores = [0.0] * 9
        scores[i] = 1.0
        prompt_blend, dbg_blend = scores_to_prompt_blended(scores)
        prompt_max, dbg_max = scores_to_prompt_max(scores)
        _log(f"  {label:<22s} -> blend: {prompt_blend:<28s}  max: {prompt_max} ({dbg_max['label']})")
    _log("")


def test_blended_emotions():
    """Test blending with mixed emotion scores."""
    _log("=" * 60)
    _log("BLENDED EMOTION TESTS")
    _log("=" * 60)

    # Screenshot: actual vocals.wav utterance scores from test_emotion2vec.py
    vocals_scores = [
        0.0043, 0.0163, 0.0019, 0.2114, 0.1799,
        0.0040, 0.0025, 0.0010, 0.5788,
    ]
    prompt, dbg = scores_to_prompt_blended(vocals_scores)
    _log(f"  vocals.wav (full 41s):")
    _log(f"    Prompt: {prompt}")
    _log(f"    Raw: oral={dbg['raw_values']['oral']}, laugh={dbg['raw_values']['laugh']}, break={dbg['raw_values']['break']}")
    _log(f"    Top: {dbg['top_emotions']}")

    # seg_004 which was 98.5% happy
    happy_scores = [0.0001, 0.0002, 0.0002, 0.9850, 0.0022, 0.0000, 0.0000, 0.0000, 0.0123]
    prompt, dbg = scores_to_prompt_blended(happy_scores)
    _log(f"\n  seg_004 (20-25s, ~98% happy):")
    _log(f"    Prompt: {prompt}")
    _log(f"    Raw: oral={dbg['raw_values']['oral']}, laugh={dbg['raw_values']['laugh']}, break={dbg['raw_values']['break']}")

    # seg_000 which was 91.7% neutral
    neutral_scores = [0.0005, 0.0010, 0.0008, 0.0148, 0.9167, 0.0004, 0.0000, 0.0000, 0.0658]
    prompt, dbg = scores_to_prompt_blended(neutral_scores)
    _log(f"\n  seg_000 (0-5s, ~92% neutral):")
    _log(f"    Prompt: {prompt}")
    _log(f"    Raw: oral={dbg['raw_values']['oral']}, laugh={dbg['raw_values']['laugh']}, break={dbg['raw_values']['break']}")

    # Mixed: 50% happy + 30% neutral + 20% <unk>
    mixed_scores = [0.0, 0.0, 0.0, 0.50, 0.30, 0.0, 0.0, 0.0, 0.20]
    prompt, dbg = scores_to_prompt_blended(mixed_scores)
    _log(f"\n  Synthetic (50% happy + 30% neutral + 20% <unk>):")
    _log(f"    Prompt: {prompt}")

    # Extreme: 80% angry + 20% sad
    angry_sad = [0.80, 0.0, 0.0, 0.0, 0.0, 0.0, 0.20, 0.0, 0.0]
    prompt, dbg = scores_to_prompt_blended(angry_sad)
    _log(f"\n  Synthetic (80% angry + 20% sad):")
    _log(f"    Prompt: {prompt}")
    _log("")


def main():
    _log("Emotion -> ChatTTS Prompt Mapping Research")
    _log(f"Log: {LOG_PATH}")
    _log("")

    test_mapping_table()
    test_pure_emotions()
    test_blended_emotions()

    _log("=" * 60)
    _log("Done.")
    _log("=" * 60)


if __name__ == "__main__":
    main()
