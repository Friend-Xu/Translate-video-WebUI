"""Isolated test: Phase 3 video mix only (no TTS, no speed adjust).

Take a known-good TTS WAV → pass through slow_down_video_to_file
→ compare input vs output audio for speed and distortion.
"""

import os, sys, tempfile, subprocess, json
import numpy as np
import soundfile as sf

PROJ = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ)

WORKSPACE = os.path.join(
    PROJ, "source_file",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric_project",
)
VIDEO_PATH = os.path.join(
    PROJ, "source_file",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric.mp4",
)
INSTR_PATH = os.path.join(WORKSPACE, "01_extract", "instrumental.wav")
AUDIO_DIR = os.path.join(WORKSPACE, "03_tts", "audio")
VIDEO_DIR = os.path.join(WORKSPACE, "03_tts", "video")

# ── Test setup ──────────────────────────────────────────
from pipeline.tts_config import TTSConfig
from pipeline.tts_video import VideoSegmenter

cfg = TTSConfig.from_yaml(os.path.join(PROJ, "config", "tts.yaml"))
cfg.engine_type = "chattts"
cfg.output_dir = os.path.join(WORKSPACE, "03_tts")

seg = VideoSegmenter(
    video_output_dir=VIDEO_DIR,
    clone_color=False,
    caption=False,
    voice_cloner_callback=None,
    caption_renderer=None,
    video_bitrate=cfg.video_bitrate,
    video_codec=cfg.video_codec,
    video_preset=cfg.video_preset,
    audio_codec=cfg.audio_codec,
    bgm_volume=getattr(cfg, "bgm_volume", 0.5),
    video_speed_min=getattr(cfg, "video_speed_min", 0.5),
    video_speed_max=getattr(cfg, "video_speed_max", 2.0),
)
print(f"VideoSegmenter: codec={cfg.video_codec}, audio_codec={cfg.audio_codec}, "
      f"bgm_vol={getattr(cfg, 'bgm_volume', 'N/A')}")

# ── Pick 3 test segments of different lengths ────────────
test_segs = [
    ("115870_117370", 115870, 117370, 118042),  # short (~1s)
    ("18649_29109", 18649, 29109, 29510),        # medium (~10s)
    ("102370_106530", 102370, 106530, 106790),    # medium-short (~4s)
]

from moviepy import VideoFileClip, AudioFileClip
ffprobe = "ffprobe"

for seg_name, start, end, video_end in test_segs:
    wav_path = os.path.join(AUDIO_DIR, f"audio_{seg_name}.wav")
    if not os.path.isfile(wav_path):
        print(f"\nSKIP {seg_name}: WAV not found")
        continue

    print(f"\n{'='*60}")
    print(f"Testing: {seg_name}  start={start}ms  end={end}ms  video_end={video_end}ms")
    print(f"  Segment duration: {(end-start)/1000:.2f}s")
    print(f"  Video span: {(video_end-start)/1000:.2f}s")

    # Read source WAV info
    wav_info = json.loads(subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", wav_path],
        capture_output=True, text=True).stdout)
    wav_stream = wav_info["streams"][0]
    wav_dur = float(wav_stream["duration"])
    print(f"  Source WAV: {wav_dur:.4f}s, {wav_stream['sample_rate']}Hz, "
          f"ch={wav_stream['channels']}, codec={wav_stream['codec_name']}")

    # Load audio clips
    current_video = VideoFileClip(VIDEO_PATH).subclipped(start / 1000, video_end / 1000)
    print(f"  Video clip: {current_video.duration:.4f}s")

    instrumental_audio = AudioFileClip(INSTR_PATH) if os.path.isfile(INSTR_PATH) else None
    tts_audio = AudioFileClip(wav_path)
    print(f"  TTS clip: fps={tts_audio.fps}, nchannels={tts_audio.nchannels}, "
          f"dur={tts_audio.duration:.4f}s")

    # ── Run Phase 3: slow_down_video_to_file ──
    out_mp4 = os.path.join(VIDEO_DIR, f"_ISOLATED_TEST_{seg_name}.mp4")
    try:
        seg.slow_down_video_to_file(
            current_video, instrumental_audio, tts_audio,
            wav_path, start, "TEST_ZH", "TEST_EN", end,
            caption_groups=None,
        )
        # Rename output for inspection
        actual_out = os.path.join(VIDEO_DIR, f"TTS_{start}_{end}.mp4")
        if os.path.isfile(actual_out):
            os.replace(actual_out, out_mp4)
    except Exception as e:
        print(f"  [FAIL] slow_down_video_to_file: {e}")
        import traceback
        traceback.print_exc()
        continue
    finally:
        current_video.close()
        tts_audio.close()
        if instrumental_audio:
            instrumental_audio.close()

    if not os.path.isfile(out_mp4):
        print(f"  [FAIL] Output MP4 not created")
        continue

    # ── Analyze output MP4 ──
    mp4_info = json.loads(subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", out_mp4],
        capture_output=True, text=True).stdout)
    mp4_audio = next((s for s in mp4_info["streams"] if s["codec_type"] == "audio"), None)
    mp4_video = next((s for s in mp4_info["streams"] if s["codec_type"] == "video"), None)

    if mp4_audio:
        mp4_adur = float(mp4_audio["duration"])
        print(f"  Output MP4 audio: {mp4_adur:.4f}s, {mp4_audio['sample_rate']}Hz, "
              f"ch={mp4_audio['channels']}, codec={mp4_audio['codec_name']}")
        dur_ratio = wav_dur / mp4_adur
        print(f"  WAV/MP4 duration ratio: {dur_ratio:.3f} (should be ~1.0)")
        if dur_ratio > 1.05:
            print(f"  *** WARNING: MP4 audio is {((1-dur_ratio)*100):.1f}% FASTER than source!")
        elif dur_ratio < 0.95:
            print(f"  *** WARNING: MP4 audio is {((dur_ratio-1)*100):.1f}% SLOWER than source!")

    if mp4_video:
        print(f"  Output MP4 video: {float(mp4_video['duration']):.4f}s")

    # ── Extract MP4 audio and compare waveform ──
    extracted = out_mp4 + ".extracted.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", out_mp4, "-acodec", "pcm_s16le", extracted],
        capture_output=True, timeout=30, encoding="utf-8", errors="replace",
    )

    if os.path.isfile(extracted):
        mp4_data, mp4_sr = sf.read(extracted)
        tts_data, tts_sr = sf.read(wav_path)

        print(f"  Extracted MP4 audio: shape={mp4_data.shape}, sr={mp4_sr}")
        print(f"  Source TTS audio: shape={tts_data.shape}, sr={tts_sr}")

        # Channel analysis
        if mp4_data.ndim > 1:
            for ch in range(mp4_data.shape[1]):
                ch_data = mp4_data[:, ch]
                ch_rms = np.sqrt(np.mean(ch_data ** 2))
                print(f"    MP4 ch{ch}: max={np.max(np.abs(ch_data)):.4f}, "
                      f"RMS={ch_rms:.4f}, min={ch_data.min():.4f}, max_val={ch_data.max():.4f}")

            # Check if both channels have signal
            ch0_rms = np.sqrt(np.mean(mp4_data[:, 0] ** 2))
            ch1_rms = np.sqrt(np.mean(mp4_data[:, 1] ** 2))
            if abs(ch0_rms - ch1_rms) < max(ch0_rms, ch1_rms) * 0.1:
                print(f"    ✓ Both channels match (L-R diff < 10%)")
            elif ch0_rms < ch1_rms * 0.1:
                print(f"    ✗ LEFT CHANNEL IS SILENT!")
            elif ch1_rms < ch0_rms * 0.1:
                print(f"    ✗ RIGHT CHANNEL IS SILENT!")

        # Check for zero runs (stuttering)
        mono = mp4_data[:, 0] if mp4_data.ndim > 1 else mp4_data
        zero_mask = np.abs(mono) < 1e-6
        zero_runs = []
        in_zero = False
        zs = 0
        for i in range(len(mono)):
            if zero_mask[i]:
                if not in_zero:
                    zs = i
                    in_zero = True
            else:
                if in_zero and i - zs > mp4_sr // 10:  # >100ms gap
                    zero_runs.append((zs / mp4_sr * 1000, (i - zs) / mp4_sr * 1000))
                in_zero = False
        if zero_runs:
            print(f"    ! ZERO GAPS in MP4 audio: {len(zero_runs)} found (>100ms)")
            for gap_start_ms, gap_len_ms in zero_runs[:5]:
                print(f"      gap at {gap_start_ms:.0f}ms for {gap_len_ms:.0f}ms")
        else:
            print(f"    ✓ No significant zero gaps")

        # Cross-correlation for speed detection
        from scipy.signal import correlate
        mlen = min(len(tts_data), len(mono))
        if mlen > 100:
            corr = correlate(tts_data[:mlen], mono[:mlen], mode="same")
            peak_lag = np.argmax(np.abs(corr)) - len(corr) // 2
            peak_ms = peak_lag / tts_sr * 1000
            peak_corr = np.max(np.abs(corr))
            print(f"  Cross-corr peak: lag={peak_lag}samples ({peak_ms:.1f}ms), value={peak_corr:.1f}")
            if abs(peak_ms) < 50:
                print(f"  ✓ Timing aligned (within 50ms)")
            else:
                print(f"  ✗ TIMING MISMATCH: {peak_ms:.1f}ms offset!")

        os.unlink(extracted)

    # Clean up test output
    # os.unlink(out_mp4)

print(f"\n{'='*60}")
print("Isolated mix test complete.")
