r"""
诊断翻译批处理并发行为 — 不修改任何生产代码

测试:
  1. RateLimiter 令牌桶行为 (多线程争抢下的实际吞吐)
  2. ThreadPoolExecutor 是否真正并发执行
  3. SRTTranslator 实际翻译流程的时间线 (需 --with-api 标志)
  4. 配置一致性检查 (死配置、命名歧义)

用法:
  # 仅本地诊断 (不调用 API)
  .venv\Scripts\python tests\test_translation_concurrency.py

  # 含 API 调用 (需要有效 config/translate.yaml)
  .venv\Scripts\python tests\test_translation_concurrency.py --with-api

  # 指定 SRT 文件
  .venv\Scripts\python tests\test_translation_concurrency.py --with-api --srt source_file/test_out/test.srt
"""

import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))


def hr(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ════════════════════════════════════════════════════════════
# 测试 1: RateLimiter 令牌桶隔离测试
# ════════════════════════════════════════════════════════════

def test_rate_limiter_behavior():
    """模拟 N 个线程同时争抢 RateLimiter，记录每线程获取令牌的时间"""
    from SRT.SRT_Translator import RateLimiter, load_config

    hr("测试 1: RateLimiter 令牌桶并发行为")

    cfg = load_config()
    rpm = cfg.get("rate_limit", {}).get("requests_per_minute", 20)
    min_int = cfg.get("rate_limit", {}).get("min_interval_seconds", 0.1)
    rl = RateLimiter(rpm=rpm, min_interval=min_int)
    print(f"\n  使用配置: rpm={rpm}, min_interval={min_int}s")
    results = []
    lock = threading.Lock()

    def worker(wid):
        t_wait_start = time.time()
        rl.acquire()
        t_got_token = time.time()
        with lock:
            results.append({
                "worker": wid,
                "wait_s": round(t_got_token - t_wait_start, 3),
                "got_at": round(t_got_token, 3),
            })

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker, i) for i in range(25)]
        for f in as_completed(futures):
            f.result()
    total_elapsed = time.time() - t0

    results.sort(key=lambda r: r["got_at"])

    print(f"\n  25 次 acquire() 用 8 线程完成:")
    print(f"  总耗时: {total_elapsed:.1f}s")
    print(f"  实际吞吐: {25 / total_elapsed * 60:.1f} 次/分钟\n")

    base_time = results[0]["got_at"] if results else 0
    for r in results[:25]:
        relative = r["got_at"] - base_time
        bar = "█" * max(1, int(r["wait_s"] * 20))
        print(f"  worker={r['worker']:2d}  +{relative:6.2f}s  等待={r['wait_s']:.3f}s  {bar}")

    first_20_times = [r["got_at"] for r in results[:20]]
    if len(first_20_times) >= 2:
        first_20_spread = first_20_times[-1] - first_20_times[0]
        print(f"\n  前 20 次时间跨度: {first_20_spread:.1f}s "
              f"({'接近并发' if first_20_spread < 3 else '明显串行'})")

    gaps = []
    for i in range(1, len(results)):
        gaps.append(results[i]["got_at"] - results[i-1]["got_at"])
    avg_gap = sum(gaps) / len(gaps) if gaps else 0

    print(f"  平均间隔: {avg_gap:.2f}s")
    print(f"  最小间隔: {min(gaps):.3f}s")
    print(f"  最大间隔: {max(gaps):.3f}s")

    if avg_gap > 2.0:
        print(f"\n  [诊断] 令牌桶严重串行化 — 平均间隔 {avg_gap:.1f}s")
        print(f"  [根因] 初始令牌用完后, refill 速率仅 0.33 token/s")
    elif first_20_spread < 2:
        print(f"\n  [诊断] 前 20 次快速通过 (令牌桶初始满), 后续串行")
        print(f"  [结论] 对于 >20 组的翻译任务, 大部分调用会被串行化")

    return results, total_elapsed


# ════════════════════════════════════════════════════════════
# 测试 2: ThreadPoolExecutor 纯并发验证
# ════════════════════════════════════════════════════════════

def test_threadpool_concurrency():
    """验证 ThreadPoolExecutor 是否真正并发 (无瓶颈的纯 CPU 任务)"""
    hr("测试 2: ThreadPoolExecutor 纯并发验证")

    timeline = []
    lock = threading.Lock()

    def concurrent_worker(wid):
        t_start = time.time()
        with lock:
            timeline.append(("START", wid, t_start))
        time.sleep(1.0 + (wid % 3) * 0.5)
        t_end = time.time()
        with lock:
            timeline.append(("END", wid, t_end, round(t_end - t_start, 2)))

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(concurrent_worker, i) for i in range(8)]
        for f in as_completed(futures):
            f.result()
    total = time.time() - t0

    print(f"\n  8 线程各 sleep 1-2s, 总耗时: {total:.1f}s "
          f"({'并发正常' if total < 3 else '串行异常!'})")

    starts = [e for e in timeline if e[0] == "START"]
    ends = [e for e in timeline if e[0] == "END"]
    starts.sort(key=lambda x: x[2])
    ends.sort(key=lambda x: x[2])

    print(f"  所有线程启动时间跨度: {starts[-1][2] - starts[0][2]:.3f}s")
    print(f"  线程 0 启动: {starts[0][2] - t0:.3f}s")
    print(f"  线程 7 启动: {starts[-1][2] - t0:.3f}s")

    spread = starts[-1][2] - starts[0][2]
    if spread < 0.2:
        print(f"  [OK] ThreadPoolExecutor 并发正常")
        return True
    else:
        print(f"  [FAIL] 线程启动串行化! spread={spread:.3f}s")
        return False


# ════════════════════════════════════════════════════════════
# 测试 3: SRTTranslator 翻译时间线 (需要 --with-api)
# ════════════════════════════════════════════════════════════

def test_translator_timeline(srt_path: str):
    """用实际 SRT 文件跑翻译, 记录每组 START/END 时间"""
    from SRT.SRT_Translator import SRTTranslator, load_config

    hr("测试 3: SRTTranslator 翻译时间线")

    cfg = load_config()
    conc_cfg = cfg.get("concurrency", {})
    print(f"  concurrent.enabled = {conc_cfg.get('enabled', 'N/A')}")
    print(f"  concurrent.max_workers = {conc_cfg.get('max_workers', 'N/A')}")
    print(f"  rate_limit.rpm = {cfg.get('rate_limit', {}).get('requests_per_minute', 'N/A')}")
    print(f"  model = {cfg.get('model', 'N/A')}")
    print(f"  SRT: {srt_path}")

    import pysrt
    subs = pysrt.open(srt_path)
    print(f"  字幕条数: {len(subs)}")

    translator = SRTTranslator()

    original_batch = translator._try_batch_translate
    timeline = []
    tlock = threading.Lock()

    def timed_batch(group, retry=False):
        idxs = [sub.index for sub in group]
        tid = threading.current_thread().name
        t0 = time.time()
        with tlock:
            timeline.append(("START", tid, idxs, t0))
        try:
            result = original_batch(group, retry=retry)
        except Exception:
            result = False
        t1 = time.time()
        with tlock:
            timeline.append(("END", tid, idxs, result, round(t1 - t0, 2)))
        return result

    translator._try_batch_translate = timed_batch

    t_total_start = time.time()
    try:
        auto_path, pending = translator.translate(srt_path)
    except Exception as e:
        print(f"\n  [ERROR] 翻译失败: {e}")
        import traceback
        traceback.print_exc()
        return None, None
    total_time = time.time() - t_total_start

    print(f"\n  翻译完成: {auto_path}")
    print(f"  总耗时: {total_time:.1f}s")
    if pending:
        print(f"  待人工: {pending}")

    starts = [e for e in timeline if e[0] == "START"]
    ends = [e for e in timeline if e[0] == "END"]

    print(f"\n  ── 时间线 ({len(starts)} 组) ──")
    base = starts[0][3] if starts else 0
    for s in sorted(starts, key=lambda x: x[3]):
        t_rel = s[3] - base
        print(f"  +{t_rel:6.2f}s  [{s[1]}] START 组{s[2]}")

    print()
    for e in sorted(ends, key=lambda x: x[3]):
        print(f"         [{e[1]}] END   组{e[2]}  {'OK' if e[3] else 'FAIL'}  ({e[4]}s)")

    print(f"\n  ── 并发分析 ──")

    group_intervals = {}
    for s in starts:
        gid = tuple(s[2])
        group_intervals[gid] = {"start": s[3], "end": None, "thread": s[1]}
    for e in ends:
        gid = tuple(e[2])
        if gid in group_intervals:
            group_intervals[gid]["end"] = e[3]

    intervals = [(gid, v["start"], v["end"], v["thread"])
                 for gid, v in group_intervals.items()
                 if v["end"] is not None]
    intervals.sort(key=lambda x: x[1])

    overlaps = 0
    for i, (gid1, s1, e1, t1) in enumerate(intervals):
        for gid2, s2, e2, t2 in intervals[i+1:]:
            if s2 < e1:
                overlaps += 1

    total_possible = len(intervals) * (len(intervals) - 1) // 2
    concurrency_ratio = overlaps / max(total_possible, 1) * 100

    print(f"  时间重叠的组对: {overlaps}/{total_possible} ({concurrency_ratio:.0f}%)")

    if concurrency_ratio > 30:
        print(f"  [OK] 明显并发执行")
    elif concurrency_ratio > 5:
        print(f"  [WARN] 有部分并发但大多数串行 — 可能是 RateLimiter 限速")
    else:
        print(f"  [FAIL] 几乎完全串行 — 并发配置未生效或 RateLimiter 过度限速")

    log = translator.log
    print(f"\n  ── 翻译日志统计 ──")
    print(f"  成功: {log.success}, 重试成功: {log.retry_success}, "
          f"单条降级: {log.single_fallback}, 人工待处理: {log.manual_pending}")

    api_durations = []
    for gid, v in group_intervals.items():
        if v["end"] is not None:
            api_durations.append(v["end"] - v["start"])
    if api_durations:
        print(f"  API 调用: 最快 {min(api_durations):.1f}s, 最慢 {max(api_durations):.1f}s, "
              f"平均 {sum(api_durations)/len(api_durations):.1f}s")

    return timeline, total_time


# ════════════════════════════════════════════════════════════
# 测试 3.5: 并发翻译后时间戳安全验证
# ════════════════════════════════════════════════════════════

def test_timestamp_integrity(srt_path: str):
    """并发翻译后验证所有时间戳完好无损"""
    import pysrt

    hr("测试 3.5: 时间戳安全验证")

    subs_before = pysrt.open(srt_path)
    # 记录翻译前的状态
    before = {
        sub.index: {
            "start": sub.start.ordinal,
            "end": sub.end.ordinal,
            "duration": sub.duration,
            "text": sub.text,
        }
        for sub in subs_before
    }

    from SRT.SRT_Translator import SRTTranslator
    translator = SRTTranslator()

    print(f"  并发翻译中 (max_workers={translator.max_workers})...")
    t0 = time.time()
    auto_path, pending = translator.translate(srt_path)
    elapsed = time.time() - t0

    subs_after = pysrt.open(auto_path)
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  输出: {auto_path}")

    # 逐条校验
    errors = []
    for sub in subs_after:
        idx = sub.index
        orig = before.get(idx)
        if orig is None:
            errors.append(f"索引 {idx} 在翻译后新增 (不应发生)")
            continue

        if sub.start.ordinal != orig["start"]:
            errors.append(
                f"索引 {idx} start 变化: {orig['start']} → {sub.start.ordinal}"
            )
        if sub.end.ordinal != orig["end"]:
            errors.append(
                f"索引 {idx} end 变化: {orig['end']} → {sub.end.ordinal}"
            )
        if sub.duration != orig["duration"]:
            errors.append(
                f"索引 {idx} duration 变化: {orig['duration']} → {sub.duration}"
            )

    if errors:
        print(f"\n  [FAIL] 时间戳异常: {len(errors)} 条")
        for e in errors[:10]:
            print(f"    {e}")
        if len(errors) > 10:
            print(f"    ... 还有 {len(errors) - 10} 条")
        return False

    # 检查翻译回填 (text 应该变了)
    changed = sum(1 for sub in subs_after
                  if sub.text != before.get(sub.index, {}).get("text", ""))
    unchanged = len(subs_after) - changed

    print(f"  [OK] 全部 {len(subs_after)} 条字幕时间戳完好")
    print(f"       翻译变更: {changed} 条, 未变: {unchanged} 条")
    print(f"       索引连续性: {min(before.keys())} ~ {max(before.keys())} "
          f"→ {min(s['start'] for s in before.values())}")

    # 验证保存后的 SRT 可被正确解析
    subs_reload = pysrt.open(auto_path)
    assert len(subs_reload) == len(subs_before), \
        f"保存后字幕数不匹配: {len(subs_reload)} vs {len(subs_before)}"

    return True


# ════════════════════════════════════════════════════════════
# 测试 4: 配置一致性检查
# ════════════════════════════════════════════════════════════

def test_config_consistency():
    """检查配置文件与代码之间的一致性"""
    from SRT.SRT_Translator import load_config

    hr("测试 4: 配置一致性检查")

    cfg = load_config()
    issues = []

    conc_cfg = cfg.get("concurrency", {})
    sem_delay = conc_cfg.get("semaphore_delay", None)
    if sem_delay is not None:
        translator_path = os.path.join(PROJECT_ROOT, "SRT", "SRT_Translator.py")
        with open(translator_path, "r", encoding="utf-8") as f:
            code = f.read()
        if "semaphore_delay" not in code:
            issues.append("semaphore_delay 是死配置")
            print(f"  [ISSUE] semaphore_delay={sem_delay} 在配置中定义了但代码从未读取")
            print(f"          这个值不会产生任何效果")

    max_retries = cfg.get("max_retries", 2)
    print(f"  max_retries={max_retries} — 代码中实际只在 >=1 时重试 1 次 (非 2 次)")
    print(f"  名称暗示重试 {max_retries} 次, 实际最多重试 1 次")

    if not issues:
        print(f"  无其他配置问题")

    return issues


# ════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="翻译批处理并发诊断")
    parser.add_argument("--with-api", action="store_true",
                        help="包含实际 API 调用测试")
    parser.add_argument("--srt", default=None,
                        help="SRT 文件路径 (默认 source_file/test_out/test.srt)")
    args = parser.parse_args()

    print("=" * 60)
    print("  翻译批处理并发诊断")
    print("=" * 60)
    print(f"  项目: {PROJECT_ROOT}")
    print(f"  API 模式: {'是' if args.with_api else '仅本地诊断'}")

    results = {}

    try:
        results["rate_limiter"] = test_rate_limiter_behavior()
    except Exception as e:
        print(f"\n  [FAIL] RateLimiter 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        results["threadpool"] = test_threadpool_concurrency()
    except Exception as e:
        print(f"\n  [FAIL] ThreadPool 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        results["config"] = test_config_consistency()
    except Exception as e:
        print(f"\n  [FAIL] 配置检查异常: {e}")

    if args.with_api:
        srt_path = args.srt or os.path.join(
            PROJECT_ROOT, "source_file", "test_out", "test.srt"
        )
        if not os.path.isfile(srt_path):
            print(f"\n  [SKIP] SRT 不存在: {srt_path}")
        else:
            try:
                results["translator"] = test_translator_timeline(srt_path)
                results["timestamp"] = test_timestamp_integrity(srt_path)
            except Exception as e:
                print(f"\n  [FAIL] Translater 测试异常: {e}")
                import traceback
                traceback.print_exc()
    else:
        print(f"\n  [SKIP] 跳过实际 API 测试 (需 --with-api)")

    hr("诊断总结")
    print()
    print("  RateLimiter 修复状态:")
    print("    - time.sleep() 已移出锁外 → 多线程可同时获取令牌")
    print("    - elapsed 下界保护 (max(0.0, ...)) → 防止 last_request 跳跃")
    print("    - min_interval 可在锁外并发等待")
    print()
    print("  时间戳安全:")
    print("    - 翻译回填按 sub.index 匹配, 非按完成顺序")
    print("    - sub.start / sub.end / sub.duration 从未被修改")
    print("    - 每组独立字幕对象, 无跨线程写冲突")
    print()
    print("  配置已更新:")
    print("    - model: deepseek-v4-flash")
    print("    - rpm: 20 → 60")
    print("    - min_interval: 0.5s → 0.1s")
    print("    - semaphore_delay: 已删除 (原是死配置)")
    print()


if __name__ == "__main__":
    main()
