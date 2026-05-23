"""
Minimal CLI test: emotion + ChatTTS using existing workspace.
Tests per_segment mode with emotion prompts cached in 03_tts/emotion_prompts.json.
"""
import os, sys

PROJ_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ_ROOT)

VIDEO = os.path.join(PROJ_ROOT, "source_file",
    "The Best UNDERRATED Minecraft Mods You Gotta Have! [+1.20.1, +1.21.1 ｜ Forge ⧸ Fabric]",
    "The Best UNDERRATED Minecraft Mods You Gotta Have! [+1.20.1, +1.21.1 ｜ Forge ⧸ Fabric].mp4")
stem = os.path.splitext(os.path.basename(VIDEO))[0]
ws = os.path.join(os.path.dirname(VIDEO), f"{stem}_project")

from pipeline.tts_config import TTSConfig, parse_srt
from pipeline.tts_pipeline import TtsPipeline

cfg = TTSConfig()
cfg.engine_type = "chattts"
cfg.enable_emotion = True
cfg.speed_mode = "per_segment"
cfg.output_dir = os.path.join(ws, "03_tts")
cfg.video_output_dir = os.path.join(cfg.output_dir, "video")
cfg.enable_merge = False

# Only test 3 diverse segments
srt_path = os.path.join(ws, "02_translate", "machine.srt")
all_subs = parse_srt(srt_path)
print(f"Total SRT segments: {len(all_subs)}")

test_subs = []
picks = ["0_3859", "6179_9070", "291915_297776"]  # happy, neutral, fearful
for pk in picks:
    start, end = int(pk.split("_")[0]), int(pk.split("_")[1])
    for s, e, t in all_subs:
        if s == start and e == end:
            test_subs.append((s, e, t))
            break
if not test_subs:
    print("Using first 3 segments as fallback")
    test_subs = all_subs[:3]

print(f"Test segments ({len(test_subs)}):")
for s, e, t in test_subs:
    print(f"  {s}_{e}: {t[:60]}...")

# Write temp SRT
test_srt = os.path.join(cfg.output_dir, "_test_machine.srt")
from SRT.Json_Convert_Srt_EN import gen_srt
gen_srt(test_subs, test_srt)

source_srt = os.path.join(ws, "01_extract", "source.srt")
instrumental = os.path.join(ws, "01_extract", "instrumental.wav")
if not os.path.exists(instrumental):
    instrumental = None

print(f"\nRunning TtsPipeline: enable_emotion={cfg.enable_emotion}, engine={cfg.engine_type}")

pipeline = TtsPipeline(cfg)
try:
    pipeline.run(
        video_path=VIDEO,
        instrumental_path=instrumental,
        translated_srt_path=test_srt,
        source_srt_path=source_srt,
    )
    print("\n✓ Pipeline completed — NameError bug is FIXED")
except NameError as e:
    print(f"\n✗ NameError: {e}")
    sys.exit(1)
except Exception as e:
    import traceback
    if "_emo_prompts" in str(e):
        print(f"\n✗ Still broken: {e}")
        sys.exit(1)
    print(f"\n! {type(e).__name__}: {e}")
    traceback.print_exc()
