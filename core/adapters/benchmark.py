"""
Adapter Benchmark (CLI Runtime 计划书 §11)

单适配器性能基准 — 测量推理延迟和显存。
通过 capability_id 查找已注册适配器，运行 warmup + 多次推理取平均。
"""
from __future__ import annotations
import time
from dataclasses import dataclass


@dataclass
class BenchmarkResult:
    capability_id: str = ""
    device: str = "cpu"
    warmup_s: float = 0.0
    latency_s_per_item: float = 0.0
    vram_mb: float = 0.0
    items: int = 0
    error: str = ""


def _gpu_memory_mb() -> float:
    try:
        import torch
        return torch.cuda.max_memory_allocated() / 1024 / 1024
    except Exception:
        return 0.0


def benchmark_whisper(audio_path: str, device: str = "cuda",
                      model_name: str = "small", iterations: int = 3) -> BenchmarkResult:
    """Whisper ASR benchmark — 对音频文件做 VAD+转录。"""
    from core.adapters.whisper_adapter import WhisperAdapter, EngineContext
    result = BenchmarkResult(capability_id="asr.whisper", device=device)
    try:
        ctx = EngineContext(audio_path=audio_path, device=device, model_name=model_name)
        adapter = WhisperAdapter(ctx)
        t0 = time.time()
        adapter.run()
        result.warmup_s = round(time.time() - t0, 1)
        latencies = []
        for _ in range(iterations):
            adapter = WhisperAdapter(ctx)
            t0 = time.time()
            patches = adapter.run()
            latencies.append(time.time() - t0)
            result.items = len(patches)
        result.latency_s_per_item = round(sum(latencies) / len(latencies), 2)
        result.vram_mb = round(_gpu_memory_mb(), 1)
    except Exception as exc:
        result.error = str(exc)
    return result


def benchmark_chattts(text: str = "你好世界，这是一个测试",
                      iterations: int = 3) -> BenchmarkResult:
    """ChatTTS benchmark — 测量单段合成延迟。"""
    result = BenchmarkResult(capability_id="tts.chattts", device="cuda")
    try:
        from core.adapters.chattts_adapter import ChatTTSAdapter, TTSSegmentContext
        adapter = ChatTTSAdapter()
        ctx = TTSSegmentContext(segment_id="bench", translation_text=text)
        t0 = time.time()
        adapter.synthesize(ctx)
        result.warmup_s = round(time.time() - t0, 1)
        latencies = []
        for _ in range(iterations):
            t0 = time.time()
            adapter.synthesize(ctx)
            latencies.append(time.time() - t0)
        result.latency_s_per_item = round(sum(latencies) / len(latencies), 2)
        result.items = iterations
        result.vram_mb = round(_gpu_memory_mb(), 1)
    except Exception as exc:
        result.error = str(exc)
    return result


def run_benchmark(capability_id: str, **kwargs) -> BenchmarkResult:
    if capability_id == "asr.whisper":
        audio = kwargs.get("audio", "test.wav")
        return benchmark_whisper(audio, kwargs.get("device", "cuda"),
                                 kwargs.get("model", "small"))
    elif capability_id == "tts.chattts":
        return benchmark_chattts(kwargs.get("text", "你好世界"))
    return BenchmarkResult(error=f"unknown capability: {capability_id}")


def format_result(r: BenchmarkResult) -> str:
    if r.error:
        return f"{r.capability_id:24s}  ERROR: {r.error}"
    return (f"{r.capability_id:24s}  {r.device:6s}  "
            f"warmup={r.warmup_s:5.1f}s  latency={r.latency_s_per_item:5.1f}s/item  "
            f"vram={r.vram_mb:5.1f}MB  items={r.items}")
