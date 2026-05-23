"""
ChatTTS 内存分析 — 单独测试脚本，不影响现有系统。

用法:
    .venv/Scripts/python tests/profile_chattts_memory.py
"""

import os
import sys
import gc

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HOME"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["TORCH_HOME"] = os.path.join(PROJECT_ROOT, "models")

from memory_profiler import memory_usage
import torch


def profile_load():
    """仅加载模型，不推理"""
    from pipeline.tts_chattts import ChatTTSEngine
    engine = ChatTTSEngine(speaker_seed=2)
    engine._load_model()
    engine._ensure_spk_emb()
    return engine


def profile_infer(engine, text):
    """单次推理"""
    import soundfile as sf
    import numpy as np
    out = "tests/output/_mem_test.wav"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    engine.synthesize(text, out)


if __name__ == "__main__":
    print("=" * 60)
    print("ChatTTS 内存分析")
    print("=" * 60)

    # ── 基线 ──
    gc.collect()
    torch.cuda.empty_cache()
    base_mem = memory_usage(-1, max_usage=True)
    print(f"\n基线 RAM: {base_mem:.1f} MiB")

    # ── 模型加载 ──
    print("\n[1/2] 模型加载 + speaker 初始化...")
    mem_usage = memory_usage((profile_load,), max_usage=True)
    peak_mem = max(mem_usage) if isinstance(mem_usage, list) else mem_usage
    print(f"  加载峰值 RAM: {peak_mem:.1f} MiB  (增量: {peak_mem - base_mem:.1f} MiB)")

    # ── 推理 ──
    engine = profile_load()
    test_texts = [
        "你好，这是一个测试句子。",
        "今天我们要讨论人工智能在医疗领域的应用与发展前景。",
        "在深度学习中，反向传播算法通过计算损失函数相对于每个权重的梯度来更新网络参数，这使得多层神经网络能够从数据中学习复杂的非线性映射关系。",
    ]

    for i, text in enumerate(test_texts):
        gc.collect()
        torch.cuda.empty_cache()
        before = memory_usage(-1, max_usage=True)

        mem_usage = memory_usage((profile_infer, (engine, text),), max_usage=True)
        peak_mem = max(mem_usage) if isinstance(mem_usage, list) else mem_usage

        print(f"\n[2.{i+1}] 推理 '{text[:20]}...' ({len(text)} chars)")
        print(f"  推理前 RAM: {before:.1f} MiB")
        print(f"  推理峰值 RAM: {peak_mem:.1f} MiB  (增量: {peak_mem - before:.1f} MiB)")

    # ── 清理后 ──
    engine.cleanup()
    gc.collect()
    torch.cuda.empty_cache()
    after_mem = memory_usage(-1, max_usage=True)
    print(f"\n清理后 RAM: {after_mem:.1f} MiB  (释放: {peak_mem - after_mem:.1f} MiB)")

    print("\n" + "=" * 60)
    print("分析完成")
    print("=" * 60)
