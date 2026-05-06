"""
测试 VADTranscriber 模型池功能:
  1. 模型池加载 (VRAM 限制计算)
  2. 并行 vs 串行输出一致性 (数据准确性)
  3. 模型池 get/put 并发安全性
  4. 模型释放清理
"""
import os
import sys
import gc
import queue
import time
import threading
import soundfile as sf
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HOME"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["SENTENCE_TRANSFORMERS_HOME"] = os.path.join(PROJECT_ROOT, "models", "hf_cache")
os.environ["TORCH_HOME"] = os.path.join(PROJECT_ROOT, "models")


def _find_test_wav():
    wav_path = os.path.join(PROJECT_ROOT, "source_file", "test_out", "test.wav")
    if os.path.isfile(wav_path):
        info = sf.SoundFile(wav_path)
        if info.frames / info.samplerate >= 10:
            info.close()
            return wav_path
        info.close()
    return None


def test_vram_limit_calculation():
    """VRAM 限制计算: CPU 不限, tiny/small 正确估算"""
    print("\n=== 测试 1: VRAM 限制计算 ===")
    from pipeline.transcriber import VADTranscriber

    wav = _find_test_wav()
    if not wav:
        print("  [SKIP] 无可用测试音频")
        return

    tc = VADTranscriber(wav, model_name="small", device="cpu", num_workers=4)
    local_root = os.path.join(PROJECT_ROOT, "models", "whisper")
    model_path = os.path.join(local_root, "small")

    result = tc._compute_vram_limit(model_path, 4)
    assert result == 4, f"CPU 应原样返回 4, 实际 {result}"
    print(f"  [PASS] CPU: 4 workers → {result}")

    tiny_path = os.path.join(local_root, "tiny")
    if os.path.isdir(tiny_path):
        tc.model_name = "tiny"
        result = tc._compute_vram_limit(tiny_path, 8)
        assert result == 8, f"tiny CPU 应返回 8, 实际 {result}"
        print(f"  [PASS] tiny CPU: 8 workers → {result}")

    del tc


def test_model_pool_loading():
    """模型池加载: N 个独立实例, 清理释放"""
    print("\n=== 测试 2: 模型池加载 ===")
    from pipeline.transcriber import VADTranscriber

    wav = _find_test_wav()
    if not wav:
        print("  [SKIP] 无可用测试音频")
        return

    tc = VADTranscriber(wav, model_name="small", device="cpu", num_workers=2)
    t0 = time.time()
    load_time = tc._load_model_pool(2)
    elapsed = time.time() - t0

    assert tc._model_pool is not None
    assert tc._model_pool.qsize() == 2, f"池应有 2 个模型, 实际 {tc._model_pool.qsize()}"
    print(f"  [PASS] 加载 2 个实例, 耗时 {load_time:.1f}s")

    m1 = tc._model_pool.get()
    m2 = tc._model_pool.get()
    assert m1 is not m2, "两个实例应是不同对象"
    tc._model_pool.put(m1)
    tc._model_pool.put(m2)
    print(f"  [PASS] 两个实例为独立对象")

    destroyed = 0
    while True:
        try:
            m = tc._model_pool.get_nowait()
            del m
            destroyed += 1
        except queue.Empty:
            break
    assert destroyed == 2, f"应销毁 2, 实际 {destroyed}"
    tc._model_pool = None
    gc.collect()
    print(f"  [PASS] 清理: {destroyed} 个实例")

    del tc
    return


def test_serial_vs_parallel_accuracy():
    """串行 vs 并行输出一致性 — 数据准确性核心测试"""
    print("\n=== 测试 3: 串行 vs 并行输出一致性 ===")
    from pipeline.transcriber import VADTranscriber

    wav = _find_test_wav()
    if not wav:
        print("  [SKIP] 无可用测试音频")
        return

    print("  注意: 此测试需完整转录流程, 耗时较长...")

    print("  [1/2] 串行转录 (num_workers=1)...")
    tc_s = VADTranscriber(wav, model_name="small", device="cpu", num_workers=1)
    tc_s.run_vad(force=True)
    r_s = tc_s.transcribe_all(language="en")
    s_words = r_s["words"]
    s_segs = r_s["segments"]
    s_t = r_s["stats"]["transcribe_time"]
    print(f"    串行: {len(s_words)} words, {len(s_segs)} segments, {s_t:.1f}s")

    print("  [2/2] 并行转录 (num_workers=2)...")
    tc_p = VADTranscriber(wav, model_name="small", device="cpu", num_workers=2)
    tc_p._vad_segments = tc_s._vad_segments
    r_p = tc_p.transcribe_all(language="en")
    p_words = r_p["words"]
    p_segs = r_p["segments"]
    p_t = r_p["stats"]["transcribe_time"]
    print(f"    并行: {len(p_words)} words, {len(p_segs)} segments, {p_t:.1f}s")

    # 词数偏差 < 10%
    wdiff = abs(len(s_words) - len(p_words)) / max(len(s_words), 1) * 100
    assert wdiff < 10, f"词数偏差过大: {wdiff:.1f}%"
    print(f"  [PASS] 词数偏差: {wdiff:.1f}%")

    # segments 偏差 ≤ 2
    seg_diff = abs(len(s_segs) - len(p_segs))
    assert seg_diff <= 2, f"Segments 偏差: {len(s_segs)} vs {len(p_segs)}"
    print(f"  [PASS] Segments: {len(s_segs)} vs {len(p_segs)}")

    # 文本字符偏差 < 15%
    sc = sum(len(x["text"]) for x in s_segs)
    pc = sum(len(x["text"]) for x in p_segs)
    cd = abs(sc - pc) / max(sc, 1) * 100
    assert cd < 15, f"文本偏差过大: {cd:.1f}%"
    print(f"  [PASS] 文本字符偏差: {cd:.1f}%")

    # 语言一致
    assert r_s["language"] == r_p["language"]
    print(f"  [PASS] 语言一致: {r_s['language']}")

    # 时间戳合理
    if p_words:
        assert p_words[0]["start"] >= 0
        assert p_words[-1]["end"] > p_words[0]["start"]
        print(f"  [PASS] 时间: {p_words[0]['start']:.1f}s ~ {p_words[-1]['end']:.1f}s")

    assert tc_p._model_pool is None, "模型池应已清理"
    print(f"  [PASS] 模型池已清理")

    if s_t > 0 and p_t > 0:
        speedup = s_t / p_t
        print(f"\n  加速比: {speedup:.2f}× (串行 {s_t:.1f}s / 并行 {p_t:.1f}s)")

    del tc_s, tc_p
    return


def test_model_pool_queue():
    """模型池队列并发安全: 空池阻塞, 归还可用"""
    print("\n=== 测试 4: 模型池队列并发安全 ===")
    from pipeline.transcriber import VADTranscriber

    wav = _find_test_wav()
    if not wav:
        print("  [SKIP] 无可用测试音频")
        return

    tc = VADTranscriber(wav, model_name="small", device="cpu", num_workers=2)
    tc._load_model_pool(2)

    m1 = tc._model_pool.get(timeout=5)
    m2 = tc._model_pool.get(timeout=5)
    assert tc._model_pool.qsize() == 0
    print(f"  [PASS] 池排空: 0/{tc._model_pool.maxsize}")

    got = [None]

    def _try_get():
        try:
            got[0] = tc._model_pool.get(timeout=2)
        except queue.Empty:
            got[0] = "timeout"

    t = threading.Thread(target=_try_get)
    t.start()
    t.join(timeout=5)
    assert got[0] == "timeout", f"空池 get 应超时, 实际 {got[0]}"
    print(f"  [PASS] 空池 get(timeout=2) 正确超时")

    tc._model_pool.put(m2)
    m2b = tc._model_pool.get(timeout=5)
    assert m2b is m2, "归还后应取回同一对象"
    tc._model_pool.put(m2b)
    tc._model_pool.put(m1)
    print(f"  [PASS] 归还后取回同一实例")

    destroyed = 0
    while True:
        try:
            m = tc._model_pool.get_nowait()
            del m
            destroyed += 1
        except queue.Empty:
            break
    assert destroyed == 2
    tc._model_pool = None
    gc.collect()
    print(f"  [PASS] 清理: {destroyed} 个实例")

    del tc
    return


def main():
    print("=" * 60)
    print("  VADTranscriber 模型池测试")
    print("=" * 60)

    tests = [
        ("VRAM 限制计算", test_vram_limit_calculation),
        ("模型池加载", test_model_pool_loading),
        ("串行 vs 并行一致性", test_serial_vs_parallel_accuracy),
        ("模型池队列安全", test_model_pool_queue),
    ]

    results = {}
    for name, func in tests:
        try:
            results[name] = func()
        except Exception as e:
            print(f"\n  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
        gc.collect()

    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n  {passed}/{total} 通过")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
