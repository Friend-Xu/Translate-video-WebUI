"""Quick single-segment TTS + mix test with real ChatTTS audio."""
import os, sys, subprocess, json
import numpy as np
import soundfile as sf

PROJ = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ)

WORKSPACE = os.path.join(PROJ, "source_file",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric_project")
VIDEO_PATH = os.path.join(PROJ, "source_file",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric.mp4")
INSTR_PATH = os.path.join(WORKSPACE, "01_extract", "instrumental.wav")

# Pick a segment with substantial text
start, end = 18649, 29109  # ~10s segment
video_end = 29510
text_cn = "确保你们全程观看，因为这些整合包只会越来越好，你不会错过目前最好的整合包"

print("Phase 1: ChatTTS synthesis...")
from pipeline.tts_chattts import ChatTTSEngine

engine = ChatTTSEngine(speaker_seed=2, model_source="local")
engine.warmup()

out_dir = os.path.join(WORKSPACE, "03_tts", "audio")
os.makedirs(out_dir, exist_ok=True)
wav_path = os.path.join(out_dir, f"_test_single_{start}_{end}.wav")

wav_time = engine.synthesize(text_cn, wav_path, "+40%")
print(f"TTS done: {wav_path} ({wav_time:.2f}s)")
engine.cleanup()

# LUFS
from pipeline.tts_config import TTSConfig
cfg = TTSConfig.from_yaml(os.path.join(PROJ, "config", "tts.yaml"))
cfg.engine_type = "chattts"
cfg.output_dir = os.path.join(WORKSPACE, "03_tts")

from pipeline.loudness import normalize_segment_loudness
normalize_segment_loudness(wav_path, target_lufs=-13.1)

# Now mix with BGM using both codecs
from moviepy import VideoFileClip, AudioFileClip
from pipeline.tts_video import VideoSegmenter

seg = VideoSegmenter(
    video_output_dir=os.path.join(WORKSPACE, "03_tts", "video"),
    clone_color=False, caption=False,
    voice_cloner_callback=None, caption_renderer=None,
    video_bitrate=cfg.video_bitrate, video_codec=cfg.video_codec,
    video_preset=cfg.video_preset, audio_codec=cfg.audio_codec,
    bgm_volume=getattr(cfg, "bgm_volume", 1.0),
    video_speed_min=getattr(cfg, "video_speed_min", 0.5),
    video_speed_max=getattr(cfg, "video_speed_max", 2.0),
)

current_video = VideoFileClip(VIDEO_PATH).subclipped(start/1000, video_end/1000)
instr_audio = AudioFileClip(INSTR_PATH)
tts_audio = AudioFileClip(wav_path)

video_dir = os.path.join(WORKSPACE, "03_tts", "video")

# Version 1: pcm_s32le (current config)
print("Generating pcm_s32le version...")
seg.audio_codec = "pcm_s32le"
out_s32 = os.path.join(video_dir, f"_REAL_TTS_pcm_s32le.mp4")
seg.slow_down_video_to_file(current_video, instr_audio, tts_audio,
    wav_path, start, text_cn, "", end, caption_groups=None)
# Rename from TTS_ to _REAL_TTS_
actual = os.path.join(video_dir, f"TTS_{start}_{end}.mp4")
if os.path.isfile(actual):
    os.replace(actual, out_s32)
print(f"  -> {out_s32}")

# Version 2: pcm_s16le (proposed fix)
print("Generating pcm_s16le version...")
seg.audio_codec = "pcm_s16le"
out_s16 = os.path.join(video_dir, f"_REAL_TTS_pcm_s16le.mp4")
# Need fresh clips since slow_down_video_to_file closes them
current_video2 = VideoFileClip(VIDEO_PATH).subclipped(start/1000, video_end/1000)
instr_audio2 = AudioFileClip(INSTR_PATH)
tts_audio2 = AudioFileClip(wav_path)
seg.slow_down_video_to_file(current_video2, instr_audio2, tts_audio2,
    wav_path, start, text_cn, "", end, caption_groups=None)
actual2 = os.path.join(video_dir, f"TTS_{start}_{end}.mp4")
if os.path.isfile(actual2):
    os.replace(actual2, out_s16)
print(f"  -> {out_s16}")

# Clean up
current_video.close(); current_video2.close()
instr_audio.close(); instr_audio2.close()
tts_audio.close(); tts_audio2.close()

print("\nDone! Compare these two files:")
print(f"  pcm_s32le: {out_s32}")
print(f"  pcm_s16le: {out_s16}")
