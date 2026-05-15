"""
CosyVoice 2.0/3.0 离线 TTS 引擎 — CosyVoiceTTSEngine

通过 subprocess 在隔离 Python 环境中运行 CosyVoice 推理，
避免 PyTorch 版本冲突和依赖污染。主进程仅负责 prompt 音频预处理和子进程管理。

用法:
    engine = CosyVoiceTTSEngine(model_version="v3", prompt_audio="speaker.wav")
    engine.warmup()
    engine.synthesize("你好世界", "output.wav")
    engine.cleanup()
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

import torch
import torchaudio

from pipeline.logger import get_logger

logger = get_logger(__name__)

_COSYVOICE_TTS_LOCK = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORKER_SCRIPT = PROJECT_ROOT / "models" / "CosyVoice" / "cosyvoice_worker.py"
_ISOLATED_PYTHON = PROJECT_ROOT / "models" / "CosyVoice" / ".python310" / "python.exe"
_ISOLATED_PKGS = PROJECT_ROOT / "models" / "CosyVoice" / ".cosyvenv" / "Lib" / "site-packages"
_MODELS_DIR = PROJECT_ROOT / "models"


class CosyVoiceTTSEngine:
    """CosyVoice 离线 TTS 引擎（subprocess 隔离模式）。

    通过 stdin/stdout JSON 协议与隔离 Python 进程中的 CosyVoice 通信，
    主进程不加载 CosyVoice 模型，避免了 PyTorch 版本冲突。
    """

    _VERSION_TO_ID = {"v2": "cosyvoice", "v3": "cosyvoice3"}
    _VALID_LANGS = {"zh", "en", "ja", "ko", "yue"}

    def __init__(
        self,
        model_version: str = "v2",
        model_path: str = "",
        prompt_audio: Optional[str] = None,
        prompt_text: Optional[str] = None,
        fp16: bool = True,
        default_speed: float = 1.0,
        tts_mode: str = "auto",
        lang: str = "",
        worker_python: str = "",
        worker_script: str = "",
        site_packages: str = "",
        model_root: str = "",
    ):
        self._model_version = model_version
        if model_path:
            self._model_path = model_path
        else:
            from pipeline.model_manager import ModelManager
            model_id = self._VERSION_TO_ID.get(model_version, "cosyvoice")
            self._model_path = str(ModelManager.get_path(model_id))
        self._prompt_audio_path: Optional[str] = prompt_audio
        self._prompt_text: Optional[str] = prompt_text
        self._fp16 = fp16
        self._default_speed = max(0.5, min(2.0, default_speed))
        self._tts_mode = tts_mode
        self._lang = self._normalize_lang(lang)

        self._worker_python = worker_python or str(_ISOLATED_PYTHON)
        self._worker_script = worker_script or str(_WORKER_SCRIPT)
        self._site_packages = site_packages or str(_ISOLATED_PKGS)
        self._model_root = model_root or str(_MODELS_DIR)

        self._proc: Optional[subprocess.Popen] = None
        self._prompt_audio: Optional[torch.Tensor] = None
        self._prompt_wav_path: Optional[str] = None
        self._loaded = False
        self._worker_available = True

    @staticmethod
    def _normalize_lang(lang: str) -> str:
        if not lang:
            return ""
        raw = lang.lower().replace("-", "").replace("_", "")
        if raw in CosyVoiceTTSEngine._VALID_LANGS:
            return raw
        for valid in ("zh", "yue", "ja", "ko", "en"):
            if raw.startswith(valid) or valid in raw:
                return valid
        if len(raw) >= 2:
            if raw[:2] in CosyVoiceTTSEngine._VALID_LANGS:
                return raw[:2]
        return ""

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    @property
    def isolated(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional["EmotionStyle"] = None,  # type: ignore
    ) -> float:
        if not self._worker_available:
            raise RuntimeError("CosyVoice 隔离工作进程不可用")
        if self._proc is None:
            if not self._restart_worker():
                raise RuntimeError("CosyVoice worker 未启动，请先调用 warmup()")

        # health check: if worker died since last call, auto-restart
        if self._proc is not None and self._proc.poll() is not None:
            logger.warning(
                "CosyVoice worker 意外退出 (code=%s), 自动重启",
                self._proc.returncode,
            )
            self._dump_stderr_log()
            self._shutdown_worker()
            if not self._restart_worker():
                raise RuntimeError("CosyVoice worker 重启失败")

        self._ensure_prompt()
        speed = self._parse_rate(rate)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        mode = "cross_lingual" if self._tts_mode == "cross_lingual" else "zero_shot"

        req = {
            "action": "synthesize",
            "text": text,
            "prompt_audio": self._prompt_wav_path,
            "prompt_text": self._prompt_text or "",
            "mode": mode,
            "speed": speed,
            "output_path": output_path,
            "lang": self._lang,
        }

        try:
            resp = self._send_command(req)
            if resp.get("status") != "ok":
                raise RuntimeError(resp.get("message", "Unknown error"))
            return float(resp.get("duration_s", 0))
        except RuntimeError:
            self._dump_stderr_log()
            raise
        except Exception as e:
            self._dump_stderr_log()
            raise RuntimeError(f"CosyVoice 合成失败: {e}") from e

    def get_voices(self) -> List[str]:
        return []

    def supports_rate(self) -> bool:
        return True

    def supports_emotion(self) -> bool:
        return False

    def emotion_modes(self) -> List[str]:
        return []

    def warmup(self) -> None:
        if self._loaded and self._proc is not None:
            return

        if not os.path.isfile(self._worker_python):
            logger.warning("隔离 Python 不存在: %s, CosyVoice 不可用", self._worker_python)
            self._worker_available = False
            return

        if not os.path.isfile(self._worker_script):
            logger.warning("worker 脚本不存在: %s, CosyVoice 不可用", self._worker_script)
            self._worker_available = False
            return

        with _COSYVOICE_TTS_LOCK:
            if self._loaded and self._proc is not None:
                return

            logger.info("启动 CosyVoice 隔离 worker: %s", self._worker_python)
            self._stderr_log = tempfile.NamedTemporaryFile(
                prefix="cosyvoice_stderr_", suffix=".log",
                delete=False, mode="w", encoding="utf-8",
            )
            logger.debug("worker stderr → %s", self._stderr_log.name)
            worker_env = os.environ.copy()
            worker_env.pop("PYTHONUNBUFFERED", None)
            worker_env["PYTHONIOENCODING"] = "utf-8"
            try:
                self._proc = subprocess.Popen(
                    [
                        self._worker_python,
                        self._worker_script,
                        "--site-packages", self._site_packages,
                        "--model-root", self._model_root,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=self._stderr_log,
                    env=worker_env,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as e:
                self._stderr_log.close()
                try:
                    os.unlink(self._stderr_log.name)
                except OSError:
                    pass
                logger.warning("无法启动 CosyVoice worker: %s", e)
                self._worker_available = False
                self._proc = None
                return

            resp = self._send_command({
                "action": "warmup",
                "model_version": self._model_version,
                "model_path": self._model_path,
                "fp16": self._fp16,
            }, timeout=120)

            if resp.get("status") != "ok":
                msg = resp.get("message", "Unknown")
                logger.error("CosyVoice worker warmup 失败: %s", msg)
                self._shutdown_worker()
                self._worker_available = False
                return

            smoke = resp.get("smoke_test", {})
            logger.info(
                "CosyVoice worker 就绪: smoke_test %.1fs, RMS=%.4f, sr=%d",
                smoke.get("duration_s", 0),
                smoke.get("rms", 0),
                resp.get("sample_rate", 24000),
            )
            self._loaded = True

    def cleanup(self) -> None:
        self._shutdown_worker()
        self._loaded = False
        self._prompt_audio = None
        if self._prompt_wav_path and os.path.isfile(self._prompt_wav_path):
            try:
                os.unlink(self._prompt_wav_path)
            except OSError:
                pass
            self._prompt_wav_path = None
        try:
            import gc
            torch.cuda.empty_cache()
            gc.collect()
        except Exception:
            pass

    def reset_speaker(
        self,
        prompt_audio: Optional[str] = None,
        prompt_text: Optional[str] = None,
    ) -> None:
        if prompt_audio is not None:
            self._prompt_audio_path = prompt_audio
        if prompt_text is not None:
            self._prompt_text = prompt_text
        self._prompt_audio = None
        if self._prompt_wav_path and os.path.isfile(self._prompt_wav_path):
            try:
                os.unlink(self._prompt_wav_path)
            except OSError:
                pass
            self._prompt_wav_path = None

    def _send_command(self, req: dict, timeout: int = 120) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("CosyVoice worker 已退出")

        line = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"向 worker 发送命令失败: {e}")

        deadline = time.time() + timeout
        while time.time() < deadline:
            resp_line = self._proc.stdout.readline()
            if resp_line:
                return json.loads(resp_line.strip())
            time.sleep(0.1)

        stderr_info = ""
        if hasattr(self, "_stderr_log") and self._stderr_log is not None:
            self._stderr_log.flush()
            try:
                with open(self._stderr_log.name, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    if lines:
                        stderr_info = "\nworker stderr tail:\n" + "".join(lines[-30:])
            except Exception:
                pass
        raise RuntimeError(f"worker 响应超时 ({timeout}s){stderr_info}")
    def _shutdown_worker(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                try:
                    self._send_command({"action": "shutdown"}, timeout=5)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        if hasattr(self, "_stderr_log") and self._stderr_log is not None:
            try:
                self._stderr_log.close()
            except Exception:
                pass
            try:
                os.unlink(self._stderr_log.name)
            except OSError:
                pass
            self._stderr_log = None

    def _dump_stderr_log(self) -> None:
        """输出 worker stderr 日志到主日志（用于诊断 worker 崩溃）。"""
        if not hasattr(self, "_stderr_log") or self._stderr_log is None:
            return
        try:
            self._stderr_log.flush()
            with open(self._stderr_log.name, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if content.strip():
                logger.warning(
                    "CosyVoice worker stderr (%s):\n%s",
                    self._stderr_log.name,
                    content[-4000:],
                )
        except Exception:
            pass

    def _restart_worker(self) -> bool:
        """自动重启已崩溃的 worker 并重新 warmup。"""
        self._loaded = False
        self._prompt_audio = None
        if self._prompt_wav_path:
            try:
                os.unlink(self._prompt_wav_path)
            except OSError:
                pass
            self._prompt_wav_path = None
        try:
            self.warmup()
            return self._loaded
        except Exception as e:
            logger.error("CosyVoice worker 自动重启失败: %s", e)
            self._worker_available = False
            return False

    def _parse_rate(self, rate_str: str) -> float:
        s = rate_str.strip()
        if s.endswith("%"):
            try:
                pct = float(s[:-1].replace("+", "")) / 100.0
                return max(0.5, min(2.0, 1.0 + pct))
            except ValueError:
                pass
        return 1.0

    def _ensure_prompt(self) -> None:
        if self._prompt_audio is not None:
            return
        if not self._prompt_audio_path or not os.path.isfile(self._prompt_audio_path):
            raise RuntimeError(f"CosyVoice TTS 参考音频不存在: {self._prompt_audio_path}")

        with _COSYVOICE_TTS_LOCK:
            if self._prompt_audio is not None:
                return
            wav, sr = torchaudio.load(self._prompt_audio_path)
            if sr != 16000:
                wav = torchaudio.functional.resample(wav, sr, 16000)
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
            max_samples = 30 * 16000
            if wav.shape[1] > max_samples:
                wav = wav[:, :max_samples]
            self._prompt_audio = wav
            logger.info("CosyVoice TTS prompt 音频已加载: %s", self._prompt_audio_path)
            fd, tmp_path = tempfile.mkstemp(
                prefix="cosyvoice_prompt_", suffix=".wav"
            )
            os.close(fd)
            torchaudio.save(tmp_path, wav.clamp(-1, 1), 16000, bits_per_sample=16)
            self._prompt_wav_path = tmp_path


class CosyVoiceTTSEngineFactory:
    @staticmethod
    def from_config(config) -> CosyVoiceTTSEngine:
        return CosyVoiceTTSEngine(
            model_version=getattr(config, "cosyvoice_tts_model_version", "v2"),
            model_path=getattr(config, "cosyvoice_tts_model_path", ""),
            prompt_audio=getattr(config, "cosyvoice_tts_prompt_audio", None),
            prompt_text=getattr(config, "cosyvoice_tts_prompt_text", None),
            fp16=getattr(config, "cosyvoice_tts_fp16", True),
            default_speed=getattr(config, "cosyvoice_tts_speed", 1.0),
            tts_mode=getattr(config, "cosyvoice_tts_mode", "auto"),
            lang=getattr(config, "cosyvoice_tts_lang", ""),
        )
