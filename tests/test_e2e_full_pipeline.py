"""
E2E Full Pipeline Emotion Test — 20 segments.

Full flow: emotion extraction → dynamic ChatTTS → speed adjust → video mix → concat.

Zero pipeline modifications. Uses only public APIs and ffmpeg.

Usage:
    tests\_run_e2e_full.bat
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import time
import numpy as np

PROJ_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ_ROOT)

# ── Project paths ─────────────────────────────────────
STEM = "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric"
WORKSPACE = os.path.join(PROJ_ROOT, "source_file", STEM, f"{STEM}_project")
VIDEO_PATH = os.path.join(PROJ_ROOT, "source_file", STEM, f"{STEM}.mp4")
VOCALS_PATH = os.path.join(WORKSPACE, "01_extract", "vocals.wav")
INSTRUMENTAL_PATH = os.path.join(WORKSPACE, "01_extract", "htdemucs", STEM, "no_vocals.wav")
SRT_PATH = os.path.join(WORKSPACE, "02_translate", "machine.srt")

OUT_DIR = os.path.join(PROJ_ROOT, r"tests\e2e_full_output")
os.makedirs(OUT_DIR, exist_ok=True)

AUDIO_DIR = os.path.join(OUT_DIR, "audio")
VIDEO_DIR = os.path.join(OUT_DIR, "video")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

N_WORKERS = 4
SPEAKER_SEED = 2
N_SEGMENTS = 20

# ── Emotion mapping ────────────────────────────────────
EMOTION_PROMPT_MAP = {
    "生气/angry": (3,0,2), "厌恶/disgusted": (1,0,4), "恐惧/fearful": (2,0,4),
    "开心/happy": (6,1,4), "中立/neutral": (2,0,5), "其他/other": (2,0,5),
    "难过/sad": (1,0,6), "吃惊/surprised": (4,0,3), "<unk>": (2,0,5),
}
LABEL_ORDER = [
    "生气/angry","厌恶/disgusted","恐惧/fearful","开心/happy",
    "中立/neutral","其他/other","难过/sad","吃惊/surprised","<unk>",
]
FIXED_PROMPT = "[oral_0][break_5]"


def scores_to_prompt(scores):
    oral = sum(EMOTION_PROMPT_MAP[l][0]*s for l,s in zip(LABEL_ORDER, scores) if l in EMOTION_PROMPT_MAP)
    laugh = sum(EMOTION_PROMPT_MAP[l][1]*s for l,s in zip(LABEL_ORDER, scores) if l in EMOTION_PROMPT_MAP)
    break_ = sum(EMOTION_PROMPT_MAP[l][2]*s for l,s in zip(LABEL_ORDER, scores) if l in EMOTION_PROMPT_MAP)
    return f"[oral_{max(0,min(9,int(round(oral))))}][laugh_{max(0,min(2,int(round(laugh))))}][break_{max(0,min(7,int(round(break_))))}]"


def main():
    t_total = time.time()
    print("=" * 60)
    print("E2E Full Pipeline: 20 segments with dynamic emotion prompts")
    print("=" * 60)

    # ── Prepare 20-segment SRT ──────────────────────────
    print("\n[Prep] Backing up SRT, writing 20-segment version...")
    with open(SRT_PATH, "r", encoding="utf-8") as f:
        full_srt = f.read()
    blocks = full_srt.strip().split("\n\n")
    print(f"  Total SRT blocks: {len(blocks)}, using {N_SEGMENTS}")
    with open(SRT_PATH, "w", encoding="utf-8") as f:
        f.write("\n\n".join(blocks[:N_SEGMENTS]) + "\n\n")

    try:
        # ── Parse SRT ───────────────────────────────────
        from pipeline.tts_config import parse_srt
        segments = parse_srt(SRT_PATH)
        print(f"  Parsed {len(segments)} segments")

        # ── Emotion extraction ───────────────────────────
        print("\n[Step 1] Emotion extraction per segment...")
        from funasr import AutoModel
        model = AutoModel(model="iic/emotion2vec_plus_large", hub="ms", disable_update=True)

        seg_prompts = []
        for i, (start_ms, end_ms, text) in enumerate(segments):
            dur = (end_ms - start_ms) / 1000.0
            if dur < 1.0:
                seg_prompts.append({"idx": i, "prompt": FIXED_PROMPT, "emotion": "short"})
                continue
            seg_wav = os.path.join(OUT_DIR, f"_seg_{i:03d}.wav")
            subprocess.run([
                "ffmpeg", "-y", "-v", "quiet", "-i", VOCALS_PATH,
                "-ss", str(start_ms/1000), "-t", str(dur + 0.1),
                "-ac", "1", "-ar", "16000", seg_wav
            ], check=True)
            result = model.generate(input=seg_wav, output_dir=None, granularity="utterance")
            if result and len(result) > 0:
                scores = result[0]["scores"]
                prompt = scores_to_prompt(scores)
                top_idx = max(range(9), key=lambda j: scores[j])
                seg_prompts.append({"idx": i, "prompt": prompt, "emotion": result[0]["labels"][top_idx]})
            else:
                seg_prompts.append({"idx": i, "prompt": FIXED_PROMPT, "emotion": "fail"})

        unique = set(p["prompt"] for p in seg_prompts)
        print(f"  Unique prompts: {len(unique)}/{len(seg_prompts)}")
        for i, p in enumerate(seg_prompts[:5]):
            print(f"  [{i}] {p['emotion']} -> {p['prompt']}")

        # ── ChatTTS synthesis ────────────────────────────
        print(f"\n[Step 2] ChatTTS synthesis ({N_WORKERS} workers, seed={SPEAKER_SEED})...")
        from pipeline.tts_chattts import ChatTTSEngine

        engines = [ChatTTSEngine(speaker_seed=SPEAKER_SEED, model_source="local")
                   for _ in range(N_WORKERS)]
        for i, e in enumerate(engines):
            print(f"  Warming up worker {i+1}/{N_WORKERS}...")
            e.warmup()

        t_tts = time.time()

        def synthesize_one(idx, text, prompt):
            engine = engines[idx % N_WORKERS]
            out_path = os.path.join(AUDIO_DIR, f"TTS_{idx:04d}.wav")
            dur = engine.synthesize(text, out_path, emotion=prompt)
            return {"idx": idx, "path": out_path, "dur": dur, "prompt": prompt}

        with concurrent.futures.ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
            futures = []
            for i, (start_ms, end_ms, text) in enumerate(segments):
                prompt = seg_prompts[i]["prompt"]
                futures.append(ex.submit(synthesize_one, i, text, prompt))
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        results.sort(key=lambda r: r["idx"])
        tts_elapsed = time.time() - t_tts
        print(f"  TTS done: {len(results)} segments in {tts_elapsed/60:.1f} min")

        # ── Speed adjustment (ffmpeg atempo) ──────────────
        print("\n[Step 3] Speed adjustment (ffmpeg atempo)...")
        for i, (start_ms, end_ms, text) in enumerate(segments):
            r = results[i]
            target_dur = (end_ms - start_ms) / 1000.0
            if r["dur"] > target_dur * 1.02:
                ratio = r["dur"] / target_dur
                adjusted_path = os.path.join(AUDIO_DIR, f"TTS_{i:04d}_adjusted.wav")
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error",
                    "-i", r["path"],
                    "-filter:a", f"atempo={1.0/ratio:.4f}",
                    "-ac", "1", "-ar", "44100",
                    adjusted_path,
                ], check=True)
                results[i]["adjusted_path"] = adjusted_path
                results[i]["adjusted_dur"] = target_dur * ratio  # approximate
            else:
                results[i]["adjusted_path"] = r["path"]
            if i < 3:
                print(f"  [{i}] dur={r['dur']:.2f}s target={target_dur:.2f}s")

        # ── Video segment assembly ───────────────────────
        print("\n[Step 4] Video segment assembly (crop + BGM mix)...")
        seg_videos = []

        for i, (start_ms, end_ms, text) in enumerate(segments):
            r = results[i]
            video_end = segments[i+1][0] if i+1 < len(segments) else end_ms
            crop_end = min(video_end + 500, end_ms + 2000)

            seg_video = os.path.join(VIDEO_DIR, f"seg_{i:04d}.mp4")
            audio_path = r.get("adjusted_path", r["path"])

            if os.path.exists(INSTRUMENTAL_PATH):
                mix_filter = (
                    f"[1:a]atrim={start_ms/1000}:{crop_end/1000},asetpts=PTS-STARTPTS[bgm];"
                    f"[2:a]aloop=loop=-1:size=2e9[tts];"
                    f"[bgm][tts]amix=inputs=2:duration=first:weights=0.3 1[amix]"
                )
            else:
                mix_filter = f"[2:a]aloop=loop=-1:size=2e9[amix]"

            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-i", VIDEO_PATH,
                "-i", INSTRUMENTAL_PATH if os.path.exists(INSTRUMENTAL_PATH) else VIDEO_PATH,
                "-i", audio_path,
                "-ss", str(start_ms / 1000),
                "-t", str((crop_end - start_ms) / 1000),
                "-filter_complex", mix_filter,
                "-map", "0:v", "-map", "[amix]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                seg_video,
            ]
            subprocess.run(cmd, check=True)
            seg_videos.append(seg_video)
            if i < 3:
                print(f"  [{i}] video={seg_video}")

        # ── Concatenate ──────────────────────────────────
        print("\n[Step 5] Concatenating segments...")
        concat_list = os.path.join(OUT_DIR, "concat_list.txt")
        with open(concat_list, "w") as f:
            for v in seg_videos:
                f.write(f"file '{v}'\n")

        final_video = os.path.join(OUT_DIR, "dubbed_emotion.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            final_video,
        ], check=True)

        total_elapsed = time.time() - t_total
        print(f"\n{'='*60}")
        print(f"Done! Total: {total_elapsed/60:.1f} min")
        print(f"Output: {final_video}")
        print(f"Segments: {len(seg_videos)} video, {len(results)} audio")
        print(f"Unique emotion prompts: {len(set(p['prompt'] for p in seg_prompts))}/{len(seg_prompts)}")
        print(f"{'='*60}")

    finally:
        with open(SRT_PATH, "w", encoding="utf-8") as f:
            f.write(full_srt)
        print("  SRT restored.")
        for e in engines:
            try:
                e.cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    main()
