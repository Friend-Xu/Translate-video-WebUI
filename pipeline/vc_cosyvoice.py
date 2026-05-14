"""
CosyVoice 2.0/3.0 Voice Cloner -- high-quality voice conversion for GPU-rich devices.

Implements the VoiceCloner Protocol defined in ``pipeline/vc_base.py``.

Modes
-----
**local**  -- Loads the CosyVoice model directly into the current process.
             Requires Python 3.10 + CosyVoice dependencies.
             Raises RuntimeError on Python >= 3.11 (use Docker mode instead).

**docker** -- Sends audio to a CosyVoice Docker service via HTTP.
             Python-version agnostic; recommended for Python 3.12 hosts.

Voice Conversion
----------------
Uses ``inference_vc()`` (inherited by CosyVoice2/3 from the base class).
This method bypasses the LLM entirely and relies solely on the **Flow model**
(DiT for v3, Conformer for v2) for audio-to-audio timbre transfer.

Architecture::

    TTS Audio (any sr)                Reference Audio (16 kHz)
          |                                    |
          v                                    v
    torchaudio.load               torchaudio.load + resample
          |                                    |
          v                                    v
    ---------------------------------------------------------------
    |  CosyVoice Frontend                                        |
    |  |-- source_wav -> speech_token (source content)           |
    |  |-- prompt_wav -> spk_embedding + speech_feat             |
    ---------------------------------------------------------------
                       |
                       v
    ---------------------------------------------------------------
    |  Flow Model (CausalMaskedDiffWithXvec / DiT)               |
    |  source_token + target_embedding -> mel spectrogram        |
    ---------------------------------------------------------------
                       |
                       v
    ---------------------------------------------------------------
    |  HiFT Vocoder -> waveform (24 kHz)                         |
    ---------------------------------------------------------------
                       |
                       v
                  Output WAV
"""

from __future__ import annotations

from pipeline.logger import get_logger

logger = get_logger(__name__)

import gc
import hashlib
import io
import os
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import torch
import torchaudio

from .vc_base import VoiceCloneConfig
from .vc_device import detect_vram_mb

# ── ensure CosyVoice is importable ────────────────────────────────────
# CosyVoice 源码（models/CosyVoice/cosyvoice/）为只读 git clone，
# 不存在运行时修改自身文件的场景。直接添加源路径到 sys.path，
# 不做任何 temp 复制。
_cosyvoice_root = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "models", "CosyVoice")
)
_matcha_root = os.path.join(_cosyvoice_root, "third_party", "Matcha-TTS")
for _p in (_cosyvoice_root, _matcha_root):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

CosyVoice2 = None
CosyVoice3 = None
try:
    from cosyvoice.cli.cosyvoice import CosyVoice2 as _CV2  # type: ignore[import-untyped]
    CosyVoice2 = _CV2
except ImportError:
    pass
try:
    from cosyvoice.cli.cosyvoice import CosyVoice3 as _CV3  # type: ignore[import-untyped]
    CosyVoice3 = _CV3
except ImportError:
    pass


# ---------------------------------------------------------------------------
# CosyVoiceCloner
# ---------------------------------------------------------------------------

class CosyVoiceCloner:
    """CosyVoice 2.0/3.0 voice cloner -- local or Docker-backed.

    Speaker embeddings are cached to disk (``models/.se_cache/``) so that the
    same reference audio only incurs ONNX inference once across sessions.

    Thread-safe: the internal model is guarded by a lock so that concurrent
    ``clone()`` calls (driven by ``ThreadPoolExecutor``) do not race on the
    GPU.  Docker mode does not need a lock because each request is stateless.
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, config: VoiceCloneConfig) -> None:
        self.config = config

        # --- mode ----------------------------------------------------------
        self._mode: str = config.cosyvoice_mode  # "local" | "docker"

        # --- VRAM / device -------------------------------------------------
        self._vram_mb: int = detect_vram_mb()
        self._device: str = self._resolve_device(config.device)

        if self._vram_mb >= 8192:
            self._gpu_tier = "high"
            self._max_concurrency = min(config.concurrent_workers, 4)
        elif self._vram_mb >= 4096:
            self._gpu_tier = "mid"
            self._max_concurrency = min(config.concurrent_workers, 2)
        else:
            self._gpu_tier = "low"
            self._max_concurrency = 1

        self._concurrency = max(self._max_concurrency, 1)

        # --- internal state ------------------------------------------------
        self._model: Optional[object] = None       # CosyVoice2/3 instance
        self._prompt_audio: Optional[torch.Tensor] = None  # 16 kHz mono
        self._prompt_audio_path: str = ""
        self._lock = threading.Lock()

        # --- speaker-embedding cache ---------------------------------------
        self._se_cache_dir: str = os.path.abspath(config.se_cache_dir)
        os.makedirs(self._se_cache_dir, exist_ok=True)

        # --- local-mode flags (ignored in Docker mode) ---------------------
        self._fp16: bool = config.cosyvoice_fp16
        self._load_jit: bool = config.cosyvoice_load_jit
        self._load_trt: bool = config.cosyvoice_load_trt

    # ------------------------------------------------------------------
    # VoiceCloner Protocol
    # ------------------------------------------------------------------

    def prepare(self, voice_path: str) -> bool:
        """Load and cache the reference voice audio.

        Args:
            voice_path: Path to the reference vocal WAV (e.g. Demucs output).
                Falls back to ``config.color_audio_path`` if that exists.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        color_path = self.config.color_audio_path

        # Prefer the color_audio_path if it already exists
        if os.path.isfile(color_path):
            voice_path = color_path

        if not voice_path or not os.path.isfile(voice_path):
            self._log_error(
                f"prepare: reference audio not found "
                f"(voice={voice_path}, color={color_path})"
            )
            return False

        try:
            if self._mode == "local":
                return self._prepare_local(voice_path)
            else:
                return self._prepare_docker(voice_path)
        except Exception as exc:
            self._log_error(f"prepare failed [{voice_path}]: {exc}")
            return False

    def clone(self, tts_audio_path: str, output_dir: str) -> Optional[str]:
        """Convert TTS audio to the target speaker timbre.

        Thread-safe for local mode (model guarded by lock).
        Docker mode is naturally thread-safe (stateless HTTP).

        Args:
            tts_audio_path: Path to the audio generated by the TTS engine.
            output_dir: Directory in which to write the cloned file.

        Returns:
            Path to the cloned audio file, or ``None`` on failure.
        """
        if not os.path.isfile(tts_audio_path):
            self._log_error(f"clone: TTS audio not found: {tts_audio_path}")
            return None

        try:
            if self._mode == "local":
                return self._clone_local(tts_audio_path, output_dir)
            else:
                return self._clone_docker(tts_audio_path, output_dir)
        except Exception as exc:
            self._log_error(f"clone failed [{tts_audio_path}]: {exc}")
            return None

    def clone_batch(
        self, items: list[tuple[str, str]]
    ) -> list[Optional[str]]:
        """Concurrently clone multiple TTS audio files.

        Uses ``ThreadPoolExecutor`` with ``self._concurrency`` workers.

        Args:
            items: List of ``(tts_audio_path, output_dir)`` tuples.

        Returns:
            List of cloned audio paths (``None`` for failed items), in the
            same order as *items*.
        """
        if self._concurrency <= 1 or len(items) <= 1:
            return [self.clone(path, out_dir) for path, out_dir in items]

        n = len(items)
        results: list[Optional[str]] = [None] * n

        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = {
                pool.submit(self.clone, path, out_dir): idx
                for idx, (path, out_dir) in enumerate(items)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    self._log_error(f"clone_batch worker exception: {exc}")

        return results

    def device_info(self) -> dict:
        """Return device metadata (matches ``VoiceCloner`` protocol)."""
        return {
            "device": self._device,
            "vram_mb": self._vram_mb,
            "mode": self._mode,
            "gpu_tier": self._gpu_tier,
            "concurrency": self._concurrency,
            "engine": "cosyvoice",
        }

    def cleanup(self) -> None:
        """Release GPU memory and reset internal state."""
        if self._model is not None:
            del self._model
            self._model = None

        self._prompt_audio = None
        self._prompt_audio_path = ""

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

    # ------------------------------------------------------------------
    # Local mode -- direct model inference
    # ------------------------------------------------------------------

    def _prepare_local(self, voice_path: str) -> bool:
        """Load reference audio into memory (16 kHz mono tensor, trimmed to <=30s)."""
        self._load_model()

        try:
            wav, sr = torchaudio.load(voice_path)
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
            if sr != 16000:
                wav = torchaudio.functional.resample(wav, sr, 16000)
            # CosyVoice speech token extraction limits audio to 30s
            max_samples = 16000 * 30
            if wav.shape[1] > max_samples:
                wav = wav[:, :max_samples]
            self._prompt_audio = wav
            self._prompt_audio_path = voice_path

            # Cache the speaker embedding to disk for cross-session reuse
            self._cache_speaker_embedding(voice_path, wav)
            return True
        except Exception as exc:
            self._log_error(f"_prepare_local failed: {exc}")
            return False

    def _clone_local(
        self, tts_audio_path: str, output_dir: str
    ) -> Optional[str]:
        """Run inference_vc locally.

        CosyVoice's inference_vc() expects file paths (not tensors) because
        its internal load_wav() calls torchaudio.load().  We save the
        pre-loaded prompt tensor to a temp file and pass the original
        TTS path directly.
        """
        self._load_model()

        if self._prompt_audio is None:
            color_path = self.config.color_audio_path
            if os.path.isfile(color_path):
                if not self._prepare_local(color_path):
                    return None
            else:
                self._log_error(
                    "_clone_local: not prepared and no color_audio_path"
                )
                return None

        import tempfile

        prompt_tmp = None
        try:
            # Save prompt audio to temp file (CosyVoice API needs file paths)
            prompt_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            torchaudio.save(prompt_tmp.name, self._prompt_audio, 16000)

            os.makedirs(output_dir, exist_ok=True)
            filename = f"cosyvc_{os.path.basename(tts_audio_path)}"
            save_path = os.path.join(output_dir, filename)

            with self._lock:
                generator = self._model.inference_vc(
                    tts_audio_path, prompt_tmp.name, stream=False
                )
                for _, result in enumerate(generator):
                    tts_speech = result["tts_speech"]
                    torchaudio.save(
                        save_path,
                        tts_speech.cpu(),
                        self._model.sample_rate,
                    )
                    break

            return save_path
        except Exception as exc:
            self._log_error(
                f"_clone_local inference failed [{tts_audio_path}]: {exc}"
            )
            return None
        finally:
            if prompt_tmp is not None:
                try:
                    os.unlink(prompt_tmp.name)
                except OSError:
                    pass

    def _load_model(self) -> None:
        """Lazy-load the CosyVoice2 or CosyVoice3 model.

        Raises:
            RuntimeError: If Python >= 3.11 (CosyVoice requires 3.10).
            ImportError: If CosyVoice package is not installed.
        """
        if self._model is not None:
            return

        # Python version gate -- CosyVoice requires <= 3.10
        if sys.version_info >= (3, 11):
            msg = (
                f"CosyVoice local mode requires Python <= 3.10, "
                f"but running on Python {sys.version_info.major}."
                f"{sys.version_info.minor}. "
                f"Switch to mode: docker or use a Python 3.10 environment."
            )
            self._log_error(msg)
            raise RuntimeError(msg)
        # Python 3.10 — local mode supported
        logger.info(f"local mode ready (Python {sys.version_info.major}.{sys.version_info.minor})")

        model_path = self.config.model_dir
        model_version = self.config.model_version

        try:
            if model_version == "v3":
                if CosyVoice3 is None:
                    raise ImportError("CosyVoice3 not available (check Python version and installation)")
                CVModel = CosyVoice3
            else:
                if CosyVoice2 is None:
                    raise ImportError("CosyVoice2 not available (check Python version and installation)")
                CVModel = CosyVoice2

            self._model = CVModel(
                model_path,
                load_jit=self._load_jit,
                load_trt=self._load_trt,
                fp16=self._fp16,
            )
        except ImportError as exc:
            msg = (
                f"Cannot import CosyVoice: {exc}. "
                f"Clone https://github.com/FunAudioLLM/CosyVoice.git "
                f"and install dependencies (pip install -r requirements.txt)."
            )
            self._log_error(msg)
            raise
        except Exception as exc:
            self._log_error(f"CosyVoice model load failed: {exc}")
            raise

    def _model_device(self) -> str:
        """Return the device string the loaded model is using."""
        if self._model is None:
            return "cpu"
        try:
            return str(self._model.frontend.device)
        except Exception:
            return self._device

    def _cache_speaker_embedding(
        self, voice_path: str, wav_16k: torch.Tensor
    ) -> None:
        """Extract and persist the speaker embedding to disk."""
        if self._model is None:
            return

        cache_path = self._se_cache_path(voice_path)
        if os.path.isfile(cache_path):
            return

        try:
            embedding = self._model.frontend._extract_spk_embedding(
                voice_path
            )
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            torch.save(embedding.cpu(), cache_path)
        except Exception as exc:
            self._log_error(f"cache speaker embedding failed: {exc}")

    # ------------------------------------------------------------------
    # Docker mode -- HTTP API
    # ------------------------------------------------------------------

    def _prepare_docker(self, voice_path: str) -> bool:
        """Cache the reference audio in memory for Docker mode.

        In Docker mode, the reference audio is uploaded with each clone
        request.  We pre-load and resample it once here.
        """
        if not os.path.isfile(voice_path):
            self._log_error(f"_prepare_docker: file not found: {voice_path}")
            return False

        try:
            wav, sr = torchaudio.load(voice_path)
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
            if sr != 16000:
                wav = torchaudio.functional.resample(wav, sr, 16000)
            self._prompt_audio = wav
            self._prompt_audio_path = voice_path
            return True
        except Exception as exc:
            self._log_error(f"_prepare_docker load audio failed: {exc}")
            return False

    def _clone_docker(
        self, tts_audio_path: str, output_dir: str
    ) -> Optional[str]:
        """Send audio to Docker service for voice conversion.

        Expected Docker API::

            POST {docker_url}/api/vc
            Content-Type: multipart/form-data
            Fields:
                source_audio  -- (file) TTS audio to convert
                prompt_audio  -- (file) reference voice audio
            Response: audio/wav binary

        Falls back to FunSpeech-compatible ``/api/v1/tts`` if ``/api/vc``
        returns 404.
        """
        import requests

        docker_url = self.config.cosyvoice_docker_url.rstrip("/")
        timeout = self.config.cosyvoice_docker_timeout

        # Prepare prompt audio bytes
        prompt_bytes = self._prompt_audio_bytes()
        if prompt_bytes is None:
            self._log_error("_clone_docker: no reference audio available")
            return None

        try:
            with open(tts_audio_path, "rb") as f:
                source_bytes = f.read()

            files = {
                "source_audio": (
                    os.path.basename(tts_audio_path),
                    source_bytes,
                    "audio/wav",
                ),
                "prompt_audio": ("prompt.wav", prompt_bytes, "audio/wav"),
            }

            resp = requests.post(
                f"{docker_url}/api/vc",
                files=files,
                timeout=timeout,
            )

            if resp.status_code == 404:
                resp = self._clone_docker_fallback(
                    docker_url, source_bytes, prompt_bytes, timeout
                )

            if resp.status_code != 200:
                self._log_error(
                    f"Docker VC request failed "
                    f"HTTP {resp.status_code}: {resp.text[:500]}"
                )
                return None

            os.makedirs(output_dir, exist_ok=True)
            filename = f"cosyvc_{os.path.basename(tts_audio_path)}"
            save_path = os.path.join(output_dir, filename)

            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type:
                # Some services return JSON with base64 audio
                try:
                    data = resp.json()
                    audio_b64 = data.get("audio") or data.get("data")
                    if audio_b64:
                        import base64
                        with open(save_path, "wb") as f:
                            f.write(base64.b64decode(audio_b64))
                        return save_path
                except Exception:
                    pass
                self._log_error(
                    f"Docker VC returned JSON but no audio field found"
                )
                return None
            else:
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                return save_path

        except requests.exceptions.Timeout:
            self._log_error(
                f"Docker VC request timed out ({timeout}s): {docker_url}"
            )
            return None
        except requests.exceptions.ConnectionError:
            self._log_error(f"Docker service unreachable: {docker_url}")
            return None
        except Exception as exc:
            self._log_error(f"_clone_docker failed [{tts_audio_path}]: {exc}")
            return None

    def _clone_docker_fallback(
        self,
        docker_url: str,
        source_bytes: bytes,
        prompt_bytes: bytes,
        timeout: int,
    ):
        """Fallback: FunSpeech-compatible /api/v1/tts endpoint."""
        import requests

        files = {
            "reference_audio": ("prompt.wav", prompt_bytes, "audio/wav"),
            "audio": ("source.wav", source_bytes, "audio/wav"),
        }
        data = {"mode": "voice_conversion"}
        return requests.post(
            f"{docker_url}/api/v1/tts",
            files=files,
            data=data,
            timeout=timeout,
        )

    def _prompt_audio_bytes(self) -> Optional[bytes]:
        """Encode the cached prompt audio as WAV bytes."""
        if self._prompt_audio is not None:
            return _tensor_to_wav_bytes(self._prompt_audio, 16000)
        if os.path.isfile(self.config.color_audio_path):
            with open(self.config.color_audio_path, "rb") as f:
                return f.read()
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_device(raw: str) -> str:
        """Normalise the device string from config."""
        if raw == "auto":
            return "cuda:0" if torch.cuda.is_available() else "cpu"
        return raw

    def _se_cache_path(self, voice_path: str) -> str:
        """SHA-256 based path for a persisted speaker-embedding tensor."""
        h = hashlib.sha256(voice_path.encode()).hexdigest()[:16]
        return os.path.join(self._se_cache_dir, f"cv_{h}.pt")

    def _log_error(self, message: str) -> None:
        """Append a timestamped message to the error log."""
        log_path = self.config.error_log_path
        if not log_path:
            return
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass  # Best-effort logging


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_cosyvoice_path() -> None:
    """No-op: paths are set at module import time (see top of file)."""
    pass


def _tensor_to_wav_bytes(wav: torch.Tensor, sample_rate: int) -> bytes:
    """Encode a (1, T) tensor as WAV bytes in memory."""
    buf = io.BytesIO()
    torchaudio.save(buf, wav.cpu(), sample_rate, format="wav")
    buf.seek(0)
    return buf.read()
