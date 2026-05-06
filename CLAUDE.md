# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all TTS tests (15 test files, 211 tests)
.venv\Scripts\python -m pytest tests/test_tts/ -v

# Run a single test file
.venv\Scripts\python -m pytest tests/test_tts/test_tts_edge.py -v

# Run a single test
.venv\Scripts\python -m pytest tests/test_tts/test_tts_edge.py::test_synthesize_basic -v

# Run the full 3-step pipeline (extract → translate → TTS)
.venv\Scripts\python main.py source_file/test.mp4 --lang en

# Extract subtitles only (no translate, no TTS)
.venv\Scripts\python extract_subtitles.py source_file/test.mp4 --lang en --model small

# Skip Demucs vocal separation (faster, for clean audio)
.venv\Scripts\python main.py source_file/test.mp4 --lang en --skip-demucs

# Translate an existing SRT file
.venv\Scripts\python -m SRT.SRT_Translator path/to/file.srt

# Start WebUI backend
.venv\Scripts\python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000
```

## Architecture

This is a video translation pipeline: **extract subtitles → translate → TTS synthesize → merge video segments** back into a final video with dubbed audio and bilingual captions.

### Two parallel entry points

| Entry point | Steps | When to use |
|---|---|---|
| `main.py` | extract → translate → TTS (3 steps) | Recommended; calls `extract_subtitles.py` as subprocess; supports `--skip-demucs`, `--skip-defect-check`, `--skip-extract/translate/tts`, `--backup-dir`, 13 caption customization flags, `--no-optimize-subtitles` |
| `translate_video.py` | extract → translate → TTS → merge (4 steps) | Legacy; uses `TTSAdapter` compat layer |

### Subtitle extraction dataflow (extract_subtitles.py)

```
NODE 1   video_info.py          → ffmpeg -i metadata
NODE 1.5 MediaValidator         → C2 defect diagnosis (AAC padding gap)
NODE 2   audio.py               → audio extraction + aresample fix
NODE 2.5 demucs_instr.py        → Demucs vocal/instrumental separation
NODE 3   transcriber.py         → Silero VAD + faster-whisper transcription
NODE 3.5 whisperx_local/        → wav2vec2 CTC forced alignment (~20ms precision)
NODE 4   Json_Convert_Srt       → JSON → SRT (with MeCab for Japanese)
```

Modules communicate through the filesystem: output paths are passed between steps.

### TTS pipeline (pipeline/tts_*.py)

TTS engines implement `BaseTTSEngine` (Protocol, not ABC). The protocol requires `synthesize(text, output_path, rate, emotion) -> float`.

**Engine implementations:**
- `tts_edge.py` — Edge TTS (Microsoft cloud, default; MP3 → PCM WAV via ffmpeg)
- `tts_chattts.py` — ChatTTS (local/offline, Chinese-optimized)

**Supporting modules:**
- `gpu_detect.py` — auto-detect GPU encoder (h264_nvenc/h264_amf/libx264), applies best encoder + preset to config
- `speed_strategy.py` — two speed adjustment strategies: `PerSegmentStrategy` (per-segment speed) and `GlobalStrategy` (uniform global speed), chosen via `create_strategy()`
- `tts_timing.py` — `TimingAdjuster` aligns TTS audio to video segment duration
- `tts_video.py` — `VideoSegmenter` crops/slows/speeds video segments, mixes audio via ffmpeg
- `tts_caption.py` — `CaptionRenderer` renders bilingual captions onto video frames
- `caption_config.py` — `CaptionConfig` dataclass for YAML-based caption style management
- `subtitle_optimizer.py` — splits long subtitle lines by writing-system-aware break points, redistributes timestamps proportionally
- `video_merger.py` — `VideoMerger` concatenates per-segment .mp4 files via ffmpeg concat demuxer (with MoviePy fallback)
- `tts_pipeline.py` — `TtsPipeline` orchestrates the full per-segment flow
- `tts_resume.py` — `ResumeManager` for progress save/restore

**Timing strategy:** Two-tier decision via `speed_strategy.py`:
1. TTS duration within ±15% of video segment → adjust video playback speed (visually imperceptible)
2. Beyond ±15% → regenerate TTS at different rate, up to max_speed. If still over → video slowdown as last resort.

**Per-segment flow:** crop video segment → extract instrumental segment → TTS synthesize → `TimingAdjuster.align()` → `VideoSegmenter.slow_down_video_to_file()` (mixes audio via ffmpeg amix, avoiding MoviePy's float32 pipeline which causes audio artifacts) → add captions → write .mp4 segment → `VideoMerger.merge()` concat all segments.

**Key fix:** All WAV manipulation uses ffmpeg directly (not MoviePy) to avoid "electric" audio artifacts caused by the s16le → float32 → s32le conversion chain.

### Translation (SRT/)

`SRT_Translator.py` uses DeepSeek API with a 3-tier fallback: batch (8/group) → single → manual. `TranslationVerifier.py` does cross-lingual semantic similarity checking with sentence-transformers (threshold 0.65). `TermReplacer.py` applies a terminology dictionary post-translation. `LANGUAGE_PRESETS.py` provides per-language SRT formatting presets (max_chars, min_duration, formatter). `Json_Convert_Srt_JP.py` is the Japanese-specific JSON→SRT converter (MeCab-based).

### Config system

Three YAML files (see `config/`):
- `translate.yaml` — DeepSeek API key, model, rate limits, semantic check settings
- `tts.yaml` — engine type, voice, speed params, codec settings, ImageMagick path
- `caption.yaml` — font, colors, stroke, alignment, subtitle optimization

`config/translate.yaml` is gitignored (contains API key). `translate.yaml.example` is the template.

### Critical implementation details

- **Python 3.12** — portable Python at `.python/` with CUDA torch 2.6.0+cu124. Use `.venv/Scripts/python` for all commands.
- **GPU support** — CUDA available (RTX 3060 Ti). whisper uses CUDA via ctranslate2 (device="cuda", not "gpu"). Falls back to CPU if CUDA unavailable.
- `gpu_detect.py` auto-picks h264_nvenc if available, falls back to libx264.
- **C2 defect fix** — OBS-recorded MP4s have AAC padding that causes audio duration < container duration. Fixed with `aresample=async=1:first_pts=0` + `-t <CD>` during audio extraction.
- **Model storage** — all models cached locally in `models/` (gitignored). HF endpoint defaults to `hf-mirror.com` for China users.
- **Resume** — `ResumeManager` checks for existing `TTS_{start}_{end}.mp4` files; no separate state file.
- **Backup** — `main.py --backup-dir <dir>` auto-saves intermediate artifacts after each step (extract/translate/TTS) with timestamp labels.
- **Skip flags** — `--skip-demucs` (skip vocal separation for clean audio) and `--skip-defect-check` (skip C2 diagnosis) can speed up the pipeline when source quality is known good.
- **Submodules are vendored** — `spleeter/`, `OpenVoice/`, `SwinIR/`, `Minecraft_dict/` are vendored copies, not the active pipeline. Only `pipeline/`, `SRT/`, `whisperx_local/`, and `openvoice_cli/` are actively used.

## Project docs

- `ARCHITECTURE.md` — full dataflow diagrams, design decisions, ADRs
- `README.md` — quickstart, CLI reference, config reference, module tree
- `docs/tts-engine-research-2026.md` — TTS engine comparison research
- `docs/voice-cloning-research-2026.md` — voice cloning feasibility research
