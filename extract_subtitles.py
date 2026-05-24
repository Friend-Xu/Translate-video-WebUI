#!/usr/bin/env python
"""
通用视频字幕提取脚本 — 编排器 (Orchestrator)

数据流:
  NODE 1   视频信息采集     → pipeline/video_info.py
  NODE 1.5 时长缺陷检测     → MediaValidator
  NODE 2   音频提取+修复     → pipeline/audio.py
  NODE 2.5 Demucs人声分离    → pipeline/demucs_instr.py
  NODE 3   VAD+转录+断句    → pipeline/transcriber.py
  NODE 3.5 wav2vec2 对齐    → whisperx_local.alignment (精修词级时间戳)
  NODE 2.7 说话人分离(可选)  → pipeline/speaker_diarize.py
  NODE 2.75 说话人融合(可选)  → pipeline/speaker_fusion.py
  NODE 2.8  分离结果验证(可选) → pipeline/diarization_verify.py
  NODE 3.75 Timeline Fusion     → timeline/ (统一时间轴 IR)
  NODE 4   JSON→SRT         → Json_Convert_Srt

用法:
    python extract_subtitles.py <视频路径> [--out-dir <路径>] [--lang <语言代码>]

   --lang ja  (指定语言时自动启用 wav2vec2 强制对齐，精修时间戳)
   不指定--lang (auto-detect) 时不启用 wav2vec2 对齐

详细文档: ARCHITECTURE.md
"""
import os
import sys
import time
import re
import json
import subprocess
import argparse
from datetime import datetime

# ─── 环境初始化 ───
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["HF_HOME"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["TORCH_HOME"] = os.path.join(PROJECT_ROOT, "models")

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))


# ─── 日志辅助 ───
def log_node(node, msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [NODE {node}] {msg}")


def hr(title):
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def parse_args():
    parser = argparse.ArgumentParser(description="视频字幕提取 (faster-whisper 直连)")
    parser.add_argument("video", nargs="?", help="视频路径")
    parser.add_argument("--out-dir", help="输出目录（默认同目录下的 <视频名>_out/）")
    parser.add_argument("--lang", default=None, help="语言代码（指定后启用 wav2vec2 对齐，如 --lang ja）")
    parser.add_argument("--model", default="turbo", help="whisper 模型 (tiny/base/small/medium/turbo/large-v3)")
    parser.add_argument("--device", default="cuda", help="计算设备 (cuda/cpu)")
    parser.add_argument("--compute-type", default="float16", help="计算精度 (float16/int8_float16/int8/float32)")
    parser.add_argument("--skip-defect-check", action="store_true", help="跳过音频缺陷检测 (NODE 1.5)")
    parser.add_argument("--skip-demucs", action="store_true", help="跳过 Demucs 人声分离 (NODE 2.5)")
    parser.add_argument("--skip-align", action="store_true", help="跳过 wav2vec2 强制对齐 (即使指定了 --lang)")
    parser.add_argument("--align-lang", default=None, help="wav2vec2 对齐语言（默认跟随 --lang）")
    parser.add_argument("--num-workers", type=int, default=1, help="whisper 并发 worker 数 (1=串行, 2~4=并行)")
    parser.add_argument("--enable-speaker-diarization", action="store_true", help="启用说话人分离 (NODE 2.7)")
    return parser.parse_args()


# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════
def main():
    args = parse_args()

    # 默认使用同目录下的 LongTest1.mp4（兼容旧用法）
    video = args.video or os.path.join(PROJECT_ROOT, "source_file", "LongTest1.mp4")
    if not os.path.isfile(video):
        print(f"错误: 视频文件不存在: {video}")
        sys.exit(1)

    video_name = os.path.splitext(os.path.basename(video))[0]
    out_dir = args.out_dir or os.path.join(os.path.dirname(video), f"{video_name}_out")
    os.makedirs(out_dir, exist_ok=True)

    wav_path = os.path.join(out_dir, f"{video_name}.wav")
    json_path = os.path.join(out_dir, f"{video_name}.json")
    srt_path = os.path.join(out_dir, f"{video_name}.srt")

    # ── 断点续传: 加载 workspace checkpoint ──
    ws_dir = os.path.dirname(out_dir)  # out_dir is 01_extract/, ws_dir is {name}_project/
    from pipeline.checkpoint import PipelineCheckpoint, _file_sha256
    ck = PipelineCheckpoint.load(ws_dir)
    ck.clean_tmp_files(out_dir)

    # ── 导入模块（延迟加载，避免 import 开销影响日志整洁）──
    from pipeline.utils import get_ffmpeg_exe, format_size, fmt_time
    from pipeline.video_info import get_video_info, diagnose_defect
    from pipeline.audio import need_extract_audio, extract_audio_with_fix
    from pipeline.transcriber import VADTranscriber
    from Json_Convert_Srt import convert_json_to_srt

    ffmpeg_exe = get_ffmpeg_exe()

    # ════════════════════════════════════════════════════════
    # NODE 1: 视频信息采集
    # ════════════════════════════════════════════════════════
    hr(f"NODE 1: 视频信息采集 — {video_name}")
    t0 = time.time()
    info = get_video_info(video, ffmpeg_exe)
    log_node(1, f"文件: {info.path} ({format_size(info.size)})")
    log_node(1, f"时长: {info.duration_str} ({info.duration_sec:.2f}s)")
    log_node(1, f"编码: {info.video_codec} / {info.audio_codec}")
    log_node(1, f"耗时: {time.time()-t0:.2f}s")
    d1 = time.time() - t0
    ck.complete_node("N1"); ck.save()

    # ════════════════════════════════════════════════════════
    # NODE 1.5: 时长缺陷检测
    # ════════════════════════════════════════════════════════
    if args.skip_defect_check:
        hr("NODE 1.5: 视频时长缺陷检测 (已跳过)")
        log_node("1.5", "用户选择跳过缺陷检测，假定无缺陷")

        class _FakeMetrics:
            container_duration = info.duration_sec
            decoded_audio_duration = info.duration_sec
            container_audio_gap = 0.0
            drift_rate_pct = 0.0
            is_vfr = False
            total_video_frames = 0
            avg_frame_rate = 0.0

        class _FakeDiagnosis:
            status = "ok"
            metrics = _FakeMetrics()
            defect_type = ""
            defect_name = ""
            severity = ""
            suggested_action = ""

        diagnosis = _FakeDiagnosis()
        d15 = 0.0
    else:
        hr("NODE 1.5: 视频时长缺陷检测 (MediaValidator)")
        t0 = time.time()
        diagnosis = diagnose_defect(video)
        m = diagnosis.metrics
        log_node("1.5", f"状态: {diagnosis.status}")
        log_node("1.5", f"CD={m.container_duration:.3f}s, ADD={m.decoded_audio_duration:.3f}s")
        log_node("1.5", f"偏差: {m.container_audio_gap:+.3f}s ({m.drift_rate_pct:+.3f}%)")
        log_node("1.5", f"VFR={m.is_vfr}, TVF={m.total_video_frames}, FPS={m.avg_frame_rate:.3f}")
        if diagnosis.status == "defect":
            log_node("1.5", f"缺陷: {diagnosis.defect_type} - {diagnosis.defect_name}")
            log_node("1.5", f"严重度: {diagnosis.severity} | 建议: {diagnosis.suggested_action}")
        log_node("1.5", f"耗时: {time.time()-t0:.2f}s")
        d15 = time.time() - t0
    ck.complete_node("N1.5"); ck.save()

    # ════════════════════════════════════════════════════════
    # NODE 2: 音频提取 + aresample 修复
    # ════════════════════════════════════════════════════════
    hr("NODE 2: 音频提取 + aresample 修复")
    t0 = time.time()
    wav_sec = 0.0

    if need_extract_audio(wav_path, ffmpeg_exe, info.duration_sec, diagnosis):
        log_node(2, f"容器时长={info.duration_sec:.2f}s, aresample=async=1:first_pts=0")
        wav_sec = extract_audio_with_fix(video, wav_path, info.duration_sec, ffmpeg_exe)
        new_gap = info.duration_sec - wav_sec
        if abs(new_gap) < 1.0:
            log_node(2, f"修复成功! WAV={wav_sec:.2f}s, 偏差={new_gap:+.3f}s")
        else:
            log_node(2, f"修复后仍有偏差: WAV={wav_sec:.2f}s, 差={new_gap:+.3f}s")
    else:
        from pipeline.audio import get_wav_duration
        wav_sec = get_wav_duration(wav_path, ffmpeg_exe)
        log_node(2, f"已有 WAV ({wav_sec:.1f}s) 且无缺陷，跳过提取")

    audio_size = os.path.getsize(wav_path)
    log_node(2, f"WAV: {format_size(audio_size)}, 16000Hz, PCM16")
    log_node(2, f"耗时: {time.time()-t0:.1f}s")
    d2 = time.time() - t0
    ck.complete_node("N2"); ck.save()

    # ════════════════════════════════════════════════════════
    # NODE 2.5: Demucs 人声分离（提取纯背景乐 + 人声）
    # ════════════════════════════════════════════════════════
    t0 = time.time()
    vocal_path = os.path.join(out_dir, f"{video_name}_(Vocals).wav")
    instrumental_path = os.path.join(out_dir, f"{video_name}_(Instrumental).wav")
    # 若 instrumental 是降级 fallback（不是真实 Demucs 输出），删除后重跑
    demucs_no_vocals = os.path.join(out_dir, "htdemucs", video_name, "no_vocals.wav")
    if os.path.isfile(instrumental_path) and not os.path.isfile(demucs_no_vocals):
        print(f"  [INFO] 检测到降级残留，删除后重试 Demucs")
        os.remove(instrumental_path)
        if os.path.isfile(vocal_path):
            os.remove(vocal_path)

    demucs_ok = False  # N2.5 是否成功完成（或有意跳过）

    if not os.path.isfile(instrumental_path):
        if args.skip_demucs:
            hr("NODE 2.5: 背景乐（已跳过 Demucs，不生成背景乐）")
            print(f"  [INFO] Demucs 已跳过 (--skip-demucs)，不生成背景音乐")
            log_node("2.5", "跳过 — 无背景乐")
            demucs_ok = True
        else:
            hr("NODE 2.5: Demucs 人声分离")
            try:
                from pipeline.demucs_instr import extract_instrumental
                instr_result = extract_instrumental(video, out_dir)
                demucs_dir = os.path.dirname(instr_result)
                demucs_vocal = os.path.join(demucs_dir, "vocals.wav")

                import shutil
                shutil.copy2(instr_result, instrumental_path)
                if os.path.isfile(demucs_vocal):
                    shutil.copy2(demucs_vocal, vocal_path)
                    vocal_size = os.path.getsize(vocal_path)
                    log_node("2.5", f"人声: {vocal_path} ({format_size(vocal_size)})")

                instr_size = os.path.getsize(instrumental_path)
                log_node("2.5", f"背景乐: {instrumental_path} ({format_size(instr_size)})")
                demucs_ok = True
            except Exception as e:
                import traceback
                print(f"  [WARN] Demucs 失败 ({e})，跳过背景乐分离")
                print(f"  [DEBUG] 详细错误:\n{traceback.format_exc()}")
                log_node("2.5", f"跳过: Demucs 失败 — {e}")
    else:
        instr_size = os.path.getsize(instrumental_path)
        log_node("2.5", f"已有背景乐 ({format_size(instr_size)})，跳过分离")
        if os.path.isfile(vocal_path):
            log_node("2.5", f"人声: {vocal_path} ({format_size(os.path.getsize(vocal_path))})")
        demucs_ok = True

    log_node("2.5", f"耗时: {time.time()-t0:.1f}s")
    d25 = time.time() - t0
    if demucs_ok:
        ck.complete_node("N2.5"); ck.save()

    # ════════════════════════════════════════════════════════
    # NODE 3: VAD 分段 + faster-whisper 转录
    # ════════════════════════════════════════════════════════
    hr("NODE 3: VAD 分段 + faster-whisper 转录")
    log_node(3, f"模型: faster-whisper-{args.model} ({args.device}, {args.compute_type})")
    t0 = time.time()

    model_root = os.path.join(PROJECT_ROOT, "models", "whisper")
    os.makedirs(model_root, exist_ok=True)

    transcriber = VADTranscriber(
        audio_path=wav_path,
        model_name=args.model,
        device=args.device,
        compute_type=args.compute_type,
        download_root=model_root,
        num_workers=args.num_workers,
    )

    # 3a: VAD
    log_node(3, "执行 Silero VAD...")
    vad_segments, vad_time = transcriber.run_vad(force=False)
    vad_stats = transcriber.get_vad_stats()
    log_node(3, f"VAD: {vad_stats['vad_count']} 段, 耗时: {vad_time:.1f}s")
    log_node(3, f"首段: {vad_stats['first_segment']}, 末段: {vad_stats['last_segment']}")
    log_node(3, f"语音: {vad_stats['total_speech_dur']:.1f}s ({vad_stats['total_speech_dur']/max(vad_stats['audio_len'],1)*100:.1f}%)")

    # 保存 VAD segments 标准化输出（M2：计划书 7.2 节规范）
    vad_json_path = os.path.join(out_dir, "vad_segments.json")
    with open(vad_json_path, "w", encoding="utf-8") as f:
        json.dump([{"start": s, "end": e} for s, e in vad_segments], f, ensure_ascii=False, indent=2)
    log_node(3, f"VAD 标准化输出: vad_segments.json")

    # 3b: 语言检测（打印日志）
    log_node(3, "检测音频语言...")

    # 3c: 转录 + 词级分组 + wav2vec2 对齐
    #   指定语言时同时启用 wav2vec2 对齐；自动检测时不启用（需手动确认语言）
    merged_batches = transcriber.merge_segments(vad_segments)
    align_lang = args.align_lang or None
    enable_align = not args.skip_align
    log_node(3, f"开始转录 ({vad_stats['vad_count']} 段 → 合并后 {len(merged_batches)} 批)...")
    result = transcriber.transcribe_all(language=args.lang, align_language=align_lang, enable_align=enable_align)
    st = result["stats"]

    log_node(3, f"语言: {result['language']} (置信度: {st['lang_probability']:.3f}), 耗时: {st['detect_time']:.1f}s")
    log_node(3, f"合并后: {st['merged_count']} 批次, 词级: {st['total_words']} words")
    log_node(3, f"分组: {st['segments_count']} segments")
    log_node(3, f"转录耗时: {st['transcribe_time']:.1f}s ({st['transcribe_time']/60:.1f}min)")
    if st['align_time']:
        align_status = f"✓ {st['align_time']:.1f}s"
    else:
        align_status = "未启用 (指定 --lang 即可启用)"
    log_node(3, f"wav2vec2 对齐: {align_status}")
    log_node(3, f"总文本字符: {sum(len(s['text']) for s in result['segments'])}")

    # 保存 JSON（含 wav2vec2 对齐后的精确时间戳）
    json_size = VADTranscriber.save_json(result, json_path)
    log_node(3, f"JSON: {json_path} ({format_size(json_size)})")
    d3 = time.time() - t0
    ck.complete_node("N3"); ck.save()

    # ════════════════════════════════════════════════════════
    # NODE 2.7: 说话人分离 (可选)
    # ════════════════════════════════════════════════════════
    speaker_timeline = None
    speaker_timeline_path = os.path.join(out_dir, "speaker_timeline.json")

    if args.enable_speaker_diarization and os.path.isfile(vocal_path):
        hr("NODE 2.7: 说话人分离 (pyannote)")
        t0 = time.time()
        try:
            from pipeline.speaker_diarize import SpeakerDiarizer
            diarizer = SpeakerDiarizer()
            speaker_timeline = diarizer.run(vocal_path)
            diarizer.export_timeline_json(vocal_path, speaker_timeline_path)
            speakers = sorted(set(s[0] for s in speaker_timeline))
            log_node("2.7", f"检测到 {len(speakers)} 个说话人: {', '.join(speakers)}, "
                     f"{len(speaker_timeline)} 个语音段")
            log_node("2.7", f"耗时: {time.time()-t0:.1f}s")
        except Exception as e:
            import traceback
            print(f"  [WARN] 说话人分离失败 ({e})，跳过")
            traceback.print_exc()
            log_node("2.7", f"跳过: 分离失败 — {e}")
            speaker_timeline = None

    if args.enable_speaker_diarization and not os.path.isfile(vocal_path):
        log_node("2.7", "跳过: 人声文件不存在")
        print(f"  [INFO] 说话人分离跳过 — 人声文件不存在: {vocal_path}")

    # ════════════════════════════════════════════════════════
    # NODE 2.75: 说话人融合 (word 级时间交集分配)
    # ════════════════════════════════════════════════════════
    speaker_map_path = os.path.join(out_dir, "speaker_map.json")

    if speaker_timeline and result.get("segments"):
        hr("NODE 2.75: 说话人融合")
        t0 = time.time()
        try:
            from pipeline.speaker_fusion import (
                assign_word_speakers,
                split_at_speaker_boundaries,
                detect_overlaps,
            )

            # 收集所有词
            all_words = result.get("words", [])
            if not all_words:
                for seg in result["segments"]:
                    all_words.extend(seg.get("words", []))

            # 词级说话人分配 (优先 Word-level Probabilistic Refinement)
            n_assigned = 0
            if all_words:
                try:
                    from core.refiner import WordLevelRefiner
                    refiner = WordLevelRefiner()
                    refined = refiner.refine(all_words, speaker_timeline)
                    all_words = refined["words"]
                    stats = refined["stats"]
                    n_assigned = sum(1 for w in all_words if w.get("speaker"))
                    log_node("2.75", f"概率精修: {stats['refined_count']}/{stats['total']} words 调整 "
                             f"({stats['refined_pct']}%), avg_entropy={stats['avg_entropy']:.3f}")
                except ImportError:
                    all_words = assign_word_speakers(all_words, speaker_timeline)
                    n_assigned = sum(1 for w in all_words if w.get("speaker"))

            # 将全局词的 speaker 分配到 segment 内每个 word（时间重叠法）
            # whisper 词和 wav2vec2 对齐词粒度不同，直接匹配时间戳不可靠
            if all_words:
                for seg in result["segments"]:
                    for w in seg.get("words", []):
                        if "start" not in w or "end" not in w:
                            continue
                        best_spk = None
                        best_ov = 0.0
                        for gw in all_words:
                            s = gw.get("speaker")
                            if not s or "start" not in gw or "end" not in gw:
                                continue
                            ov = max(0, min(w["end"], gw["end"]) - max(w["start"], gw["start"]))
                            if ov > best_ov:
                                best_ov = ov
                                best_spk = s
                        if best_spk and best_ov > 0:
                            w["speaker"] = best_spk

            # 检测重叠
            overlaps = detect_overlaps(speaker_timeline)

            # 预切分: 利用 pyannote turn 边界切分长 ASR segment
            before_pre_split = len(result["segments"])
            result["segments"] = _pre_split_by_pyannote_turns(
                result["segments"], speaker_timeline, min_gap=0.3
            )
            after_pre_split = len(result["segments"])
            if after_pre_split > before_pre_split:
                log_node("2.75", f"预切分: {before_pre_split} → {after_pre_split} segments "
                         f"(+{after_pre_split - before_pre_split})")

            # 段切分 (词级 speaker 边界)
            original_count = len(result["segments"])
            result["segments"] = split_at_speaker_boundaries(result["segments"])
            new_count = len(result["segments"])

            # 更新 result
            result["words"] = all_words
            speakers = sorted(set(
                w.get("speaker", "?") for w in all_words if w.get("speaker")
            ))
            result["speakers"] = {
                spk: {
                    "total_dur": sum(
                        w["end"] - w["start"]
                        for w in all_words
                        if w.get("speaker") == spk
                    ),
                    "segments": sum(
                        1 for s in result["segments"]
                        if s.get("speaker") == spk
                    ),
                }
                for spk in speakers
            }
            result["speaker_turns"] = [
                {"speaker": spk, "start": s, "end": e, "confidence": c}
                for spk, s, e, c in speaker_timeline
            ]

            # 导出 speaker_map（SRT 索引 → speaker 映射）
            speaker_map = [
                {"index": i + 1, "speaker": s.get("speaker", "?")}
                for i, s in enumerate(result["segments"])
            ]
            with open(speaker_map_path, "w", encoding="utf-8") as f:
                json.dump(speaker_map, f, ensure_ascii=False, indent=2)

            # 更新保存的 JSON
            json_size = VADTranscriber.save_json(result, json_path)

            log_node("2.75", f"词级分配: {n_assigned}/{len(all_words)} 个词标说话人")
            log_node("2.75", f"段切分: {original_count} → {new_count} 段")
            log_node("2.75", f"说话人: {', '.join(speakers) if speakers else '无'}")
            if overlaps:
                log_node("2.75", f"重叠: {len(overlaps)} 处")
            log_node("2.75", f"耗时: {time.time()-t0:.1f}s")
        except Exception as e:
            import traceback
            print(f"  [WARN] 说话人融合失败 ({e})，跳过")
            traceback.print_exc()
            log_node("2.75", f"跳过: 融合失败 — {e}")

    # ════════════════════════════════════════════════════════
    # NODE 2.8: 分离结果验证
    # ════════════════════════════════════════════════════════
    speaker_verification_path = os.path.join(out_dir, "speaker_verification.json")

    if speaker_timeline and result.get("segments"):
        hr("NODE 2.8: 分离结果验证")
        t0 = time.time()
        try:
            from pipeline.diarization_verify import verify_diarization

            # 用 result 中的 speakers 汇总计算音频时长
            total_speech = sum(
                s.get("total_dur", 0)
                for s in result.get("speakers", {}).values()
            ) if result.get("speakers") else sum(
                s["end"] - s["start"] for s in result["segments"]
            )

            report = verify_diarization(
                speaker_timeline, transcript=result, total_audio_dur=total_speech
            )

            with open(speaker_verification_path, "w", encoding="utf-8") as f:
                json.dump({
                    "passes_all": report.passes_all,
                    "summary": report.summary,
                    "issues": [
                        {"layer": i.layer, "severity": i.severity,
                         "message": i.message, "detail": i.detail}
                        for i in report.issues
                    ],
                }, f, ensure_ascii=False, indent=2)

            status = "通过" if report.passes_all else f"有 {report.summary['errors']} 个错误"
            log_node("2.8", f"验证: {status}, {report.summary['total_issues']} 个问题")
            for issue in report.issues:
                log_node("2.8", f"  [{issue.severity.upper()}] L{issue.layer}: {issue.message}")
            log_node("2.8", f"耗时: {time.time()-t0:.1f}s")
        except Exception as e:
            import traceback
            print(f"  [WARN] 验证失败 ({e})，跳过")
            traceback.print_exc()
            log_node("2.8", f"跳过: 验证失败 — {e}")

    # ════════════════════════════════════════════════════════
    # NODE 3.75: Timeline Fusion（统一时间轴 IR 生成）
    # ════════════════════════════════════════════════════════
    hr("NODE 3.75: Timeline Fusion (统一时间轴 IR)")
    timeline_path = os.path.join(out_dir, "timeline.json")
    t0 = time.time()
    try:
        from timeline import from_extract_result, save_json as save_timeline

        tl = from_extract_result(
            segments=result.get("segments", []),
            words=result.get("words"),
            speaker_timeline=speaker_timeline,
            audio_id=video_name,
            metadata={
                "lang": result.get("language", ""),
                "duration": info.duration_sec,
                "extract_model": f"faster-whisper-{args.model}",
            },
        )
        save_timeline(tl, timeline_path)
        log_node("3.75", f"Timeline IR: {len(tl.timeline)} segments, "
                 f"{len(tl.speaker_map)} speakers")
        log_node("3.75", f"保存: timeline.json ({os.path.getsize(timeline_path)} bytes)")
        log_node("3.75", f"耗时: {time.time()-t0:.1f}s")

        # ═══ 双写验证：新 core/ IR v2 并行输出 ═══
        try:
            from core.runtime.verify import dual_write_verify
            vrf = dual_write_verify(
                old_timeline=tl,
                segments=result.get("segments", []),
                speaker_timeline=speaker_timeline,
                output_dir=out_dir,
            )
            if vrf["status"] == "ok":
                log_node("3.75", f"双写验证: 行为等价 ✓")
            elif vrf["status"] == "diff":
                log_node("3.75", f"双写验证: 发现 {vrf['diff_count']} 处差异 → {os.path.basename(vrf['diff_file'])}")
            else:
                log_node("3.75", f"双写验证: 错误 — {vrf.get('reason', 'unknown')}")
        except ImportError:
            log_node("3.75", "双写验证: core/ 模块未就绪，跳过")
        except Exception as _dw_err:
            log_node("3.75", f"双写验证: 异常 — {_dw_err}")
    except Exception as e:
        import traceback
        print(f"  [WARN] Timeline Fusion 失败 ({e})，跳过")
        traceback.print_exc()
        log_node("3.75", f"跳过: Timeline 构建失败 — {e}")

    # ════════════════════════════════════════════════════════
    # NODE 4: JSON → SRT
    # ════════════════════════════════════════════════════════
    hr("NODE 4: SRT 断句整理 (Json_Convert_Srt)")
    t0 = time.time()

    # 语言检测（用于显示）
    jp_chars = re.compile(r'[\u3040-\u309F\u30A0-\u30FF]')
    sample_text = " ".join(s["text"] for s in result["segments"][:5])
    detected_lang = "ja" if jp_chars.search(sample_text) else "en"
    log_node(4, f"文本语言: {'日语' if detected_lang == 'ja' else '英语'}")
    log_node(4, f"输入: {st['segments_count']} segments")

    try:
        srt_content = convert_json_to_srt(json_path)
    except Exception as e:
        log_node(4, f"错误: SRT 转换失败 - {e}")
        raise
    if not srt_content or not srt_content.strip():
        log_node(4, "错误: SRT 输出为空")
        raise RuntimeError("convert_json_to_srt 返回空内容")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    blocks = [b for b in srt_content.split("\n\n") if b.strip()]
    srt_chars = sum(len(b.split("\n")[-1]) for b in blocks if b.split("\n")[-1].strip())
    log_node(4, f"输出: {len(blocks)} 条字幕, {srt_chars} 字符")
    log_node(4, f"平均每条: {srt_chars/max(len(blocks),1):.1f} 字符")
    log_node(4, f"耗时: {time.time()-t0:.1f}s")
    d4 = time.time() - t0
    ck.complete_node("N4"); ck.save()

    srt_size = os.path.getsize(srt_path)

    # ════════════════════════════════════════════════════════
    # FINAL: 汇总
    # ════════════════════════════════════════════════════════
    hr("FINAL: 汇总统计")
    total = d1 + d15 + d2 + d3 + d4

    log_node("PREVIEW", "SRT 前 5 条:")
    for line in srt_content.split("\n")[:25]:
        print(f"  {line}")

    print()
    stats = [
        ("视频", os.path.basename(video)),
        ("时长", f"{fmt_time(info.duration_sec)} ({info.duration_sec:.1f}s)"),
        ("WAV", format_size(audio_size)),
        ("语言", result["language"]),
        ("VAD 段", str(st["vad_count"])),
        ("批次", str(st["merged_count"])),
        ("words", str(st["total_words"])),
        ("segments", str(st["segments_count"])),
        ("字幕", str(len(blocks))),
        ("文本字符", str(srt_chars)),
        ("SRT", format_size(srt_size)),
        ("JSON", format_size(json_size)),
        ("N1", f"{d1:.2f}s"),
        ("N1.5", f"{d15:.2f}s"),
        ("N2", f"{d2:.1f}s"),
        ("N3", f"{d3:.1f}s ({d3/60:.1f}min)"),
        ("N3.5(align)", f"{st.get('align_time', 0):.1f}s"),
        ("N4", f"{d4:.1f}s"),
        ("总计", f"{total:.1f}s ({total/60:.1f}min)"),
    ]
    for k, v in stats:
        print(f"  {k:>12s}: {v}")

    print()
    log_node("DONE", f"输出目录: {out_dir}")
    log_node("DONE", f"SRT: {srt_path}")

    # ── 翻译提示（如有需要） ──
    # 本管线只做字幕提取，不包含翻译。翻译由 SRT_Translator 完成。
    # 翻译管线包含三个内置质量保障功能（见代码注释）:
    #   - MeCab 日语分词: 用于 SRT 时间轴自适应
    #   - 跨语言语义核验: 日语原文 vs 中文译文相似度排查
    #   - 术语词典替换: 技术术语 (Minecraft 299条) 自动替换
    # 使用方式：
    #   python -m SRT.SRT_Translator "{srt_path}"
    #
    # 定点重转录验证（faster-whisper，可选）:
    #   python -m SRT.TargetedRecognizer <srt> <wav> -d <索引...>
    print()
    log_node("NEXT", "如需翻译，运行:")
    relative = os.path.relpath(srt_path, PROJECT_ROOT)
    print(f"  python -m SRT.SRT_Translator {relative}")

    return 0


def _pre_split_by_pyannote_turns(
    segments: list[dict],
    speaker_timeline: list[tuple],
    min_gap: float = 0.3,
) -> list[dict]:
    """利用 pyannote turn 边界预切分 ASR segment。

    ASR 的 Silero VAD 可能把多个 speaker turn 合并成一个长段。
    此函数检测 ASR segment 是否跨越 pyannote 的 turn 边界，
    如果是则在边界处切分。

    Args:
        segments: ASR segments [{start, end, text, words, speaker, ...}]
        speaker_timeline: [(speaker, start, end, confidence), ...]
        min_gap: 两个 turn 之间的最小间隔才作为切分点

    Returns:
        新的 segments 列表（可能更长）
    """
    if not speaker_timeline or len(speaker_timeline) < 2:
        return segments

    # 收集所有合格的切分边界 (相邻 turn 间隔 >= min_gap)
    split_boundaries: list[float] = []
    for i in range(1, len(speaker_timeline)):
        prev_end = speaker_timeline[i - 1][2]
        cur_start = speaker_timeline[i][1]
        gap = cur_start - prev_end
        if gap >= min_gap:
            split_boundaries.append(cur_start)

    if not split_boundaries:
        return segments

    result: list[dict] = []
    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)

        # 找该 segment 内的切分点
        cuts = [bp for bp in split_boundaries if seg_start < bp < seg_end]
        if not cuts:
            result.append(seg)
            continue

        # 按切分点分割
        cuts.sort()
        all_points = [seg_start] + cuts + [seg_end]
        words = seg.get("words", [])
        text = seg.get("text", "").strip()
        spk = seg.get("speaker")

        for k in range(len(all_points) - 1):
            sub_start = all_points[k]
            sub_end = all_points[k + 1]
            dur = sub_end - sub_start
            if dur < 0.15:  # 跳过过短的片段
                continue

            # 分配该时间段的 word
            sub_words = [
                w for w in words
                if w.get("start", 0) >= sub_start - 0.05
                and w.get("end", 0) <= sub_end + 0.05
            ]
            sub_text = " ".join(w.get("word", "") for w in sub_words) if sub_words else text

            sub_seg = {
                "start": sub_start,
                "end": sub_end,
                "text": sub_text.strip() or text,
                "speaker": spk,
                "words": sub_words,
            }
            # 保留原始 segment 的其他字段
            for k2, v in seg.items():
                if k2 not in sub_seg:
                    sub_seg[k2] = v

            result.append(sub_seg)

    return result


if __name__ == "__main__":
    sys.exit(main())
