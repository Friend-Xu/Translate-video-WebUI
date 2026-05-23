#!/usr/bin/env python3
"""
ChatTTS persistent inference worker — stdin/stdout JSON protocol.

Gives ChatTTS its own CUDA context, preventing STATUS_HEAP_CORRUPTION
from PyTorch allocator conflicts with CTranslate2 / MiniLM on Windows.

Protocol (one JSON object per line):
    <- {"action":"warmup","speaker_seed":42,"model_source":"local",...}
    -> {"status":"ok","sample_rate":24000,"speaker_seed":42}

    <- {"action":"synthesize","text":"...","output_path":"..."}
    -> {"status":"ok","duration_s":3.2,"wav_path":"..."}

    <- {"action":"health"}
    -> {"status":"ok","model_loaded":true}

    <- {"action":"shutdown"}
    -> {"status":"ok"}
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# CUDA safety: must run BEFORE any torch import
if os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True,max_split_size_mb:128"
os.environ.setdefault("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")


class ChatTTSWorker:
    def __init__(self):
        self._chat = None
        self._spk_emb = None
        self._speaker_seed = None
        self._sample_rate = 24000
        self._use_decoder = True

    def run(self):
        """Main loop: read JSON lines from stdin, dispatch, write JSON to stdout."""
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
            sys.stderr.write(f"FATAL: worker run() crashed:\n{traceback.format_exc()}\n")
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
        try:
            import ChatTTS
            from ChatTTS import Chat

            import torch
            torch.set_num_threads(1)

            logging.getLogger("ChatTTS").setLevel(logging.WARNING)

            speaker_seed = req.get("speaker_seed")
            model_source = req.get("model_source", "local")
            model_path = req.get("model_path", "")
            speaker_pt = req.get("speaker_pt", "")
            self._use_decoder = req.get("use_decoder", True)

            chat = Chat()
            load_kwargs = {"source": model_source, "compile": False}

            if model_source == "custom" and model_path:
                load_kwargs["custom_path"] = model_path
            elif model_source == "local":
                from pipeline.model_manager import ModelManager
                status = ModelManager.check("chattts")
                if status.exists:
                    load_kwargs["custom_path"] = status.path

            chat.load(**load_kwargs)

            import numpy as np
            if speaker_pt and os.path.isfile(speaker_pt):
                import torch
                self._spk_emb = torch.load(speaker_pt, map_location="cpu",
                                           weights_only=True).to("cuda")
                self._speaker_seed = None
            else:
                import random as _random
                if speaker_seed is not None:
                    self._speaker_seed = int(speaker_seed)
                else:
                    self._speaker_seed = _random.randint(0, 2**31 - 1)
                np.random.seed(self._speaker_seed)
                self._spk_emb = chat.sample_random_speaker()

            self._chat = chat
            return {"status": "ok", "sample_rate": self._sample_rate,
                    "speaker_seed": self._speaker_seed}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _synthesize(self, req: dict) -> dict:
        if self._chat is None:
            return {"status": "error", "message": "Model not loaded, call warmup first"}
        try:
            import numpy as np
            import soundfile as sf
            from ChatTTS import Chat

            text = req["text"]
            output_path = req["output_path"]
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            params_infer_code = Chat.InferCodeParams(
                spk_emb=self._spk_emb,
                temperature=0.3, top_P=0.7, top_K=20,
            )
            params_refine_text = Chat.RefineTextParams(
                prompt=req.get("refine_prompt", "[oral_0][break_5]")
            )

            wavs = self._chat.infer(
                text,
                skip_refine_text=False,
                use_decoder=self._use_decoder,
                do_text_normalization=False,
                split_text=False,
                params_infer_code=params_infer_code,
                params_refine_text=params_refine_text,
            )

            if not wavs or len(wavs) == 0:
                return {"status": "error", "message": "infer returned empty result"}

            wav = wavs[0]
            if hasattr(wav, "detach"):
                wav = wav.detach().cpu().numpy()
            audio_data = np.asarray(wav, dtype=np.float32).copy()
            del wavs, wav

            # Resample from 24000 Hz to 44100 Hz for video pipeline compatibility.
            # Non-standard sample rates cause metallic distortion (电音) when
            # encoded by moviepy/ffmpeg into MP4 containers.
            native_sr = self._sample_rate
            target_sr = 44100
            if native_sr != target_sr:
                from scipy.signal import resample
                target_len = int(len(audio_data) * target_sr / native_sr)
                audio_data = resample(audio_data, target_len).astype(np.float32)

            sf.write(output_path, audio_data, target_sr, subtype="PCM_16")
            duration = float(len(audio_data) / target_sr)
            del audio_data

            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass

            return {"status": "ok", "duration_s": duration, "wav_path": output_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _health(self) -> dict:
        try:
            import torch
            gpu_name = ""
            vram_mb = 0
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                vram_mb = int(
                    torch.cuda.get_device_properties(0).total_memory / 1024 / 1024
                )
            return {
                "status": "ok",
                "model_loaded": self._chat is not None,
                "gpu_name": gpu_name,
                "vram_mb": vram_mb,
            }
        except Exception:
            return {"status": "ok", "model_loaded": self._chat is not None}

    def _shutdown(self) -> dict:
        try:
            if self._chat is not None:
                del self._chat
                self._chat = None
            self._spk_emb = None
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            import gc
            gc.collect()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


def main():
    worker = ChatTTSWorker()
    worker.run()


if __name__ == "__main__":
    main()
