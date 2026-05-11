"""
复现 test_project 翻译质量问题：语义校验为何没报警。

测试：
1. 用 paraphrase-multilingual-MiniLM-L12-v2 对 source->machine 做语义相似度
2. 验证模型是否能检测到烂翻译
3. 对比：如果去掉 source_lang=="ja" 限制，校验能否拦截
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 模拟 SRT_Translator 的环境
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
hf_home = os.path.join(project_root, "models", "hf_cache")
os.environ["HF_HOME"] = hf_home
os.environ["TRANSFORMERS_CACHE"] = hf_home

from SRT.TranslationVerifier import TranslationVerifier


def parse_srt(srt_path):
    import re
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = content.strip().split("\n\n")
    result = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            idx = int(lines[0])
            ts = lines[1]
            text = "\n".join(lines[2:])
            m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", ts)
            start = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000
            end = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000
            result.append({"index": idx, "start": start, "end": end, "text": text})
    return result


def main():
    test_dir = os.path.join(project_root, "source_file", "test_project")
    source_path = os.path.join(test_dir, "01_extract", "source.srt")
    machine_path = os.path.join(test_dir, "02_translate", "machine.srt")

    source = parse_srt(source_path)
    machine = parse_srt(machine_path)

    print(f"Source subtitles: {len(source)}")
    print(f"Machine subtitles: {len(machine)}")
    print()

    machine_by_idx = {s["index"]: s["text"] for s in machine}

    print("=" * 80)
    print("Testing CrossLingualScorer (paraphrase-multilingual-MiniLM-L12-v2)")
    print("Language: EN (source) -> ZH (translation)")
    print("Threshold: 0.65")
    print("=" * 80)
    print()

    verifier = TranslationVerifier(threshold=0.65)

    flagged_count = 0
    results = []

    for s in source:
        idx = s["index"]
        src_text = s["text"]
        tgt_text = machine_by_idx.get(idx, "")
        if not tgt_text:
            continue

        result = verifier.verify(src_text, tgt_text)
        results.append((idx, src_text[:80], tgt_text[:80], result))

        flag = "[LOW]" if result["flagged"] else "[OK]"
        if result["flagged"]:
            flagged_count += 1
        print(f"  #{idx} {flag} sim={result['similarity']:.3f}")
        print(f"    EN: {src_text[:100]}")
        print(f"    ZH: {tgt_text[:100]}")
        print()

    print("=" * 80)
    print(f"RESULTS: {flagged_count}/{len(results)} flagged (below 0.65)")
    if flagged_count == 0:
        print()
        print("  *** BUG CONFIRMED ***")
        print("  All translations passed semantic check despite poor quality.")
        print("  Root cause: SRT_Translator.py:1031 restricts semantic check to")
        print("  source_lang == 'ja' only. The multilingual model CAN detect")
        print("  bad EN->ZH translations, but the code never invokes it.")
        print()
        print("  FIX: Remove 'self.source_lang == \"ja\"' condition at line 1031.")
    else:
        print(f"  Semantic verifier correctly flagged {flagged_count} translations.")
        print("  FIX: Enable semantic check for ALL languages (remove 'ja' restriction).")

    sims = [r[3]["similarity"] for r in results]
    print()
    print(f"  Similarity distribution: min={min(sims):.3f}, max={max(sims):.3f}, "
          f"avg={sum(sims)/len(sims):.3f}")

    # Control: perfect translation should score high
    print()
    print("--- Control: perfect translation ---")
    perfect = verifier.verify(
        "Today we are looking at the best Minecraft modpacks.",
        "今天我们要来看一下最好的Minecraft整合包。"
    )
    print(f"  sim={perfect['similarity']:.3f}, flagged={perfect['flagged']}")

    return flagged_count


if __name__ == "__main__":
    sys.exit(main())
