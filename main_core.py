#!/usr/bin/env python3
"""
main_core.py — 使用新 core/ PassManager 架构处理视频

与 main.py 并行：复用 extract + TTS 步骤，中间翻译用 core/ 流水线。
"""
from __future__ import annotations
import argparse, json, os, sys, time, requests

if os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128"
os.environ.setdefault("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.isabs(sys.path[0]):
    sys.path[0] = ""

from core.passes import ASRToIRPass, SemanticMergePass, LLMTranslationPass, SRTExportPass
from core.engine import PassManager
from core.runtime import SynthesisEngine, TimelineProjectState
from core.ir import TimelineProjectIR

from main import (
    _workspace_dir, workspace_paths, PipelineCheckpoint,
    step_extract, step_tts, guess_source_srt,
)
from pipeline.logger import get_logger
logger = get_logger("main_core")


def _load_translate_config():
    cfg_path = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
    import yaml
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("translate", {})

def create_translate_fn():
    cfg = _load_translate_config()
    api_key = cfg.get("api_key", "")
    model = cfg.get("model", "deepseek-chat")
    base_url = "https://api.deepseek.com"

    def translate_fn(tagged_text: str) -> str:
        system_prompt = (
            "你是一个专业字幕翻译器。输入是带标签的多行文本，每行格式: [event_id] 原文。"
            "请将每行原文翻译为中文，并保持完全相同的 [event_id] 标签格式。"
            "不要添加任何额外说明，只返回翻译结果。"
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": tagged_text},
            ],
            "temperature": 0.1,
            "max_tokens": 4000,
        }
        resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    return translate_fn


def step_translate_core(video: str, force: bool = False) -> str:
    """步骤 2 (core): 使用 core/ PassManager 完成翻译 + SRT 导出。返回 translated SRT 路径。"""
    ws_dir = _workspace_dir(video)
    ws = workspace_paths(video) or {}
    ck = PipelineCheckpoint.load(ws_dir)

    if ck.is_step_done("translate_core") and not force:
        print("\n[2/3] 翻译 (core) — 已完成 (checkpoint)，跳过")
        return ws.get("machine_srt") or os.path.join(ws_dir, "02_translate", "machine.srt")

    logger.info("[STAGE] [2/4] core/ PassManager 翻译开始")
    print("\n[2/3] 翻译 (core PassManager)...")
    ck.start_step("translate_core")
    ck.save()

    transcript_path = os.path.join(ws_dir, "01_extract", "transcript.json")
    speaker_timeline_path = os.path.join(ws_dir, "01_extract", "speaker_timeline.json")

    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)
    segments = transcript.get("segments", [])

    speaker_timeline = None
    if os.path.exists(speaker_timeline_path):
        with open(speaker_timeline_path, "r", encoding="utf-8") as f:
            st_data = json.load(f)
        speaker_timeline = [
            (t["speaker"], t["start"], t["end"], t.get("confidence", 0.5))
            for t in st_data.get("turns", [])
        ]

    asr_pass = ASRToIRPass(segments=segments, speaker_timeline=speaker_timeline)

    pm = PassManager()
    pm.register(asr_pass)
    pm.register(SemanticMergePass())
    pm.register(LLMTranslationPass(translate_fn=create_translate_fn()))
    state = pm.run(TimelineProjectState(TimelineProjectIR({}, {})))
    print(f"  PassManager 完成: {len(state.ir.events)} events (合并后)")

    machine_srt = os.path.join(ws_dir, "02_translate", "machine.srt")
    os.makedirs(os.path.dirname(machine_srt), exist_ok=True)
    srt_pass = SRTExportPass(output_path=machine_srt)
    srt_pass.apply(state)

    synth = SynthesisEngine()
    rendered = synth.render_all(state)
    timeline_v2_path = os.path.join(ws_dir, "02_translate", "timeline_v2.json")
    with open(timeline_v2_path, "w", encoding="utf-8") as f:
        json.dump(rendered, f, ensure_ascii=False, indent=2)

    print(f"  SRT 导出: {machine_srt}")
    print(f"  Timeline v2: {timeline_v2_path}")
    ck.complete_step("translate_core")
    ck.save()
    print("  [OK] 翻译 (core) 完成")
    return machine_srt


def main():
    parser = argparse.ArgumentParser(description="Translate Video — core/ PassManager 架构")
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("--lang", default="zh")
    parser.add_argument("--engine", default="edge")
    parser.add_argument("--model", default="turbo")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--skip-demucs", action="store_true")
    parser.add_argument("--skip-align", action="store_true")
    parser.add_argument("--skip-defect-check", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--align-lang", default=None)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--enable-speaker-diarization", action="store_true")

    args = parser.parse_args()
    video = os.path.abspath(args.video)
    force = args.force

    if not os.path.exists(video):
        print(f"[ERROR] 视频文件不存在: {video}")
        sys.exit(1)

    ws_dir = _workspace_dir(video)
    t0 = time.time()

    # Step 1: Extract
    step_extract(
        video, lang=args.lang, model=args.model,
        device=args.device, compute_type=args.compute_type,
        skip_defect_check=args.skip_defect_check,
        skip_demucs=args.skip_demucs,
        skip_align=args.skip_align,
        align_lang=args.align_lang,
        num_workers=args.num_workers,
        enable_speaker_diarization=args.enable_speaker_diarization,
        force=force,
    )

    # Step 2: Translate with core PassManager
    srt_translated = step_translate_core(video, force=force)
    srt_source = guess_source_srt(video) or os.path.join(ws_dir, "01_extract", "source.srt")

    # Step 3: TTS + Merge
    step_tts(
        video,
        srt_source=srt_source,
        srt_translated=srt_translated,
        engine=args.engine,
        config_path=None,
        caption_config_path=None,
        force=force,
    )

    elapsed = time.time() - t0
    print(f"\n{'='*50}")
    print(f"[OK] 全部完成 (core 架构)! 耗时: {elapsed/60:.1f} 分钟")
    print(f"{'='*50}")
    ws = workspace_paths(video) or {}
    dubbed = ws.get("dubbed_mp4", os.path.join(ws_dir, "04_output", "dubbed.mp4"))
    if os.path.exists(dubbed):
        size_mb = os.path.getsize(dubbed) / 1024 / 1024
        print(f"  [OK] 最终视频: {dubbed} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
