"""
IndexTTS engine — subprocess-isolated TTS via indextts_worker.py.

Follows the same pattern as ChatTTSEngine: a persistent subprocess running
in its own Python venv (models/IndexTTS/.venv/) communicates via
stdin/stdout JSON protocol. This isolates PyTorch 2.8 + CUDA 12.8 from
the main project's PyTorch 2.6 + CUDA 12.4, and avoids VRAM contention
(IndexTTS needs ~7.8 GB in FP16 — unloadable alongside ChatTTS/CosyVoice).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Optional

logger = logging.getLogger("pipeline.tts_indextts")

_SYNTHESIS_TIMEOUT = 180


class IndexTTSEngine:
    def __init__(
        self,
        checkpoints_dir: Optional[str] = None,
        fp16: bool = True,
        speaker_audio: Optional[str] = None,
    ):
        self._checkpoints_dir = checkpoints_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "IndexTTS", "index-tts-batch", "checkpoints",
        )
        self._fp16 = fp16
        self._speaker_audio = speaker_audio

        self._proc: Optional[subprocess.Popen] = None
        self._stderr_fh = None
        self._lock = threading.Lock()
        self._loaded = False

    # ── properties ──────────────────────────────────────────

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    @property
    def healthy(self) -> bool:
        return (
            self._proc is not None
            and self._proc.poll() is None
            and self._loaded
        )

    # ── public API ──────────────────────────────────────────

    def supports_rate(self) -> bool:
        return False  # Use target_length_ms (duration control) instead

    def supports_emotion(self) -> bool:
        return True

    def warmup(self):
        """Start the subprocess worker and load the model."""
        if self._loaded:
            return

        worker_python = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "IndexTTS", ".venv", "Scripts", "python.exe",
        )
        worker_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "IndexTTS", "indextts_worker.py",
        )

        self._stderr_log = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "IndexTTS", "worker_stderr.log",
        )
        self._stderr_fh = open(self._stderr_log, "w", encoding="utf-8")

        # Force HF cache to the correct location (relative paths in worker may break)
        hf_cache = os.path.join(self._checkpoints_dir, "hf_cache")
        worker_env = {
            **os.environ,
            "HF_HOME": hf_cache,
            "HF_HUB_CACHE": hf_cache,
            "TRANSFORMERS_CACHE": hf_cache,
        }

        self._proc = subprocess.Popen(
            [worker_python, worker_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_fh,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=worker_env,
        )

        resp = self._send({"action": "warmup", "checkpoints_dir": self._checkpoints_dir, "fp16": self._fp16})
        if resp.get("status") != "ok":
            raise RuntimeError(f"IndexTTS warmup failed: {resp.get('message', 'unknown')}")

        self._loaded = True
        logger.info("IndexTTS worker started (fp16=%s, checkpoints=%s)", self._fp16, self._checkpoints_dir)

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional[object] = None,
        target_length_ms: Optional[float] = None,
    ) -> float:
        """Synthesize speech to a WAV file. Returns audio duration in seconds."""
        if not self._loaded:
            raise RuntimeError("IndexTTS model not loaded")

        resp = self._send({
            "action": "synthesize",
            "text": text,
            "output_path": output_path,
            "spk_audio_prompt": self._speaker_audio or "",
            "target_length_ms": target_length_ms,
            "emotion": emotion,
        })

        if resp.get("status") != "ok":
            raise RuntimeError(f"IndexTTS synthesis failed: {resp.get('message', 'unknown')}")

        return float(resp.get("duration_s", 0))

    def reset_speaker(self, prompt_audio: str):
        """Change the zero-shot speaker reference audio."""
        self._speaker_audio = prompt_audio
        logger.info("IndexTTS speaker audio: %s", os.path.basename(prompt_audio))

    def cleanup(self):
        """Shut down the worker subprocess and free GPU memory."""
        if self._proc is not None:
            try:
                self._send({"action": "shutdown"})
                self._proc.stdin.close()
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
            finally:
                self._proc = None
        self._loaded = False
        try:
            self._stderr_fh.close()
        except Exception:
            pass

    # ── internal ────────────────────────────────────────────

    def _send(self, req: dict) -> dict:
        """Send a JSON request to the worker and read the response."""
        with self._lock:
            try:
                self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
                # Skip IndexTTS model-loading progress lines (not JSON)
                for _ in range(200):  # safety limit
                    line = self._proc.stdout.readline()
                    if not line:
                        return {"status": "error", "message": "worker stdout closed"}
                    line = line.strip()
                    if line.startswith("{"):
                        return json.loads(line)
                return {"status": "error", "message": "too many non-JSON lines from worker"}
            except (BrokenPipeError, OSError) as e:
                logger.error("IndexTTS worker communication error: %s", e)
                self._loaded = False
                return {"status": "error", "message": str(e)}
