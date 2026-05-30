# Repository Guidelines

## Project Structure & Module Organization

```
Translate_video/
├── main.py                  # CLI entry point (full pipeline)
├── extract_subtitles.py     # Subtitle extraction (whisper → SRT)
├── core/                    # v2 Adapter-Pass-Gate architecture
│   ├── adapters/            # 11 adapters (whisper, VAD, ChatTTS, CosyVoice, …)
│   ├── passes/              # 14 processing passes (extract, translate, TTS, …)
│   ├── gates/               # Quality gates (TextGate, EmotionGate)
│   ├── ir/                  # Timeline IR v2 immutable data model
│   ├── engine/              # Pipeline orchestration engine
│   ├── runtime/             # Runtime execution context
│   └── scoring/             # Scorers (TranslationScorer, …)
├── pipeline/                # Legacy pipeline modules (VAD, TTS, checkpoint, …)
├── SRT/                     # Translation engine, MQM scoring, glossary injection
├── whisperx_local/          # wav2vec2 forced alignment (~20ms precision)
├── GUI/                     # React 19 + FastAPI WebUI (Vite dev server, SSE logs)
├── config/                  # YAML configs (tts.yaml, caption.yaml, …)
├── tests/                   # Pytest suites (unit/, integration/, test_tts/, contract/)
├── models/                  # Downloaded AI models (gitignored, HF mirror)
└── source_file/             # Input videos (gitignored)
```

## Build, Test, and Development Commands

```bash
# Run all tests
.venv/Scripts/python -m pytest tests/ -v

# Run a single test file or specific test
.venv/Scripts/python -m pytest tests/test_tts/test_tts_edge.py::test_synthesize_basic -v

# Run the full 3-step pipeline
.venv/Scripts/python main.py source_file/video.mp4 --lang zh

# Extract subtitles only (GPU + turbo model)
.venv/Scripts/python extract_subtitles.py source_file/video.mp4 --lang ja

# WebUI backend (port 8000)
.venv/Scripts/python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# WebUI frontend dev server (port 5173, proxies /api to :8000)
cd GUI && npm run dev

# Production build + serve
cd GUI && npm run build && cd .. && .venv/Scripts/python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# TypeScript type check
cd GUI && npx tsc -p tsconfig.json --noEmit
```

## Coding Style & Naming Conventions

- **Python**: 4-space indentation, snake_case for variables/functions, PascalCase for classes.
- **TypeScript/React**: 2-space indentation, PascalCase components, explicit return types on exported functions.
- **Imports**: stdlib -> third-party -> local (core.*, pipeline.*, SRT.*).
- **Config**: YAML in config/, loaded via pipeline/core config schemas. Secrets go in gitignored config/translate.yaml and config/runtime_tts.yaml.
- **Linting**: No automated linting CI; rely on npx tsc --noEmit for TypeScript checking.

## Testing Guidelines

- **Framework**: Pytest, configured in pyproject.toml (testpaths = ["tests"]).
- **Markers**: @pytest.mark.unit (pure logic, no I/O), @pytest.mark.integration (real files), @pytest.mark.slow (GPU/API), @pytest.mark.schema (JSON Schema contracts).
- **Naming**: test_<module>.py::test_<behavior_description>. Tests live in tests/unit/, tests/integration/, tests/test_tts/, and tests/contract/.
- **Coverage**: No enforced minimum, but prefer covering new adapters and passes with unit tests.

## Commit & Pull Request Guidelines

- **Commits**: Follow the existing history pattern -- short, imperative summaries, often Chinese/English mixed. Prefer single-purpose commits.
- **Worktrees**: All new features must be developed in isolated git worktree branches under .worktrees/, never directly on main. See docs/worktree-workflow.md.
- **PRs**: Link related issues. Include screenshots for WebUI changes. Verify npm run build succeeds before merging frontend changes.

## Environment & Dependencies

- **Python**: 3.10+ only; always use .venv/Scripts/python (Windows portable Python).
- **GPU**: CUDA via CTranslate2 (faster-whisper). RTX 3060 Ti recommended. Falls back to CPU if CUDA unavailable.
- **TTS Subprocess Isolation**: ChatTTS and CosyVoice run in isolated subprocesses (stdin/stdout JSON protocol) to prevent PyTorch version conflicts and GPU memory leaks.
- **Models**: Downloaded to models/ on first run via HF mirror (hf-mirror.com). Managed by pipeline/model_manager.py.
