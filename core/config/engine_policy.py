"""EnginePolicy auto-derivation from runtime environment (定稿 §1.6)."""
from __future__ import annotations
from core.config.global_config import EnginePolicy

def derive_engine_policy():
    policy = EnginePolicy()
    try:
        import torch
        if torch.cuda.is_available():
            policy.device = 'cuda'
            policy.compute_type = 'float16'
            gpu_count = torch.cuda.device_count()
            policy.max_concurrent_tts = min(2, gpu_count)
            policy.max_concurrent_translation = min(3, gpu_count * 2)
            if gpu_count > 0:
                free, total = torch.cuda.mem_get_info(0)
                vram_gb = total / (1024**3)
                policy.chattts_vram_mode = 'high' if vram_gb >= 6 else ('medium' if vram_gb >= 4 else 'low')
            if gpu_count > 1:
                policy.cosyvoice_device = 'cuda:1'
        else:
            policy.device = 'cpu'; policy.compute_type = 'int8'
            policy.chattts_vram_mode = 'low'; policy.max_concurrent_tts = 1
    except ImportError:
        policy.device = 'cpu'; policy.compute_type = 'int8'
        policy.chattts_vram_mode = 'low'; policy.max_concurrent_tts = 1
    return policy
