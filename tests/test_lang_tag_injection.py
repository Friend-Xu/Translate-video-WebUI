"""
CosyVoice 3.0 中英混合发音对比测试：zero_shot vs cross_lingual vs cross_lingual+内联标签

用法（使用 CosyVoice 隔离 Python 环境）:
    D:\Workspace\Translate_video\models\CosyVoice\.python310\python.exe tests/test_lang_tag_injection.py

输出：
    tests/output/{case_id}_zs.wav       — zero_shot 模式（默认 text_frontend=True）
    tests/output/{case_id}_cl.wav       — cross_lingual 模式（无内联标签，预规范化）
    tests/output/{case_id}_tag.wav      — cross_lingual + 内联语言标签（实验性）
"""
import os
import re
import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_PKGS = PROJECT_ROOT / "models" / "CosyVoice" / ".cosyvenv" / "Lib" / "site-packages"
COSYVOICE_ROOT = PROJECT_ROOT / "models" / "CosyVoice"
MATCHA_ROOT = COSYVOICE_ROOT / "third_party" / "Matcha-TTS"
MODEL_ROOT = PROJECT_ROOT / "models"
OUTPUT_DIR = PROJECT_ROOT / "tests" / "output"

sys.path.insert(0, str(SITE_PKGS))
sys.path.insert(0, str(COSYVOICE_ROOT))
sys.path.insert(0, str(MATCHA_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("HF_HOME", str(MODEL_ROOT / "hf_cache"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# ── Language tag injection ───────────────────────────────────────────
_CJK_PAT = re.compile(
    r'[一-鿿㐀-䶿豈-﫿぀-ゟ゠-ヿ가-힯]'
)
_LATIN_PAT = re.compile(r'[a-zA-ZÀ-ɏ]')


def inject_lang_tags(text: str) -> str:
    """在 CJK/Latin 字符边界自动插入 <|zh|>/<|en|> 语言标签。"""
    if not text:
        return text
    n = len(text)
    char_lang = [None] * n
    for i, ch in enumerate(text):
        if _CJK_PAT.match(ch):
            char_lang[i] = "zh"
        elif _LATIN_PAT.match(ch):
            char_lang[i] = "en"
    result = []
    prev_lang = None
    for ch, lang in zip(text, char_lang):
        if lang is not None and lang != prev_lang:
            result.append(f"<|{lang}|>")
            prev_lang = lang
        elif lang is not None:
            prev_lang = lang
        result.append(ch)
    return "".join(result)


# ── Test cases ────────────────────────────────────────────────────────
TEST_CASES = [
    ("tech",     "今天我们讨论DeepSeek开源的第三弹V3与R1训练推理的关键技术", "技术中英混合"),
    ("cuda",     "CUDA核心数量为4096个，性能比上一代提升30%以上", "缩写+数字"),
    ("saas",     "这个SaaS平台的API响应时间从500ms降到了50ms", "专有名词+单位"),
    ("pytorch",  "他用PyTorch写了一个BERT模型做NLP任务", "多专有名词"),
    ("cpu",      "CPU使用率达到了百分之九十五，内存占用2GB", "简短缩写"),
    ("pure_zh",  "今天天气真不错，我们一起出去散步吧", "纯中文对照组"),
    ("pure_en",  "The quick brown fox jumps over the lazy dog", "纯英文对照组"),
    ("units",    "下载速度达到了10MB每秒，上传速度是5MB每秒", "数字单位混合"),
]


# ── Synthesis helpers ─────────────────────────────────────────────────

def load_model(version="v3"):
    from cosyvoice.cli.cosyvoice import CosyVoice2, CosyVoice3

    model_id = "CosyVoice2-0.5B" if version == "v2" else "CosyVoice3-0.5B"
    model_path = str(MODEL_ROOT / model_id)

    if version == "v3" and CosyVoice3 is not None:
        model = CosyVoice3(model_path, fp16=True)
    else:
        model = CosyVoice2(model_path, fp16=True)
    return model, version


def pre_normalize(model, text):
    """用 text_frontend=True 规范化数字/日期/符号。"""
    try:
        return model.frontend.text_normalize(text, split=False, text_frontend=True)
    except Exception:
        return text


def synthesize_zero_shot(model, ver, text, prompt_wav, prompt_text=""):
    """zero_shot 模式（v3 要求 prompt_text 包含 <|endofprompt|>）。"""
    if ver == "v3" and prompt_text and "<|endofprompt|>" not in prompt_text:
        prompt_text = f"You are a helpful assistant.<|endofprompt|>{prompt_text}"
    for result in model.inference_zero_shot(
        text, prompt_text, prompt_wav, stream=False, speed=1.0
    ):
        return result["tts_speech"].squeeze().cpu().numpy()
    return None


def synthesize_cross_lingual(model, ver, text, prompt_wav, lang="zh"):
    """cross_lingual 模式（预规范化，无内联标签，text_frontend=False）。"""
    normalized = pre_normalize(model, text)
    if ver == "v3":
        lang_tag = f"<|{lang}|>" if lang else ""
        final = f"You are a helpful assistant.{lang_tag}<|endofprompt|>{normalized}"
    else:
        final = normalized
    for result in model.inference_cross_lingual(
        final, prompt_wav, stream=False, speed=1.0, text_frontend=False
    ):
        return result["tts_speech"].squeeze().cpu().numpy()
    return None


def synthesize_tagged(model, ver, text, prompt_wav, lang="zh"):
    """cross_lingual + 内联语言标签（实验性）。"""
    normalized = pre_normalize(model, text)
    tagged = inject_lang_tags(normalized)
    if ver == "v3":
        lang_tag = f"<|{lang}|>" if lang else ""
        final = f"You are a helpful assistant.{lang_tag}<|endofprompt|>{tagged}"
    else:
        final = tagged
    for result in model.inference_cross_lingual(
        final, prompt_wav, stream=False, speed=1.0, text_frontend=False
    ):
        return result["tts_speech"].squeeze().cpu().numpy()
    return None


# ── Main ──────────────────────────────────────────────────────────────

def main():
    import soundfile as sf

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ver = sys.argv[1] if len(sys.argv) > 1 else "v3"
    print(f"加载 CosyVoice 模型: {ver}")
    model, mv = load_model(ver)
    sr = model.sample_rate
    print(f"  模型就绪, sample_rate={sr}")

    prompt_wav = str(COSYVOICE_ROOT / "asset" / "zero_shot_prompt.wav")
    prompt_text = "希望你以后能够做得比我还好哟"
    if not os.path.exists(prompt_wav):
        prompt_wav = str(COSYVOICE_ROOT / "asset" / "cross_lingual_prompt.wav")
    print(f"  参考音频: {prompt_wav}")
    print(f"  参考文本: {prompt_text}")

    print(f"\n{'Case':<10} {'Description':<30} {'zs':>7} {'cl':>7} {'tag':>7}")
    print("-" * 65)

    for case_id, text, desc in TEST_CASES:
        row = f"{case_id:<10} {desc:<30}"

        # A. zero_shot (baseline)
        t0 = time.time()
        audio = synthesize_zero_shot(model, mv, text, prompt_wav, prompt_text)
        if audio is not None:
            sf.write(str(OUTPUT_DIR / f"{case_id}_zs.wav"), audio, sr, subtype="PCM_16")
            row += f" {time.time()-t0:>6.1f}s"
        else:
            row += f" {'FAIL':>6}"

        # B. cross_lingual (no inline tags)
        t0 = time.time()
        audio = synthesize_cross_lingual(model, mv, text, prompt_wav)
        if audio is not None:
            sf.write(str(OUTPUT_DIR / f"{case_id}_cl.wav"), audio, sr, subtype="PCM_16")
            row += f" {time.time()-t0:>6.1f}s"
        else:
            row += f" {'FAIL':>6}"

        # C. cross_lingual + inline tags
        t0 = time.time()
        audio = synthesize_tagged(model, mv, text, prompt_wav)
        if audio is not None:
            sf.write(str(OUTPUT_DIR / f"{case_id}_tag.wav"), audio, sr, subtype="PCM_16")
            row += f" {time.time()-t0:>6.1f}s"
        else:
            row += f" {'FAIL':>6}"

        print(row)

    print(f"\n对比音频在: tests/output/")
    print(f"  *_zs.wav   = zero_shot (基线, text_frontend=True)")
    print(f"  *_cl.wav   = cross_lingual (预规范化, 无内联标签)")
    print(f"  *_tag.wav  = cross_lingual + 内联语言标签 (实验)")


if __name__ == "__main__":
    main()
