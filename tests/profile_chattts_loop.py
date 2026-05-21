"""
复现生产环境 ChatTTS 加载→推理→清理流程，多次推理验证 RAM 是否累积。

用法:
    .venv/Scripts/python tests/profile_chattts_loop.py
"""

import os
import sys
import gc
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HOME"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["TORCH_HOME"] = os.path.join(PROJECT_ROOT, "models")

from memory_profiler import memory_usage
import torch


# 模拟真实视频字幕：长短混排，中英文混排
REAL_SUBTITLES = [
    "大家好，欢迎收看今天的视频。",
    "今天我们要讨论一个非常重要的话题。",
    "人工智能正在改变我们的生活方式。",
    "让我们来看看具体的数据分析结果。",
    "这个模型在测试集上达到了百分之九十五的准确率。",
    "接下来我会展示一些实际的应用案例。",
    "这项技术的核心优势在于它的可扩展性。",
    "我们需要考虑计算资源和时间成本的权衡。",
    "实验结果证明了我们之前的假设是正确的。",
    "感谢大家的观看，我们下期再见。",
    "在深度学习领域，Transformer架构已经成为了主流选择。",
    "通过对比实验，我们发现新方法比传统方法提高了百分之三十的效率。",
    "代码已开源在GitHub上，欢迎大家提出改进建议。",
    "这个项目的目标是让每个人都能轻松使用AI技术。",
    "根据最新研究，大语言模型在推理能力上有了显著提升。",
    "使用GPU进行训练可以显著提高deep learning模型的训练速度。",
    "这个API接口支持RESTful架构和JSON格式的数据交换。",
    "我们使用PyTorch框架实现了论文中的神经网络结构。",
    "RTX 3060显卡在深度学习任务中表现非常出色。",
    "Python语言因为其简洁的语法和丰富的库而广受欢迎。",
    "在自然语言处理任务中，预训练模型通过在海量文本数据上进行自监督学习，获得了丰富的语言知识表示。",
    "反向传播算法的核心思想是通过链式法则计算损失函数对每个参数的梯度。",
    "随着模型规模的不断增大，如何在保证性能的同时降低计算成本。",
    "多模态学习通过融合视觉、语言和音频等多种信息源，能够构建更加鲁棒和通用的人工智能系统。",
    "注意力机制允许模型在处理序列数据时动态关注不同位置的信息。",
    "好的。", "没问题。", "我们继续。", "看这里。",
    "接下来呢？", "对了，还有一件事。", "总结一下。",
    "这个很重要。", "记住这个公式。", "回头再说。",
]

N_INFERS = len(REAL_SUBTITLES)
CHECK_INTERVAL = 5

OUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")
os.makedirs(OUT_DIR, exist_ok=True)


def simulate_production_flow():
    """完全复现生产环境 ChatTTS 加载和推理流程"""
    from pipeline.tts_chattts import ChatTTSEngine

    engine = ChatTTSEngine(
        speaker_seed=2,
        model_source="local",
        model_path=None,
        pronunciation_entries={"RTX": "RTX", "3060": "三零六零"},
    )

    engine.warmup()

    snapshots = []
    t0 = time.time()
    for i, text in enumerate(REAL_SUBTITLES):
        out = os.path.join(OUT_DIR, f"_loop_{i:03d}.wav")
        engine.synthesize(text, out)

        if (i + 1) % CHECK_INTERVAL == 0 or i == 0:
            mem = memory_usage(-1, max_usage=True)
            snapshots.append((i + 1, mem))
            print(f"  [{i+1:3d}/{N_INFERS}] RAM: {mem:.0f} MiB")

    t1 = time.time()
    total_dur = t1 - t0

    engine.cleanup()
    gc.collect()
    torch.cuda.empty_cache()
    time.sleep(0.5)
    after_mem = memory_usage(-1, max_usage=True)

    return snapshots, after_mem, total_dur


if __name__ == "__main__":
    print("=" * 60)
    print("ChatTTS 多次推理 RAM 累积测试")
    print(f"测试条数: {N_INFERS} 条字幕")
    print(f"模式: warmup → synthesize × {N_INFERS} → cleanup")
    print("=" * 60)

    gc.collect()
    torch.cuda.empty_cache()
    base_mem = memory_usage(-1, max_usage=True)
    print(f"\n基线 RAM: {base_mem:.0f} MiB\n")

    snapshots, after_mem, total_dur = simulate_production_flow()

    print(f"\n{'=' * 60}")
    print(f"结果分析")
    print(f"{'=' * 60}")

    first_mem = snapshots[0][1] if snapshots else 0
    last_mem = snapshots[-1][1] if snapshots else 0
    growth = last_mem - first_mem

    print(f"  首次快照 RAM:  {first_mem:.0f} MiB  (第 1 条后)")
    print(f"  末次快照 RAM:  {last_mem:.0f} MiB  (第 {snapshots[-1][0]} 条后)")
    print(f"  推理过程增长:  {growth:+.0f} MiB")
    print(f"  cleanup 后:    {after_mem:.0f} MiB")
    print(f"  cleanup 回收:  {last_mem - after_mem:.0f} MiB")
    print(f"  总耗时:         {total_dur:.1f}s ({total_dur/N_INFERS:.1f}s/条)")

    if growth < 100:
        print(f"\n  [OK] RAM 增长 {growth:.0f} MiB (<100MiB)，推理过程无内存泄漏")
    elif growth < 500:
        print(f"\n  [WARN] RAM 增长 {growth:.0f} MiB，有轻微累积")
    else:
        print(f"\n  [FAIL] RAM 增长 {growth:.0f} MiB (>=500MiB)，存在内存泄漏")

    for f in os.listdir(OUT_DIR):
        if f.startswith("_loop_") and f.endswith(".wav"):
            os.remove(os.path.join(OUT_DIR, f))
    print(f"\n测试 WAV 文件已清理")
