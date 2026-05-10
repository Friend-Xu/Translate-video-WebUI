# Translate_video — WebUI Guide

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript)](https://www.typescriptlang.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite)](https://vite.dev)
[![MUI](https://img.shields.io/badge/MUI-7-007FFF?logo=mui)](https://mui.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A browser-based visual interface to run the Translate_video pipeline — **drag, configure, and click**. No command line needed.

---

## Quick Start

```bash
# One-click launch
GUI\start_WebUI.bat

# Or manually — backend (port 8000)
.venv\Scripts\python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# Frontend dev (port 5173)
cd GUI && npm install && npm run dev
```

Open `http://localhost:5173`.

> **Requirements:** Python 3.10+ | Node.js 18+ | backend dependencies in `.venv/`

---

## Interface

| Panel | What it does |
|------|------|
| **Main** | Drag-drop video → click Start. SSE live logs, job queue with status badges |
| **Step Config** | 3-step visual settings: Extract (VAD/whisper/wav2vec2) → Translate (LLM/glossary/prompt) → TTS (engine/voice/speed) |
| **Output Settings** | Caption style — font, color, stroke, position, size. Video encoder & bitrate |
| **Subtitle Review** | Visual editor: proofread translations, mark bad entries, re-run TTS after fixes |
| **Batch Mode** | Queue multiple videos, pause/resume/skip, progress per file |
| **Tools** | Config import/export/reset, external subtitle optimizer, file browser |

---

## Features

### Drag & Drop
Just drop a video file on the main panel. The pipeline auto-detects filepath, language, and workspace.

### Live Progress
SSE streaming logs with per-step timing. See exactly what's happening at each pipeline stage in real time.

### GPU Auto-Detection
Detects NVIDIA GPU + VRAM capacity on startup. Automatically selects hardware encoder (NVENC) and calculates optimal ChatTTS worker count.

### Dual TTS Engine
Switch between Edge TTS (cloud, fast) and ChatTTS (local, offline). Voice auto-selected based on target language — 15 languages supported.

### Config Persistence
All settings saved to YAML. Export/import configs to share between machines. Reset to defaults anytime.

### Subtitle Calibration
Review every translated subtitle line. Edit text, mark entries for re-translation. Changes write back to `reviewed.srt` and re-trigger TTS.

### ChatTTS Voice Gacha
Preview ChatTTS voices instantly. Random seed → hear the result → lock in your favorite speaker. No GPU reload needed between previews.

---

## Tech Stack

| Layer | Technology |
|------|------|
| Frontend | React 19, TypeScript 5.7, MUI 7, Vite 6 |
| Backend | FastAPI 0.136, Python 3.10 |
| Communication | SSE (Server-Sent Events) for real-time logs |
| Pipeline | `main.py` launched as subprocess, stdout streamed to frontend |
| Config | YAML — `config/translate.yaml`, `config/tts.yaml`, `config/caption.yaml` |

---

## Directory Structure

```
GUI/
├── start_WebUI.bat          # One-click launcher
├── server.py                # FastAPI backend
├── App.tsx                  # React root with sidebar tabs
├── types.ts                 # Shared TypeScript types
├── components/
│   ├── sections/
│   │   ├── MainPanel.tsx        # Drag-drop, start button, logs
│   │   ├── StepConfig.tsx       # 3-step pipeline configuration
│   │   ├── OutputSettings.tsx   # Caption style & video encoder
│   │   ├── BatchPanel.tsx       # Multi-video batch mode
│   │   ├── SubtitleReview.tsx   # Visual subtitle editor
│   │   └── ToolsPanel.tsx       # Config management & utilities
│   ├── CustomPromptDialog.tsx   # Custom translation prompt editor
│   ├── ApiConfigDialog.tsx      # API key & model settings
│   └── ChatTTSPanel.tsx         # ChatTTS voice preview (gacha)
├── hooks/
│   ├── usePipeline.ts       # Pipeline start/status/cancel
│   ├── useBatch.ts          # Batch processing logic
│   ├── useSSE.ts            # Server-Sent Events parser
│   └── useConfig.ts         # Settings persistence
├── spec/                    # Feature specification docs
└── logs/                    # Server logs
```

---

## FAQ

**Q: Frontend fails with "npm: command not found"?**
Install Node.js from https://nodejs.org/ (18+ recommended).

**Q: Port 8000 / 5173 already in use?**
```bash
# Change backend port
.venv\Scripts\python -m uvicorn GUI.server:app --port 8001
# Change frontend port
cd GUI && npm run dev -- --port 5174
```
Update the Vite proxy target in `GUI/vite.config.ts` to match.

**Q: How to view backend logs?**
`GUI/logs/server.log` — rotating file logs (5MB per file, 3 backups).

**Q: Frontend changes don't appear?**
In dev mode (`npm run dev`), HMR auto-reloads. For production, rebuild:
```bash
cd GUI && npm run build
```

**Q: CORS errors in browser?**
Make sure the Vite dev server is running (it proxies `/api` to port 8000). Don't access port 8000 directly in dev mode.

---

## License

MIT — same as the main project.
