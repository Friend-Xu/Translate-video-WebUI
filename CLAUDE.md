# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all TTS tests
.venv/Scripts/python -m pytest tests/test_tts/ -v

# Run a single test
.venv/Scripts/python -m pytest tests/test_tts/test_tts_edge.py::test_synthesize_basic -v

# Run checkpoint tests
.venv/Scripts/python -m pytest tests/test_checkpoint.py -v

# Run all tests
.venv/Scripts/python -m pytest tests/ -v

# Run VAD benchmark (compare JIT vs ONNX)
.venv/Scripts/python tests/benchmark_vad.py source_file/video.mp4 --quick

# Run the full 3-step pipeline
.venv/Scripts/python main.py source_file/video.mp4 --lang ja

# Run with CosyVoice TTS (offline, zero-shot)
.venv/Scripts/python main.py source_file/video.mp4 --lang zh --engine cosyvoice

# Extract subtitles only (GPU + turbo defaults)
.venv/Scripts/python extract_subtitles.py source_file/video.mp4 --lang ja

# CPU fallback (if CUDA unavailable)
.venv/Scripts/python extract_subtitles.py source_file/video.mp4 --device cpu --compute-type int8

# Skip Demucs vocal separation (faster for clean audio)
.venv/Scripts/python main.py source_file/video.mp4 --lang en --skip-demucs

# Translate an existing SRT file
.venv/Scripts/python -m SRT.SRT_Translator path/to/file.srt

# ---- WebUI ----
# Backend (port 8000)
.venv/Scripts/python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# Frontend dev server (port 5173, proxies /api to 127.0.0.1:8000)
cd GUI && npm run dev

# Production build + serve (single port 8000)
cd GUI && npm run build && cd .. && .venv/Scripts/python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# TypeScript check
cd GUI && npx tsc -p tsconfig.json --noEmit
```

## Architecture

Video translation pipeline: **extract subtitles → translate → TTS synthesize → merge** into dubbed video with bilingual captions.

```
main.py → subprocess: extract_subtitles.py → subprocess: Demucs (NODE 2.5)
```

extract_subtitles.py dataflow (modules communicate via filesystem, defaults: `--model turbo --device cuda --compute-type float16`):

```
NODE 1   video_info.py       → ffmpeg -i metadata
NODE 1.5 MediaValidator      → C2 defect diagnosis
NODE 2   audio.py            → audio extraction + aresample fix
NODE 2.5 demucs_instr.py     → Demucs vocal/instrumental separation
NODE 3   transcriber.py      → Silero VAD (ONNX) + faster-whisper (CTranslate2)
NODE 3.5 whisperx_local/     → wav2vec2 CTC forced alignment
NODE 4   Json_Convert_Srt    → JSON → SRT
```

| Directory | Purpose |
|-----------|---------|
| `pipeline/` | VAD, transcription, TTS engines (edge/chattts/cosyvoice), RubberBand stretch, speed strategy, loudness, voice cloning (vc_*), caption rendering, video merging, checkpoint resume, model management, quality assessment |
| `SRT/` | Translation (DeepSeek/OpenAI API, 3-tier fallback, multi-agent Conductor pattern), semantic verification, on-demand glossary injection, term replacement, MQM scoring, language presets |
| `whisperx_local/` | wav2vec2 forced alignment (~20ms precision) |
| `GUI/` | FastAPI + React/TypeScript WebUI, Vite dev proxy to uvicorn |
| `config/` | YAML configs: `translate.yaml` (gitignored), `tts.yaml`, `caption.yaml`, `cosyvoice.yaml`, `external_subtitle.yaml`, `runtime_tts.yaml` |

Full architecture details → `ARCHITECTURE.md`. Entry points: `main.py` (recommended) or `translate_video.py` (legacy).

### CosyVoice TTS Subprocess Isolation

CosyVoice runs in an **isolated Python 3.10 subprocess** to avoid PyTorch version conflicts with the main environment (ChatTTS uses PyTorch 2.x, CosyVoice needs a specific build):

```
pipeline/tts_cosyvoice.py (CosyVoiceTTSEngine)
    │ subprocess.Popen (encoding="utf-8")
    ▼
models/CosyVoice/cosyvoice_worker.py
    │ runs in models/CosyVoice/.python310/python.exe
    │ uses models/CosyVoice/.cosyvenv/ site-packages
    ▼
stdin/stdout JSON protocol: {"action": "synthesize", ...} → {"status": "ok", ...}
```

- **Model versions**: v2 (CosyVoice2-0.5B, recommended) and v3 (CosyVoice3-0.5B, experimental)
- **Only mode**: `cross_lingual` — pre-normalizes numbers/dates via WeTextProcessing, then injects language tag, calls inference with `text_frontend=False`
- **Language tags**: `<|zh|>`, `<|en|>`, `<|ja|>`, `<|ko|>`, `<|yue|>` — placed before the text (before `<|endofprompt|>` for v3). Arbitrary lang codes (zh-CN, en-US) are normalized to these 5 tags.
- **Worker stderr** captured to temp file for crash diagnosis

### Checkpoint System (`pipeline/checkpoint.py`)

PipelineCheckpoint tracks progress per step with SHA256 content-hash change detection:

- `is_step_done("extract")` — checks step status + file existence
- `verify_files()` — discovers missing outputs and marks steps for re-run
- `check_video_changed()` — compares video hash, auto-resets if changed
- `recover_from_crash()` — detects stale `running` states from previous crash
- Error types: INFRASTRUCTURE, USER, APPLICATION (follows Airflow AIP-96)
- Always active — no opt-in. Backward compatible: absent checkpoint falls back to file-existence checks.

### Model Manager (`pipeline/model_manager.py`)

Centralized model download and versioning. All models stored under `models/` (gitignored, HF endpoint: `hf-mirror.com`). `ModelManager.ensure_hf_env()` forces all HF cache paths to local `models/` directory, preventing split storage between `~/.cache/huggingface` and project.

## Workspace Directory Structure

Pipeline creates a structured workspace per input video:

```
{video_dir}/{stem}_project/
├── project.json          ← manifest tracking stage progress + output files
├── 01_extract/           ← source.srt, transcript.json, audio.wav, vocals.wav
├── 02_translate/         ← machine.srt, translate-log.json, quality_report.json
├── 03_tts/               ← TTS audio segments + video clips
└── 04_output/            ← dubbed.mp4 (final)
```

`main.py:workspace_paths()` resolves these paths. The WebUI shares the same path derivation (`server.py` open-folder endpoint, `App.tsx` handleStartReview).

## WebUI Architecture

```
Browser (localhost:5173) → Vite dev server → proxy /api/* → uvicorn (localhost:8000)
                                                                  │
                                                          GUI/server.py (FastAPI)
                                                                  │
                                                          main.py (subprocess)
```

- **Frontend**: React 19 + MUI 7 + TypeScript, `GUI/App.tsx` is the root with sidebar tabs
- **Backend**: FastAPI at `GUI/server.py`, manages jobs in-memory (`_jobs` dict), SSE log streaming
- **Vite proxy**: `/api` requests forwarded to `http://127.0.0.1:8000`, avoids CORS issues
- **Production**: `npm run build` → `dist/`, served by FastAPI's `StaticFiles` mount

### Key API Endpoints (server.py)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/pipeline/run` | Start pipeline job |
| `GET /api/pipeline/{id}/logs` | SSE log stream |
| `GET /api/files/browse` | Directory listing for file picker |
| `GET /api/files/drives` | List Windows drives + quick-access paths |
| `GET /api/files/find` | Search file by name+size (drag-drop path resolution) |
| `POST /api/files/upload` | Upload dropped file to `source_file/` |
| `POST /api/files/open-folder` | Open workspace or video dir in OS explorer |
| `GET /api/video/info` | ffmpeg -i metadata (duration, resolution) |

## Gotchas

- **Python 3.10** — portable Python at `.python/`, always use `.venv/Scripts/python`
- **GPU** — RTX 3060 Ti, CUDA via CTranslate2. `_normalize_device()` auto-falls back to CPU. `gpu_detect.py` auto-picks h264_nvenc.
- **C2 defect fix** — OBS-recorded MP4s have AAC padding (audio < container). Fixed with `aresample=async=1:first_pts=0` + `-t <CD>` in audio extraction.
- **CosyVoice isolation** — worker runs via `subprocess.Popen` with `encoding="utf-8"` (critical on Chinese Windows where default is CP936). Stderr piped to temp file for crash diagnosis. Worker auto-restarts if it dies mid-pipeline.
- **CosyVoice lang tags** — must normalize arbitrary lang codes (zh-CN, en-US) to the 5 valid tags (zh/en/ja/ko/yue) via `_normalize_lang()`. Invalid tags produce letter-pronunciation artifacts.
- **CosyVoice pre-normalization** — text must be normalized with `text_frontend=True` FIRST (handles numbers, dates), then tags injected, then inference with `text_frontend=False`. Skipping normalization causes garbled number pronunciation (e.g., "1.19" → "一展一九").
- **CosyVoice v3 `<|endofprompt|>`** — v3 requires this token separator between conditioning prefix and speech text. v2 does not. Placed as: `"You are a helpful assistant.<|zh|><|endofprompt|>{text}"`.
- **CosyVoice modes** — only `cross_lingual` is supported (validated in `TTSConfig.__post_init__`). `zero_shot` was inferior quality and removed. `text_frontend=False` is mandatory during inference to prevent tag parsing as text.
- **Model storage** — all models cached in `models/` (gitignored), managed by `pipeline/model_manager.py`. HF endpoint: `hf-mirror.com`.
- **Resume** — `ResumeManager` checks for existing `TTS_{start}_{end}.mp4`; no separate state file.
- **Checkpoint** — `PipelineCheckpoint` at workspace root (`project.json` variant). SHA256-based change detection. `verify_files()` auto-detects manually deleted outputs.
- **Vendored but inactive** — `spleeter/`, `OpenVoice/`, `SwinIR/`, `Minecraft_dict/` are vendored copies. Only `pipeline/`, `SRT/`, `whisperx_local/`, `openvoice_cli/` are active.
- **Skip flags** — `--skip-demucs`, `--skip-defect-check`, `--skip-extract/translate/tts`, `--skip-align`, `--skip-semantic-validation`, `--skip-naturalness-check`. Backup: `--backup-dir <dir>`.
- **python-multipart** — required by FastAPI `UploadFile`; installed in venv but not declared in requirements.
- **Vite HMR** — frontend changes auto-reload at `localhost:5173`, but backend changes may need uvicorn restart (new endpoints are sometimes missed by `--reload`).
- **dist/ staleness** — if accessing via port 8000 directly, rebuild with `npm run build` after frontend changes.
- **Rubber Band** — `audio_stretch.py` needs `pyrubberband` pip package + `tools/rubberband/rubberband-3.3.0-gpl-executable-windows/` CLI binary. Used for ChatTTS time-stretching (engine doesn't support native rate control).
- **Voice cloning** — refactored from `tts_openvoice.py` into `vc_base.py` (protocol), `vc_openvoice.py`, `vc_cosyvoice.py`, `vc_device.py` (GPU routing). OpenVoice still noop by default. CosyVoice has built-in zero-shot cloning via prompt audio.
- **Audio fade** — `tts_video.py` applies 10ms ffmpeg afade to all segment WAVs before writing, prevents clicks at concat boundaries.
- **Config field duplication** — `TTSConfig` has both `cosyvoice_*` (legacy voice-clone fields) and `cosyvoice_tts_*` (current TTS engine fields). The TTS pipeline uses `cosyvoice_tts_*`; the old fields are for the separate voice-cloning path.

## Project docs

- `ARCHITECTURE.md` — full dataflow diagrams, design decisions, ADRs
- `README.md` — quickstart, CLI reference, config reference, module tree
- `README_CN.md` — same in Chinese
- `docs/tts-engine-research-2026.md` — TTS engine comparison
- `docs/voice-cloning-research-2026.md` — voice cloning feasibility
