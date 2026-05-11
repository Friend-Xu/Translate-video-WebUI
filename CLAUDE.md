# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all TTS tests
.venv/Scripts/python -m pytest tests/test_tts/ -v

# Run a single test
.venv/Scripts/python -m pytest tests/test_tts/test_tts_edge.py::test_synthesize_basic -v

# Run VAD benchmark (compare JIT vs ONNX)
.venv/Scripts/python tests/benchmark_vad.py source_file/video.mp4 --quick

# Run the full 3-step pipeline (VAD + whisper + TTS)
.venv/Scripts/python main.py source_file/video.mp4 --lang ja

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
| `pipeline/` | VAD, transcription, TTS engines (edge/chattts), RubberBand stretch, speed strategy, loudness, voice cloning (vc_*), caption rendering, video merging |
| `SRT/` | Translation (DeepSeek/OpenAI API, 3-tier fallback), semantic verification, glossary injection, term replacement |
| `whisperx_local/` | wav2vec2 forced alignment (~20ms precision) |
| `GUI/` | FastAPI + React/TypeScript WebUI, Vite dev proxy to uvicorn |
| `config/` | YAML configs: `translate.yaml` (gitignored), `tts.yaml`, `caption.yaml` |

Full architecture details → `ARCHITECTURE.md`. Entry points: `main.py` (recommended) or `translate_video.py` (legacy).

## Workspace Directory Structure

Pipeline creates a structured workspace per input video:

```
{video_dir}/{stem}_project/
├── project.json          ← manifest tracking stage progress + output files
├── 01_extract/           ← source.srt, transcript.json, audio.wav, vocals.wav
├── 02_translate/         ← machine.srt, translate-log.json
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
- **Model storage** — all models cached in `models/` (gitignored), HF endpoint: `hf-mirror.com`.
- **Resume** — `ResumeManager` checks for existing `TTS_{start}_{end}.mp4`; no separate state file.
- **Vendored but inactive** — `spleeter/`, `OpenVoice/`, `SwinIR/`, `Minecraft_dict/` are vendored copies. Only `pipeline/`, `SRT/`, `whisperx_local/`, `openvoice_cli/` are active.
- **Skip flags** — `--skip-demucs`, `--skip-defect-check`, `--skip-extract/translate/tts`, `--skip-align`. Backup: `--backup-dir <dir>`.
- **python-multipart** — required by FastAPI `UploadFile`; installed in venv but not declared in requirements.
- **Vite HMR** — frontend changes auto-reload at `localhost:5173`, but backend changes may need uvicorn restart (new endpoints are sometimes missed by `--reload`).
- **dist/ staleness** — if accessing via port 8000 directly, rebuild with `npm run build` after frontend changes.
- **Rubber Band** — `audio_stretch.py` needs `pyrubberband` pip package + `tools/rubberband/rubberband-3.3.0-gpl-executable-windows/` CLI binary. Used for ChatTTS time-stretching (engine doesn't support native rate control).
- **Voice cloning** — refactored from `tts_openvoice.py` into `vc_base.py` (protocol), `vc_openvoice.py`, `vc_cosyvoice.py`, `vc_device.py` (GPU routing). OpenVoice still noop by default.
- **Audio fade** — `tts_video.py` applies 10ms ffmpeg afade to all segment WAVs before writing, prevents clicks at concat boundaries.

## Project docs

- `ARCHITECTURE.md` — full dataflow diagrams, design decisions, ADRs
- `README.md` — quickstart, CLI reference, config reference, module tree
- `docs/tts-engine-research-2026.md` — TTS engine comparison
- `docs/voice-cloning-research-2026.md` — voice cloning feasibility
