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
| `pipeline/` | VAD, transcription, TTS engines (edge/chattts), video merging |
| `SRT/` | Translation (DeepSeek API, 3-tier fallback), semantic verification, term replacement |
| `whisperx_local/` | wav2vec2 forced alignment (~20ms precision) |
| `GUI/` | FastAPI + React/TypeScript WebUI, serves static files, no separate dev server |
| `config/` | YAML configs: `translate.yaml` (gitignored), `tts.yaml`, `caption.yaml` |

Full architecture details → `ARCHITECTURE.md`. Entry points: `main.py` (recommended) or `translate_video.py` (legacy).

## Gotchas

- **Python 3.10** — portable Python at `.python/`, always use `.venv/Scripts/python`（CosyVoice 本地模式需要 3.10）
- **GPU** — RTX 3060 Ti, CUDA via CTranslate2. `_normalize_device()` auto-falls back to CPU. `gpu_detect.py` auto-picks h264_nvenc.
- **C2 defect fix** — OBS-recorded MP4s have AAC padding (audio < container). Fixed with `aresample=async=1:first_pts=0` + `-t <CD>` in audio extraction.
- **Model storage** — all models cached in `models/` (gitignored), HF endpoint: `hf-mirror.com`.
- **Resume** — `ResumeManager` checks for existing `TTS_{start}_{end}.mp4`; no separate state file.
- **Vendored but inactive** — `spleeter/`, `OpenVoice/`, `SwinIR/`, `Minecraft_dict/` are vendored copies. Only `pipeline/`, `SRT/`, `whisperx_local/`, `openvoice_cli/` are active.
- **Skip flags** — `--skip-demucs`, `--skip-defect-check`, `--skip-extract/translate/tts`, `--skip-align`. Backup: `--backup-dir <dir>`.

## Project docs

- `ARCHITECTURE.md` — full dataflow diagrams, design decisions, ADRs
- `README.md` — quickstart, CLI reference, config reference, module tree
- `docs/tts-engine-research-2026.md` — TTS engine comparison
- `docs/voice-cloning-research-2026.md` — voice cloning feasibility

## graphify

This project has a graphify knowledge graph at `GUI/graphify-out/`.

- Before answering architecture questions, check `GRAPH_REPORT.md` for god nodes and community structure
- For cross-module queries, prefer `/graphify query/path/explain` over grep
- After modifying code, run `/graphify --update` to keep the graph current (AST-only, no API cost)
