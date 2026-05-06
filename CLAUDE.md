# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all TTS tests
.venv\Scripts\python -m pytest tests/test_tts/ -v

# Run a single test
.venv\Scripts\python -m pytest tests/test_tts/test_tts_edge.py::test_synthesize_basic -v

# Run VAD benchmark (compare JIT vs ONNX)
.venv\Scripts\python tests/benchmark_vad.py source_file/video.mp4 --quick

# Run the full 3-step pipeline (VAD + whisper + TTS)
.venv\Scripts\python main.py source_file/video.mp4 --lang ja

# Extract subtitles only (GPU + turbo defaults)
.venv\Scripts\python extract_subtitles.py source_file/video.mp4 --lang ja

# CPU fallback (if CUDA unavailable)
.venv\Scripts\python extract_subtitles.py source_file/video.mp4 --device cpu --compute-type int8

# Skip Demucs vocal separation (faster for clean audio)
.venv\Scripts\python main.py source_file/video.mp4 --lang en --skip-demucs

# Translate an existing SRT file
.venv\Scripts\python -m SRT.SRT_Translator path/to/file.srt

# Start WebUI backend
.venv\Scripts\python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000
```

## Architecture

This is a video translation pipeline: **extract subtitles → translate → TTS synthesize → merge video segments** into a final video with dubbed audio and bilingual captions.

### Two parallel entry points

| Entry point | Steps | When to use |
|---|---|---|
| `main.py` | extract → translate → TTS (3 steps) | Recommended; calls `extract_subtitles.py` as subprocess; supports `--skip-demucs`, `--skip-defect-check`, `--skip-extract/translate/tts`, `--backup-dir`, 13 caption flags |
| `translate_video.py` | extract → translate → TTS → merge (4 steps) | Legacy; uses `TTSAdapter` compat layer |

Both default to `--model turbo --device cuda --compute-type float16`. The subprocess chain is:

```
main.py → subprocess: extract_subtitles.py → subprocess: Demucs (NODE 2.5)
```

### Subtitle extraction dataflow (extract_subtitles.py)

```
NODE 1   video_info.py          → ffmpeg -i metadata
NODE 1.5 MediaValidator         → C2 defect diagnosis (AAC padding gap)
NODE 2   audio.py               → audio extraction + aresample fix
NODE 2.5 demucs_instr.py        → Demucs vocal/instrumental separation
NODE 3   transcriber.py         → Silero VAD (ONNX) + faster-whisper (CTranslate2)
NODE 3.5 whisperx_local/        → wav2vec2 CTC forced alignment (~20ms precision)
NODE 4   Json_Convert_Srt       → JSON → SRT (with MeCab for Japanese)
```

Modules communicate through the filesystem: output paths are passed between steps.

### VAD (SRT/VAD_Segmenter.py)

Silero VAD wrapper with ONNX Runtime as primary backend (~9x faster than PyTorch JIT). JIT is kept as automatic fallback if onnxruntime is unavailable. ONNX model at `models/vad/silero_vad.onnx`, JIT at `models/vad/silero_vad.jit`.

VAD is cached to JSON (`{stem}_vad_segments.json`) — parameter-matched, auto-reused on re-run. Long audio (>5min) is chunked with 1s overlap. Benchmark with `tests/benchmark_vad.py`.

### Transcription (pipeline/transcriber.py)

`VADTranscriber` orchestrates: VAD segmentation → language detection → segment merging → faster-whisper transcription → optional wav2vec2 alignment.

Uses `faster-whisper` (CTranslate2 backend). Default model is `turbo`, beam_size=2, compute_type=float16. Supports model pooling for parallel transcription (`--num-workers N`). GPU VRAM auto-limiting prevents OOM.

### TTS pipeline (pipeline/tts_*.py)

TTS engines implement `BaseTTSEngine` (Protocol). `tts_edge.py` (Microsoft cloud, default) and `tts_chattts.py` (local, Chinese-optimized).

**Timing strategy** (`speed_strategy.py`):
1. TTS within ±15% of segment → adjust video playback speed
2. Beyond ±15% → regenerate TTS at different rate, up to max_speed → video slowdown as last resort

**Per-segment flow:** crop video → extract instrumental → TTS synthesize → `TimingAdjuster.align()` → `VideoSegmenter.slow_down_video_to_file()` (audio mixed via ffmpeg amix, not MoviePy) → captions → write .mp4 → `VideoMerger.merge()` concat all segments.

All WAV manipulation uses ffmpeg directly to avoid audio artifacts from MoviePy's float32 pipeline.

### Translation (SRT/)

`SRT_Translator.py` uses DeepSeek API with 3-tier fallback: batch (8/group) → single → manual. `TranslationVerifier.py` does semantic similarity checking via sentence-transformers (threshold 0.65). `TermReplacer.py` applies terminology dictionary post-translation. `LANGUAGE_PRESETS.py` provides per-language SRT formatting presets. `Json_Convert_Srt_JP.py` is Japanese-specific (MeCab-based).

### WebUI (GUI/)

FastAPI backend (`server.py`) + React/TypeScript frontend. Serves static files; no separate frontend dev server needed.

**Key API endpoints:**
- `POST /api/pipeline/run` — start single-video processing
- `POST /api/batch/run` — start batch processing (multiple videos sequentially)
- `GET /api/pipeline/{id}/logs` — SSE streaming logs
- `POST /api/subtitle/optimize` — external subtitle optimizer
- `POST /api/subtitle/review/load` / `save` — manual translation calibration
- `GET /api/system/info` — CPU/GPU detection for frontend auto-config

**Frontend hooks:** `useConfig` (pipeline settings), `usePipeline` (SSE log streaming), `useBatch` (batch multi-video), `useSSE` (generic SSE).

**Batch processing:** Each batch has a `BatchSession` persisted to `GUI/batches/`. Videos processed sequentially with start/skip/cancel controls. Job status and logs are also persisted to `GUI/batches/` as JSON files.

### Config system

Three YAML files in `config/`:
- `translate.yaml` — DeepSeek API key, model, rate limits, semantic check (gitignored)
- `tts.yaml` — engine type, voice, speed, codec, ImageMagick path
- `caption.yaml` — font, colors, stroke, alignment, subtitle optimization

`translate.yaml.example` is the template.

### Critical implementation details

- **Python 3.12** — portable Python at `.python/` with CUDA torch 2.6.0+cu124. Always use `.venv/Scripts/python`.
- **GPU support** — RTX 3060 Ti, CUDA available. whisper uses `device="cuda"` via CTranslate2. `_normalize_device()` in transcriber.py auto-falls back to CPU if CUDA unavailable.
- `gpu_detect.py` auto-picks h264_nvenc if available, falls back to libx264.
- **C2 defect fix** — OBS-recorded MP4s have AAC padding (audio < container duration). Fixed with `aresample=async=1:first_pts=0` + `-t <CD>` during audio extraction.
- **Model storage** — all models cached locally in `models/` (gitignored). HF endpoint defaults to `hf-mirror.com`.
- **Resume** — `ResumeManager` checks for existing `TTS_{start}_{end}.mp4` files; no separate state file.
- **Backup** — `main.py --backup-dir <dir>` auto-saves intermediate artifacts after each step.
- **Skip flags** — `--skip-demucs` (skip vocal separation), `--skip-defect-check` (skip C2 diagnosis), `--skip-extract/translate/tts`.
- **Vendored submodules** — `spleeter/`, `OpenVoice/`, `SwinIR/`, `Minecraft_dict/` are vendored copies, not the active pipeline. Only `pipeline/`, `SRT/`, `whisperx_local/`, and `openvoice_cli/` are actively used.

## Project docs

- `ARCHITECTURE.md` — full dataflow diagrams, design decisions, ADRs
- `README.md` — quickstart, CLI reference, config reference, module tree
- `docs/tts-engine-research-2026.md` — TTS engine comparison
- `docs/voice-cloning-research-2026.md` — voice cloning feasibility
