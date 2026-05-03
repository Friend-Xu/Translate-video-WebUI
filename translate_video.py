#!/usr/bin/env python
"""
一站式视频翻译管线

工作流:
  1. 字幕提取 (extract_subtitles.py)   → .srt + _(Instrumental).wav
  2. SRT 翻译 (SRT_Translator)         → -zh.srt
  3. 术语替换 (TermReplacer)           → -zh-replace.srt
  4. TTS 语音合成 (pipeline/tts_*)     → -TTS.mp4

用法:
    python translate_video.py <视频路径> [--lang en] [--model small]

示例:
    python translate_video.py source_file/test.mp4 --lang en
    python translate_video.py source_file/test.mp4 --lang ja --model base
"""
import os
import sys
import re
import subprocess
import argparse
from pathlib import Path

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ.setdefault("TORCH_HOME", os.path.join(PROJECT_ROOT, "models"))


def hr(title):
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def step(label, msg):
    print(f"  [{label}] {msg}")


def parse_args():
    parser = argparse.ArgumentParser(description="一站式视频翻译管线")
    parser.add_argument("video", nargs="?", help="视频路径")
    parser.add_argument(
        "--lang", default=None,
        help="视频源语言代码（如 en, ja），指定后启用 wav2vec2 时间戳精修"
    )
    parser.add_argument(
        "--model", default="small",
        help="whisper 模型大小 (tiny/base/small/medium)"
    )
    parser.add_argument(
        "--device", default="cpu",
        help="计算设备 (cpu)"
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="保留中间文件（默认自动清理）"
    )
    parser.add_argument(
        "--skip-extract", action="store_true",
        help="跳过字幕提取（已有字幕时使用）"
    )
    parser.add_argument(
        "--skip-translate", action="store_true",
        help="跳过翻译（已有中文翻译时使用）"
    )
    parser.add_argument(
        "--tts-voice", default="zh-CN-XiaoxiaoNeural",
        help="TTS 发音人（默认 zh-CN-XiaoxiaoNeural）"
    )
    parser.add_argument(
        "--tts-workers", type=int, default=3,
        help="TTS 并发线程数（默认 3）"
    )
    return parser.parse_args()


def get_output_paths(video_path):
    """根据视频路径生成标准输出路径。"""
    video_path = os.path.abspath(video_path)
    video_dir = os.path.dirname(video_path)
    name = os.path.splitext(os.path.basename(video_path))[0]
    out_dir = os.path.join(video_dir, f"{name}_out")

    return {
        "video": video_path,
        "out_dir": out_dir,
        "name": name,
        # extract_subtitles 输出
        "srt": os.path.join(out_dir, f"{name}.srt"),
        "instrumental": os.path.join(out_dir, f"{name}_(Instrumental).wav"),
        # 翻译输出
        "srt_zh": os.path.join(out_dir, f"{name}-zh.srt"),
        "srt_zh_replace": os.path.join(out_dir, f"{name}-zh-replace.srt"),
        # TTS 输出
        "tts_output": os.path.join(out_dir, f"{name}-TTS.mp4"),
    }


def step_1_extract(paths, args):
    """步骤 1: 字幕提取（调用 extract_subtitles.py）"""
    hr(f"步骤 1/4: 字幕提取 — {paths['name']}")

    extract_script = os.path.join(PROJECT_ROOT, "extract_subtitles.py")
    cmd = [
        sys.executable, extract_script,
        paths["video"],
        "--out-dir", paths["out_dir"],
        "--model", args.model,
        "--device", args.device,
    ]
    if args.lang:
        cmd.extend(["--lang", args.lang])

    step("EXTRACT", f"运行: {' '.join(cmd[-8:])}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"❌ 字幕提取失败 (code={result.returncode})")
        sys.exit(result.returncode)

    # 验证输出
    for key in ["srt", "instrumental"]:
        p = paths[key]
        if os.path.isfile(p):
            sz = os.path.getsize(p)
            step("EXTRACT", f"✅ {key}: {p} ({sz:,} bytes)")
        else:
            step("EXTRACT", f"⚠️ {key} 未生成: {p}")

    return paths


def step_2_translate(paths):
    """步骤 2: SRT 翻译 + 术语替换"""
    hr(f"步骤 2/4: SRT 翻译 — {paths['name']}")

    from SRT.SRT_Translator import SRTTranslator
    from SRT.TermReplacer import TermReplacer

    if not os.path.isfile(paths["srt"]):
        print(f"❌ 找不到原文 SRT: {paths['srt']}")
        sys.exit(1)

    # 2a: 翻译
    translator = SRTTranslator()
    step("TRANSLATE", f"输入: {paths['srt']}")
    zh_srt_path, pending = translator.translate(paths["srt"])

    if pending:
        print(f"\n⚠️ 有 {translator.log.manual_pending if hasattr(translator.log, 'manual_pending') else '?'} 组需要人工翻译")
        print(f"待翻文件: {pending}")
        print("请完成人工翻译后重新运行（加 --skip-translate）")
        sys.exit(0)

    # SRTTranslator 的输出文件通常叫 {name}-ZH_CN.srt
    # 我们重命名为标准名
    if os.path.isfile(zh_srt_path) and zh_srt_path != paths["srt_zh"]:
        import shutil
        shutil.move(zh_srt_path, paths["srt_zh"])
        step("TRANSLATE", f"翻译输出: {paths['srt_zh']}")

    # 2b: 术语替换
    if not os.path.isfile(paths["srt_zh"]) and os.path.isfile(zh_srt_path):
        paths["srt_zh"] = zh_srt_path

    replacer = TermReplacer()
    step("REPLACE", f"术语替换: {paths['srt_zh']}")
    replacer.replace_file(paths["srt_zh"], paths["srt_zh_replace"])
    step("REPLACE", f"替换完成: {paths['srt_zh_replace']}")

    return paths


def step_3_tts(paths, args):
    """步骤 3: TTS 语音合成"""
    hr(f"步骤 3/4: TTS 语音合成 — {paths['name']}")

    # 验证必要文件
    missing = []
    for k in ["instrumental"]:
        p = paths[k]
        if not os.path.isfile(p):
            missing.append(f"{k}={p}")
    if missing:
        print(f"❌ 缺少必要文件:\n  " + "\n  ".join(missing))
        sys.exit(1)

    from pipeline.tts_adapter import TTSAdapter

    tts = TTSAdapter(
        video_path=paths["video"],
        video_instrumental_path=paths["instrumental"],
        chinese_srt_path=paths["srt_zh_replace"],
        english_srt_path=paths["srt"],
        TTS_audio_output_path=os.path.join(paths["out_dir"], "tts_audio"),
        clone_color=False,
        threading_workers=args.tts_workers,
    )
    tts.model_version = "v2"
    tts.voice = args.tts_voice

    step("TTS", "开始合成...")
    tts.EdgeTTS_TXT_To_Audio()
    step("TTS", "合成完成 ✅")
    return paths


def step_4_concat(paths):
    """步骤 4: 拼接视频段"""
    hr(f"步骤 4/4: 拼接最终视频 — {paths['name']}")

    for candidate in ("video", "video_file", "Video_file", "Vdieo"):
        video_dir = os.path.join(paths["out_dir"], candidate)
        if os.path.isdir(video_dir):
            break
    else:
        print(f"❌ 找不到视频段目录 ({paths['out_dir']}/video)，跳过拼接")
        return paths

    # 使用纯 ffmpeg 拼接视频段
    step("CONCAT", f"拼接 {video_dir} → {paths['tts_output']}")
    _concat_video_segments(video_dir, paths["tts_output"])
    if os.path.isfile(paths["tts_output"]):
        sz = os.path.getsize(paths["tts_output"])
        step("CONCAT", f"✅ 最终视频: {paths['tts_output']} ({sz/1024/1024:.1f}MB)")

    return paths


def _concat_video_segments(target_dir: str, output_path: str):
    """使用 ffmpeg concat 拼接目录下的所有 mp4 视频段。"""
    import subprocess

    video_files = [
        os.path.join(os.path.abspath(target_dir), f)
        for f in os.listdir(target_dir)
        if f.lower().endswith(".mp4")
    ]
    if not video_files:
        print(f"❌ {target_dir} 下没有 mp4 文件")
        return

    # 按文件名中的起始时间排序 (TTS_{start}_{end}.mp4)
    sorted_files = sorted(video_files, key=lambda x: int(x.split("_")[-2]))

    # 使用 concat demuxer (无需重新编码，速度快)
    list_path = os.path.join(target_dir, "video_sorted.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for v in sorted_files:
            f.write(f"file '{v}'\n")

    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ]
    print(f"  [CONCAT] ffmpeg {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main():
    args = parse_args()

    # 默认视频
    video = args.video or os.path.join(
        PROJECT_ROOT, "source_file", "test.mp4"
    )
    if not os.path.isfile(video):
        print(f"❌ 视频不存在: {video}")
        sys.exit(1)

    paths = get_output_paths(video)
    os.makedirs(paths["out_dir"], exist_ok=True)

    print()
    print(f"  视频:       {video}")
    print(f"  语言:       {args.lang or '自动检测'}")
    print(f"  输出目录:   {paths['out_dir']}")
    print(f"  最终输出:   {paths['tts_output']}")

    # ── 执行各步骤 ──
    if not args.skip_extract:
        paths = step_1_extract(paths, args)
    else:
        hr("步骤 1/4: 字幕提取 — 已跳过 (--skip-extract)")

    if not args.skip_translate:
        paths = step_2_translate(paths)
    else:
        hr("步骤 2/4: SRT 翻译 — 已跳过 (--skip-translate)")

    paths = step_3_tts(paths, args)
    paths = step_4_concat(paths)

    # ── 完成 ──
    hr("完成 🎉")
    print(f"  输出目录:   {paths['out_dir']}")
    print(f"  最终视频:   {paths['tts_output']}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
