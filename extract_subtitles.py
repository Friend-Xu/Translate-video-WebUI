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

    if not os.path.isfile(instrumental_path):
        if args.skip_demucs:
            hr("NODE 2.5: 背景乐（已跳过 Demucs，不生成背景乐）")
            print(f"  [INFO] Demucs 已跳过 (--skip-demucs)，不生成背景音乐")
            log_node("2.5", "跳过 — 无背景乐")
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
            except Exception as e:
                # Demucs 失败时降级：直接用 ffmpeg 提取完整音轨
                print(f"  [WARN] Demucs 失败 ({e})，降级为完整音轨提取")
                subprocess.run(
                    [ffmpeg_exe, "-y", "-i", video,
                     "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                     instrumental_path],
                    capture_output=True, text=True, check=True,
                )
                instr_size = os.path.getsize(instrumental_path)
                log_node("2.5", f"背景乐(降级): {instrumental_path} ({format_size(instr_size)})")
    else:
        instr_size = os.path.getsize(instrumental_path)
        log_node("2.5", f"已有背景乐 ({format_size(instr_size)})，跳过分离")
        if os.path.isfile(vocal_path):
            log_node("2.5", f"人声: {vocal_path} ({format_size(os.path.getsize(vocal_path))})")
    log_node("2.5", f"耗时: {time.time()-t0:.1f}s")
    d25 = time.time() - t0
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

    srt_content = convert_json_to_srt(json_path)
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


if __name__ == "__main__":
    sys.exit(main())
