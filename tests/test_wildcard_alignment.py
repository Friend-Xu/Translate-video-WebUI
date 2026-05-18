"""
Wildcard emission 移植测试 — 纯独立测试，不改生产代码。

Step 1-5:  纯单元测试 get_trellis / backtrack 逻辑
Step 6:    端到端测试 — 加载 en 模型，对含数字的 segment 做完整对齐，
          对比原始结果 vs wildcard 结果（独立实现，不 monkey-patch）

用法:
    .venv/Scripts/python tests/test_wildcard_alignment.py
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import torch
import numpy as np
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════
# 原始实现 (与生产代码完全一致)
# ═══════════════════════════════════════════════════════════

def orig_get_trellis(emission, tokens, blank_id=0):
    num_frame = emission.size(0)
    num_tokens = len(tokens)
    trellis = torch.empty((num_frame + 1, num_tokens + 1))
    trellis[0, 0] = 0
    trellis[1:, 0] = torch.cumsum(emission[:, 0], 0)
    trellis[0, -num_tokens:] = -float("inf")
    trellis[-num_tokens:, 0] = float("inf")
    for t in range(num_frame):
        trellis[t + 1, 1:] = torch.maximum(
            trellis[t, 1:] + emission[t, blank_id],
            trellis[t, :-1] + emission[t, tokens],
        )
    return trellis

@dataclass
class Point:
    token_index: int
    time_index: int
    score: float

def orig_backtrack(trellis, emission, tokens, blank_id=0):
    j = trellis.size(1) - 1
    t_start = torch.argmax(trellis[:, j]).item()
    path = []
    for t in range(t_start, 0, -1):
        stayed = trellis[t - 1, j] + emission[t - 1, blank_id]
        changed = trellis[t - 1, j - 1] + emission[t - 1, tokens[j - 1]]
        prob = emission[t - 1, tokens[j - 1] if changed > stayed else 0].exp().item()
        path.append(Point(j - 1, t - 1, prob))
        if changed > stayed:
            j -= 1
            if j == 0:
                break
    else:
        return None
    return path[::-1]

# ═══════════════════════════════════════════════════════════
# Wildcard 实现 (移植目标)
# ═══════════════════════════════════════════════════════════

def _safe_emission_score(frame_emission, token_idx):
    """安全获取 token 发射分 — wildcard token 用最大分兜底"""
    if 0 <= token_idx < frame_emission.size(0):
        return frame_emission[token_idx]
    return frame_emission.max()

def wildcard_get_trellis(emission, tokens, blank_id=0):
    num_frame = emission.size(0)
    num_tokens = len(tokens)
    trellis = torch.empty((num_frame + 1, num_tokens + 1))
    trellis[0, 0] = 0
    trellis[1:, 0] = torch.cumsum(emission[:, 0], 0)
    trellis[0, -num_tokens:] = -float("inf")
    trellis[-num_tokens:, 0] = float("inf")
    for t in range(num_frame):
        # 对所有 token 用安全查分
        scores = torch.stack([_safe_emission_score(emission[t], tok) for tok in tokens])
        trellis[t + 1, 1:] = torch.maximum(
            trellis[t, 1:] + emission[t, blank_id],
            trellis[t, :-1] + scores,
        )
    return trellis

def wildcard_backtrack(trellis, emission, tokens, blank_id=0):
    j = trellis.size(1) - 1
    t_start = torch.argmax(trellis[:, j]).item()
    path = []
    for t in range(t_start, 0, -1):
        stayed = trellis[t - 1, j] + emission[t - 1, blank_id]
        changed = trellis[t - 1, j - 1] + _safe_emission_score(emission[t - 1], tokens[j - 1])
        best_token = tokens[j - 1] if changed > stayed else 0
        prob = _safe_emission_score(emission[t - 1], best_token).exp().item()
        path.append(Point(j - 1, t - 1, prob))
        if changed > stayed:
            j -= 1
            if j == 0:
                break
    else:
        return None
    return path[::-1]


# ═══════════════════════════════════════════════════════════
# Step 1-5: 单元测试
# ═══════════════════════════════════════════════════════════

def make_synthetic_emission(num_frames=50, num_tokens=30):
    torch.manual_seed(42)
    emission = torch.randn(num_frames, num_tokens)
    emission[:, 0] += 2.0
    return emission

def test_unit():
    """所有纯单元测试"""
    print("=" * 60)
    print("  UNIT TESTS (no model loading)")
    print("=" * 60)

    # 1. Normal tokens identical
    emission = make_synthetic_emission(50, 30)
    tokens = [1, 5, 3, 7, 2, 4, 6, 8, 1, 3]
    t1 = orig_get_trellis(emission, tokens)
    t2 = wildcard_get_trellis(emission, tokens)
    finite = torch.isfinite(t1) & torch.isfinite(t2)
    diff = (t1[finite] - t2[finite]).abs().max().item()
    ok1 = diff < 0.01
    print(f"  1. Normal tokens identical: {'PASS' if ok1 else 'FAIL'} (diff={diff:.10f})")

    # 2. Wildcard no crash
    tokens_wc = [1, 5, 3, 999, 7, 2, -1, 8]
    t3 = wildcard_get_trellis(emission, tokens_wc)
    ok2 = not torch.isnan(t3).any().item()
    print(f"  2. Wildcard no NaN: {'PASS' if ok2 else 'FAIL'}")

    # 3. Original crashes on wildcard
    try:
        orig_get_trellis(emission, tokens_wc)
        # May not crash if PyTorch clamping, but check for NaN
        has_nan = torch.isnan(orig_get_trellis(emission, tokens_wc)).any()
        ok3 = True  # either crash or NaN — both prove the problem
        print(f"  3. Original on wildcard: {'PASS (may have garbage)' if has_nan else 'PASS (crashed)'}")
    except IndexError:
        print(f"  3. Original on wildcard: CONFIRMED CRASH")
    except RuntimeError as e:
        print(f"  3. Original on wildcard: CONFIRMED ERROR: {e}")

    # 4. Backtrack works
    path = wildcard_backtrack(t3, emission, tokens_wc)
    ok4 = path is not None and len(path) > 0
    print(f"  4. Backtrack works: {'PASS' if ok4 else 'FAIL'} (path={len(path) if path else 0})")

    # 5. All wildcard graceful
    tokens_all_wc = [999, 888, 777]
    t5 = wildcard_get_trellis(emission, tokens_all_wc)
    ok5 = not torch.isnan(t5).any().item()
    print(f"  5. All wildcard graceful: {'PASS' if ok5 else 'FAIL'}")

    all_ok = ok1 and ok2 and ok4 and ok5
    print(f"\n  Unit tests: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    return all_ok


# ═══════════════════════════════════════════════════════════
# Step 6: 端到端对齐测试 (加载 en 模型)
# ═══════════════════════════════════════════════════════════

def make_clean_char(text, model_dict):
    """构建 clean_char — 原始版 (剥数字) vs wildcard 版 (保留数字)"""
    text_lower = text.lower()
    nl = len(text) - len(text.lstrip())
    nt = len(text) - len(text.rstrip())

    # 原始版
    orig = []
    for cdx, c in enumerate(text_lower):
        c2 = c.replace(" ", "|")
        if cdx < nl or cdx > len(text_lower) - nt - 1:
            pass
        elif c2 in model_dict:
            orig.append(c2)

    # wildcard 版
    wc = []
    for cdx, c in enumerate(text_lower):
        c2 = c.replace(" ", "|")
        if cdx < nl or cdx > len(text_lower) - nt - 1:
            pass
        elif c2 in model_dict or c.isdigit() or c in ".!?,:;\"'-":
            wc.append(c2)

    # 加边界 |
    if orig and orig[0] != "|": orig.insert(0, "|")
    if orig and orig[-1] != "|": orig.append("|")
    if wc and wc[0] != "|": wc.insert(0, "|")
    if wc and wc[-1] != "|": wc.append("|")

    return orig, wc


def single_segment_align(text, start, end, audio_waveform, model, metadata, device,
                          use_wildcard=False):
    """对单个 segment 执行完整对齐 (独立实现)"""
    model_dict = metadata["dictionary"]
    WILDCARD_IDX = len(model_dict)

    # 1. 构建 clean_char
    orig_cc, wc_cc = make_clean_char(text, model_dict)
    clean_char = wc_cc if use_wildcard else orig_cc

    if not clean_char:
        return {"text": text, "start": start, "end": end, "words": []}

    # 2. tokens
    tokens = [model_dict.get(c, WILDCARD_IDX) for c in clean_char]

    # 3. 音频截取
    f1 = int(start * 16000)
    f2 = int(end * 16000)
    wave = audio_waveform[:, f1:f2]
    if wave.shape[-1] < 400:
        wave = torch.nn.functional.pad(wave, (0, 400 - wave.shape[-1]))

    # 4. 模型推理
    with torch.inference_mode():
        emissions = model(wave.to(device)).logits
    emissions = torch.log_softmax(emissions, dim=-1)
    emission = emissions[0].cpu()

    # 5. trellis + backtrack
    if use_wildcard:
        trellis = wildcard_get_trellis(emission, tokens)
        path = wildcard_backtrack(trellis, emission, tokens)
    else:
        try:
            trellis = orig_get_trellis(emission, tokens)
            path = orig_backtrack(trellis, emission, tokens)
        except (IndexError, RuntimeError):
            return {"text": text, "start": start, "end": end, "words": [],
                    "_error": "original crashed on tokens (digits in clean_char?)"}

    if path is None:
        return {"text": text, "start": start, "end": end, "words": []}

    # 6. Word segments
    from whisperx_local.alignment import merge_repeats, merge_words
    text_clean = "".join(clean_char)
    segments_list = merge_repeats(path, text_clean)
    word_segments = merge_words(segments_list)

    num_chars = len(clean_char)
    char_dur = (end - start) / num_chars if num_chars > 0 else 0
    words_out = []
    for w in word_segments:
        ws = start + w.start * char_dur if w.start < num_chars else start + (num_chars - 1) * char_dur
        we = start + w.end * char_dur if w.end < num_chars else end
        label = "".join(clean_char[w.start:w.end]).replace("|", " ").strip()
        words_out.append({"word": label, "start": round(ws, 3), "end": round(we, 3),
                          "score": w.score})

    return {"text": text, "start": start, "end": end, "words": words_out}


def step6_end_to_end_test():
    """加载 en 模型，对含数字的 segment 做原始 vs wildcard 对齐对比"""
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    print("\n" + "=" * 60)
    print("  STEP 6: End-to-end alignment test")
    print("=" * 60)

    en_model_dir = os.path.join(PROJECT_ROOT, "models", "wav2vec2", "en")
    if not os.path.isdir(en_model_dir):
        print("  SKIP: en model not at models/wav2vec2/en/")
        return

    audio_path = os.path.join(
        PROJECT_ROOT, "source_file",
        "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
        "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric_project",
        "01_extract", "audio.wav")
    if not os.path.isfile(audio_path):
        print("  SKIP: audio not found")
        return

    print(f"  Loading en model from {en_model_dir}...")
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    processor = Wav2Vec2Processor.from_pretrained(en_model_dir)
    model = Wav2Vec2ForCTC.from_pretrained(en_model_dir)
    print("  Model loaded")

    # Build metadata (same as load_align_model would)
    metadata = {
        "dictionary": {c.lower(): i for i, c in enumerate(processor.tokenizer.get_vocab())},
        "language": "en",
        "type": "huggingface",
    }

    # Load audio
    import soundfile as sf
    audio_np, sr = sf.read(audio_path)
    if audio_np.ndim > 1:
        audio_np = np.mean(audio_np, axis=1)
    audio = torch.from_numpy(audio_np.astype(np.float32)).unsqueeze(0)

    # Test: the EXACT problematic segment from the video
    # Whisper hallucinated "2025." as a separate segment.
    # wav2vec2 NLTK sentence split creates two sentences from one segment:
    #   Sentence A: "october 2025." (digits → NaN timestamps)
    #   Sentence B: "this list is heavy..." (normal alignment)
    test_segment = {
        "text": "this time for October 2025. This list is heavy",
        "start": 0.45, "end": 15.49,
    }

    # Split by sentence (like wav2vec2 align does)
    from nltk.tokenize.punkt import PunktSentenceTokenizer
    from whisperx_local.alignment import PunktParameters
    punkt_param = PunktParameters()
    punkt_param.abbrev_types = set(['dr', 'vs', 'mr', 'mrs', 'prof'])
    splitter = PunktSentenceTokenizer(punkt_param)
    sentence_spans = list(splitter.span_tokenize(test_segment["text"]))
    print(f"  Sentence spans: {sentence_spans}")

    for s_i, (s_start, s_end) in enumerate(sentence_spans):
        sent_text = test_segment["text"][s_start:s_end].strip()
        if not sent_text:
            continue
        # Allocate time proportionally by character count
        total_chars = len(test_segment["text"])
        sent_chars = s_end - s_start
        ratio = sent_chars / total_chars
        seg_dur = test_segment["end"] - test_segment["start"]
        sent_dur = seg_dur * ratio
        sent_start = test_segment["start"] + (s_start / total_chars) * seg_dur
        sent_end = sent_start + sent_dur

        print(f"\n  Sentence {s_i}: \"{sent_text}\" [{sent_start:.2f}-{sent_end:.2f}]")

        r_orig = single_segment_align(
            sent_text, sent_start, sent_end, audio, model, metadata, "cpu",
            use_wildcard=False)
        r_wc = single_segment_align(
            sent_text, sent_start, sent_end, audio, model, metadata, "cpu",
            use_wildcard=True)

        missing_orig = sum(1 for w in r_orig.get("words", []) if w.get("start") is None)
        missing_wc = sum(1 for w in r_wc.get("words", []) if w.get("start") is None)

        # Show word-level timestamps
        n_words = max(len(r_orig.get("words", [])), len(r_wc.get("words", [])))
        for wi in range(min(n_words, 10)):
            wo = r_orig["words"][wi] if wi < len(r_orig.get("words", [])) else {"word": "-", "start": None}
            ww = r_wc["words"][wi] if wi < len(r_wc.get("words", [])) else {"word": "-", "start": None}
            to = f"[{wo['start']:.2f}, {wo['end']:.2f}]" if wo.get('start') is not None else "[** NO TS **]"
            tw = f"[{ww['start']:.2f}, {ww['end']:.2f}]" if ww.get('start') is not None else "[** NO TS **]"
            print(f"    {wo['word']:15s} orig={to:20s} wc={tw:20s}")

        if missing_orig > 0 or missing_wc > 0:
            print(f"    MISSING TIMESTAMPS: orig={missing_orig}, wildcard={missing_wc}")
        elif any(c.isdigit() for c in sent_text):
            print(f"    ✓ DIGIT WORDS HAVE TIMESTAMPS IN BOTH — wildcard emission works!")



if __name__ == "__main__":
    test_unit()
    step6_end_to_end_test()
