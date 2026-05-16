"""
定点重新识别模块 — 用 faster-whisper 重转录验证可疑字幕

对指定字幕索引所对应的时间段，提取音频并重新跑 faster-whisper 转录，
对比新版与原版，用于发现 whisper 识别错误。

与提取管线共享模型（faster-whisper-small int8, cpu），不额外加载 whisperx。

用法:
    from TargetedRecognizer import targeted_retranscribe
    results = targeted_retranscribe(
        srt_path="source_file/LongTest1.srt",
        audio_path="source_file/longtest1_out/LongTest1.wav",
        indices_to_check=[25, 84],
    )
    for idx, r in results.items():
        if r["changed"]:
            print(f"索引 {idx}: {r['original']}  →  {r['retranscribed']}")

CLI:
    python -m SRT.TargetedRecognizer <srt> <wav> [索引...]
    # 也可从 SRT_Translator 的语义核验日志自动抓取低质索引:
    python -m SRT.TargetedRecognizer <srt> <wav>
"""

import os
import sys
import json
import time
import gc
import logging
from typing import List, Dict, Optional, Tuple

import pysrt
import numpy as np

logger = logging.getLogger("TargetedRecognizer")

# ── 全局模型缓存（避免反复加载） ──────────────────────────
_WHISPER_MODEL_CACHE: dict = {}


def _ensure_hf_env():
    """设好 HuggingFace 镜像 + 本地模型缓存"""
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    if not os.environ.get("HF_HUB_DISABLE_SYMLINKS_WARNING"):
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ.setdefault("TORCH_HOME", os.path.join(_project_root, "models"))


def _get_whisper_model(model_size: str = "small",
                       device: str = "cpu",
                       compute_type: str = "int8"):
    """懒加载 faster-whisper 模型，与 extract_subtitles 共享缓存策略"""
    key = f"{model_size}_{device}_{compute_type}"
    if key not in _WHISPER_MODEL_CACHE:
        _ensure_hf_env()
        _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _whisper_root = os.path.join(_project_root, "models", "whisper")
        os.makedirs(_whisper_root, exist_ok=True)
        from faster_whisper import WhisperModel
        # Prevent HF download when model already cached locally
        local_model_dir = os.path.join(_whisper_root, model_size)
        if os.path.isdir(local_model_dir) and os.path.isfile(os.path.join(local_model_dir, "model.bin")):
            os.environ["HF_HUB_OFFLINE"] = "1"
        logger.info(f"加载 faster-whisper 模型: {model_size} ({device}, {compute_type})")
        t0 = time.time()
        model = WhisperModel(model_size, device=device, compute_type=compute_type,
                             download_root=_whisper_root)
        logger.info(f"  加载完成，耗时: {time.time()-t0:.1f}s")
        _WHISPER_MODEL_CACHE[key] = model
    return _WHISPER_MODEL_CACHE[key]


def _extract_audio_segment(audio_path: str, start_sec: float, end_sec: float,
                           target_sr: int = 16000) -> Tuple[np.ndarray, int]:
    """从音频文件中提取指定时间段，返回 (audio_np_array, sample_rate)"""
    import torchaudio
    import torch

    info = torchaudio.info(audio_path)
    sr = info.sample_rate
    start_sample = int(start_sec * sr)
    num_samples = int((end_sec - start_sec) * sr)

    wav, sr_loaded = torchaudio.load(
        audio_path,
        frame_offset=start_sample,
        num_frames=num_samples,
    )

    if sr_loaded != target_sr:
        import torchaudio.functional as F
        wav = F.resample(wav, sr_loaded, target_sr)
        sr_loaded = target_sr

    if wav.shape[0] > 1:
        wav = wav.mean(dim=0)
    else:
        wav = wav.squeeze(0)

    return wav.numpy().astype(np.float32), sr_loaded


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """计算两个字符串的编辑距离比例，1.0 = 完全相同"""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    n, m = len(s1), len(s2)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            temp = dp[j]
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = temp
    return 1.0 - (dp[m] / max(n, m, 1))


def _normalize_text(text: str) -> str:
    """标准化文本用于比较：NFKC 统一 + 空白压缩"""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    text = " ".join(text.split())
    return text.strip()


def detect_language_from_audio(audio_path: str,
                               model_size: str = "small") -> Tuple[str, float]:
    """从音频文件中提取前 30 秒检测语言（与转录管线共用逻辑）

    Returns:
        (language_code, probability)
    """
    model = _get_whisper_model(model_size)

    # 提取前 30 秒用于检测
    audio_data, sr = _extract_audio_segment(audio_path, 0, min(30.0, 10 * 60))
    seg_gen, detect_info = model.transcribe(audio_data, beam_size=5)
    # 消费生成器以触发检测
    for _ in seg_gen:
        pass
    language = detect_info.language if detect_info else "ja"
    lang_prob = getattr(detect_info, "language_probability", 0.0)
    del audio_data, seg_gen
    gc.collect()
    return language, lang_prob


def retranscribe_single(audio_path: str, sub_index: int,
                        start_sec: float, end_sec: float,
                        original_text: str,
                        language: str = "ja",
                        model_size: str = "small") -> Optional[dict]:
    """
    对一段音频做定点重新转录。

    使用 faster-whisper 直接转录音频段（无需 VAD，目标明确），
    返回词级结果并与原版文本比较。

    Args:
        audio_path:     WAV 音频路径
        sub_index:      字幕索引（1-based）
        start_sec:      起始秒数
        end_sec:        结束秒数
        original_text:  原版字幕文本
        language:       语言代码
        model_size:     faster-whisper 模型大小

    Returns:
        dict 或 None:
            original:      原版文本
            retranscribed: 新版转录文本
            words:         词级 [(word, start, end), ...]
            similarity:    编辑距离相似度 (0-1)
            changed:       是否有明显变化 (similarity < 0.85)
            start/end:     时间戳(秒)
            duration:      音频段时长(秒)
    """
    duration = end_sec - start_sec
    if duration < 0.3 or duration > 30:
        logger.warning(f"[索引 {sub_index}] 时间段 {duration:.1f}s 超出合理范围，跳过")
        return None

    logger.info(f"[索引 {sub_index}] 提取音频段: {start_sec:.2f}s-{end_sec:.2f}s ({duration:.1f}s)")

    # 提取音频段
    audio_segment, sr = _extract_audio_segment(audio_path, start_sec, end_sec)

    # 获取模型 & 转录
    model = _get_whisper_model(model_size)
    segments, info = model.transcribe(
        audio_segment,
        language=language,
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,          # 定点识别不需要 VAD
    )

    # 收集所有 segment 文本
    new_text_parts = []
    word_details = []
    for seg in segments:
        new_text_parts.append(seg.text.strip())
        if hasattr(seg, "words") and seg.words:
            for w in seg.words:
                word_details.append((w.word.strip(), w.start, w.end))

    new_text = " ".join(new_text_parts)

    # 计算相似度
    orig_norm = _normalize_text(original_text)
    new_norm = _normalize_text(new_text)
    sim = _levenshtein_ratio(orig_norm, new_norm)
    changed = sim < 0.85

    if changed:
        logger.info(f"  ⚠ 识别结果不同（相似度: {sim:.2f}）")
    else:
        logger.info(f"  识别结果一致（相似度: {sim:.2f}）")

    # 清理
    del audio_segment, segments
    gc.collect()

    return {
        "original": original_text,
        "retranscribed": new_text,
        "words": word_details,
        "similarity": round(sim, 4),
        "changed": changed,
        "start": start_sec,
        "end": end_sec,
        "duration": duration,
    }


def targeted_retranscribe(srt_path: str, audio_path: str,
                          indices_to_check: List[int],
                          language: str = "ja",
                          model_size: str = "small") -> Dict[int, dict]:
    """
    对多个索引做定点重新转录。

    Args:
        srt_path:           原字幕 SRT 文件路径
        audio_path:         音频文件路径（修复后 WAV）
        indices_to_check:   需要重新识别的字幕索引列表
        language:           语言代码
        model_size:         faster-whisper 模型大小

    Returns:
        {索引: {original, retranscribed, similarity, changed, ...}}
    """
    t_start = time.time()

    # 读取全部字幕，构建索引查找表
    subs = pysrt.open(srt_path)
    sub_map = {}
    for s in subs:
        sub_map[s.index] = s

    results = {}
    for idx in indices_to_check:
        if idx not in sub_map:
            logger.error(f"索引 {idx} 不在字幕文件中")
            continue

        target = sub_map[idx]
        result = retranscribe_single(
            audio_path, idx,
            target.start.ordinal / 1000.0,
            target.end.ordinal / 1000.0,
            target.text,
            language=language, model_size=model_size,
        )
        if result:
            results[idx] = result

    elapsed = time.time() - t_start
    changed_count = sum(1 for r in results.values() if r.get("changed"))
    logger.info(f"定点识别完成: {len(results)} 条, "
                f"{changed_count} 条有差异, "
                f"耗时 {elapsed:.1f}s")
    return results


# ── CLI 使用 ──────────────────────────────────────

def main():
    """命令行入口: python -m SRT.TargetedRecognizer <srt> <wav> [索引...]"""
    import argparse

    parser = argparse.ArgumentParser(description="定点重新转录 — 用 faster-whisper 验证可疑字幕")
    parser.add_argument("srt", help="SRT 字幕文件路径")
    parser.add_argument("audio", nargs="?", help="WAV 音频路径（省略则自动推断）")
    parser.add_argument("indices", nargs="*", type=int, help="要检查的字幕索引")
    parser.add_argument("--model", default="small", help="whisper 模型大小")
    parser.add_argument("--lang", default="ja", help="语言代码")
    parser.add_argument("--json", default=None, help="输出 JSON 报告路径")

    args = parser.parse_args()

    # 自动推断 WAV 路径
    audio_path = args.audio
    if not audio_path:
        base = os.path.splitext(args.srt)[0]
        candidates = [
            f"{base}.wav",
            os.path.join(os.path.dirname(args.srt),
                         os.path.basename(base) + ".wav"),
        ]
        for c in candidates:
            if os.path.exists(c):
                audio_path = c
                print(f"自动检测到音频: {audio_path}")
                break
    if not audio_path or not os.path.exists(audio_path):
        print("错误: 无法自动检测 WAV 路径，请通过参数指定")
        sys.exit(1)

    # 如果没指定索引，从翻译日志抓取被标记的低质索引
    indices = args.indices or []
    if not indices:
        log_patterns = ["translate-log.json", "srt_extractor.log"]
        srt_dir = os.path.dirname(args.srt)
        flagged = set()
        for log_name in log_patterns:
            log_path = os.path.join(srt_dir, log_name)
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    import re
                    for line in f:
                        for m in re.finditer(r"索引 (\d+) 疑似低质|flagged.*?index[_\s]*(\d+)", line):
                            flagged.add(int(m.group(1) or m.group(2)))
        indices = sorted(flagged)
        if indices:
            print(f"从日志中找到标记索引: {indices}")
        else:
            print("未指定索引，请通过命令行提供")
            sys.exit(1)

    # 执行
    results = targeted_retranscribe(
        args.srt, audio_path, indices,
        language=args.lang, model_size=args.model,
    )

    # 报告
    print(f"\n{'='*60}")
    print(f"定点识别报告 — {len(indices)} 条检查")
    print(f"{'='*60}")
    changed_any = False
    for idx in indices:
        r = results.get(idx, {})
        if r.get("changed"):
            changed_any = True
            flag = "⚠ 不同"
        else:
            flag = "✓ 一致"
        sim = r.get("similarity", 0)
        orig = r.get("original", "")[:60]
        new_t = r.get("retranscribed", "")[:60]
        print(f"  [{idx:>3}] {flag} (sim={sim:.2f})")
        print(f"         原版: {orig}")
        print(f"         新版: {new_t}")

    if not changed_any:
        print("  全部一致，未发现识别错误")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n详细报告已保存: {args.json}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
