#!/usr/bin/env python3
"""
IndexTTS persistent inference worker — stdin/stdout JSON protocol.

Isolated Python environment: models/IndexTTS/.venv/
Run with: models/IndexTTS/.venv/Scripts/python.exe indextts_worker.py

Protocol (one JSON object per line, no trailing whitespace):
    <- {"action":"warmup","checkpoints_dir":"...","fp16":true}
    -> {"status":"ok","sample_rate":22050}

    <- {"action":"synthesize","text":"...","output_path":"...","spk_audio_prompt":"...",
        "target_length_ms":5000,"speed":1.0}
    -> {"status":"ok","duration_s":3.2,"wav_path":"..."}

    <- {"action":"health"}
    -> {"status":"ok","model_loaded":true}

    <- {"action":"shutdown"}
    -> {"status":"ok"}
"""
from __future__ import annotations

import json
import os
import sys
import traceback

# HuggingFace — use mirror, fall back to cached files
if os.environ.get("HF_ENDPOINT") is None:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# Allow offline mode if network unavailable (models are cached)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128"


class IndexTTSWorker:
    def __init__(self):
        self._tts = None
        self._sample_rate = 22050

    def run(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                    resp = self._handle(req)
                except Exception as e:
                    resp = {"status": "error", "message": str(e)}
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                if req.get("action") == "shutdown":
                    break
        except Exception:
            sys.stderr.write(f"FATAL: indextts worker crashed:\n{traceback.format_exc()}\n")
            sys.stderr.flush()

    def _handle(self, req: dict) -> dict:
        action = req.get("action", "")
        if action == "warmup":
            return self._warmup(req)
        elif action == "synthesize":
            return self._synthesize(req)
        elif action == "health":
            return self._health()
        elif action == "shutdown":
            return self._shutdown()
        return {"status": "error", "message": f"Unknown action: {action}"}

    def _warmup(self, req: dict) -> dict:
        sys.stderr.write("[worker] warmup starting...\n"); sys.stderr.flush()
        try:
            import torch
            torch.set_num_threads(1)
            sys.stderr.write("[worker] torch imported\n"); sys.stderr.flush()

            from indextts.infer_v2 import IndexTTS2

            checkpoints_dir = req.get("checkpoints_dir", "checkpoints")
            cfg_path = os.path.join(checkpoints_dir, "config.yaml")
            fp16 = req.get("fp16", True)

            self._tts = IndexTTS2(
                cfg_path=cfg_path,
                model_dir=checkpoints_dir,
                use_fp16=fp16,
                use_cuda_kernel=False,
            )
            return {"status": "ok", "sample_rate": self._sample_rate}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _synthesize(self, req: dict) -> dict:
        if self._tts is None:
            return {"status": "error", "message": "Model not loaded, call warmup first"}
        try:
            import numpy as np
            import soundfile as sf

            text = req["text"]
            output_path = req["output_path"]
            spk_audio_prompt = req.get("spk_audio_prompt", "")
            target_length_ms = req.get("target_length_ms")
            speed = req.get("speed", 1.0)
            emo_vector = req.get("emo_vector")
            emo_alpha = req.get("emo_alpha", 1.0)

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            self._tts.infer(
                spk_audio_prompt=spk_audio_prompt,
                text=text,
                output_path=output_path,
                speed=speed,
                target_length_ms=target_length_ms,
                emo_vector=emo_vector,
                emo_alpha=emo_alpha,
                verbose=False,
            )

            native_sr = self._sample_rate
            target_sr = 44100
            audio_data, sr = sf.read(output_path)
            if sr != target_sr:
                from scipy.signal import resample
                if audio_data.ndim > 1:
                    audio_data = audio_data.mean(axis=1)
                target_len = int(len(audio_data) * target_sr / sr)
                audio_data = resample(audio_data, target_len).astype(np.float32)
                sf.write(output_path, audio_data, target_sr, subtype="PCM_16")
                duration = float(len(audio_data) / target_sr)
            else:
                duration = float(len(audio_data) / sr)

            return {"status": "ok", "duration_s": duration, "wav_path": output_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _health(self) -> dict:
        return {"status": "ok", "model_loaded": self._tts is not None}

    def _shutdown(self) -> dict:
        try:
            if self._tts is not None:
                del self._tts
                self._tts = None
                import torch
                torch.cuda.empty_cache()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    # Strip system CUDA paths to prevent conflicts with PyTorch's bundled CUDA libs
    cuda_paths = [p for p in os.environ.get("PATH", "").split(";")
                  if "CUDA" in p.upper() or "NVIDIA GPU" in p.upper()]
    for p in cuda_paths:
        os.environ["PATH"] = os.environ["PATH"].replace(p + ";", "").replace(";" + p, "").replace(p, "")
    # Also strip from os.add_dll_directory equivalents
    if hasattr(os, 'add_dll_directory'):
        pass  # Can't undo add_dll_directory, but PATH removal helps

    worker_dir = os.path.dirname(os.path.abspath(__file__))
    fork_root = os.path.join(worker_dir, "index-tts-batch")
    os.chdir(fork_root)
    if fork_root not in sys.path:
        sys.path.insert(0, fork_root)

    IndexTTSWorker().run()
