"""
SRT_Translator.py — 全自动字幕翻译器

支持：
- 语义分组翻译（3-8条/组）
- 双格式输出：<index> text（首选）| JSON（备选）
- 三级降级：分组 → 重试 → 逐条 → 人工兜底
- 术语词典后处理
- 结构化日志

═══ 质量保障：语义核验（可选） ═══

启用条件: config 中 semantic_check=true（默认开启）

机制:
  TranslationVerifier 用 sentence-transformers 跨语言模型
  (paraphrase-multilingual-MiniLM-L12-v2) 计算日语原文与
  中文译文的余弦相似度。低于阈值 (default 0.65) 的翻译
  自动触发带上下文（前文+下文）的重新翻译，保留两版中
  语义更接近原文的结果。全部低于阈值则标记「建议人工复核」。

依赖: pip install sentence-transformers
          ↓ 首次运行会自动从 HuggingFace 下载模型 (~470MB)
          中国大陆用户默认使用 hf-mirror.com 镜像

═══ 日语分析：MeCab 分词 ═══

Json_Convert_Srt.py 中使用 fugashi + ipadic 进行日语分词，
用于 SRT 时间轴自适应断句（不在本文件）。

依赖: pip install fugashi ipadic
"""

import hashlib
import os
import sys
import re
import json
import time
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

import pysrt
import yaml
import requests

# 语义核对（可选，延迟加载）
_verifier_module = None


def _lazy_import_verifier():
    global _verifier_module
    if _verifier_module is None:
        # 确保项目根目录在 sys.path 中，不论如何启动此脚本
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_script_dir)
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from SRT.TranslationVerifier import TranslationVerifier as _V
        _verifier_module = _V
    return _verifier_module


# 术语替换（可选，延迟加载）
_term_replacer = None


def _lazy_import_term_replacer():
    global _term_replacer
    if _term_replacer is None:
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_script_dir)
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from SRT.TermReplacer import replace_terms as _rt
        _term_replacer = _rt
    return _term_replacer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SRT_Translator")


# ── 常量 ──────────────────────────────────────────

BASE_EXAMPLE = (
    "示例输入：\n"
    "<1> Hello everyone\n"
    "<2> welcome back\n"
    "<3> today we have something exciting\n\n"
    "示例输出：\n"
    "<1> 大家好\n"
    "<2> 欢迎回来\n"
    "<3> 今天我们有个激动人心的消息"
)

COMPLEX_EXAMPLE = (
    "示例输入：\n"
    "<1> Wait, that's not\n"
    "<2> supposed to happen!\n"
    "<3> Let me try again\n"
    "<4> okay here we go\n"
    "<5> three two one\n\n"
    "示例输出：\n"
    "<1> 等等，这不\n"
    "<2> 应该发生的！\n"
    "<3> 让我再试一次\n"
    "<4> 好了开始吧\n"
    "<5> 三二一"
)

SENTENCE_END_PUNCT = {'.', '!', '?', '。', '！', '？'}


# ── 配置加载 ──────────────────────────────────────

def find_config_path(preferred: str = "config/translate.yaml") -> str:
    candidates = [
        preferred,
        os.path.join(os.path.dirname(__file__), "..", "config", "translate.yaml"),
        "config/translate.yaml",
        "Local_API_translate/config/translate.yaml",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"未找到翻译配置文件，请创建 {preferred}")


def load_config(config_path: Optional[str] = None) -> dict:
    path = config_path or find_config_path()
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 环境变量覆盖 API key
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if api_key:
        cfg["translate"]["api_key"] = api_key
    return cfg.get("translate", cfg)


def _prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:12]


# ── 速率限制器 ────────────────────────────────────

class RateLimiter:
    """Token bucket 速率限制器"""

    def __init__(self, rpm: int = 20, min_interval: float = 0.5):
        self.tokens = float(rpm)
        self.max_tokens = float(rpm)
        self.min_interval = min_interval
        self.last_request = 0.0
        self.lock = threading.Lock()

    def acquire(self):
        # 锁内只做原子记账 (微秒级)，锁外 sleep 允许并发获取令牌
        with self.lock:
            now = time.time()
            # 补充 token
            elapsed = max(0.0, now - self.last_request)
            self.tokens = min(self.max_tokens, self.tokens + elapsed * (self.max_tokens / 60.0))
            if self.tokens >= 1:
                self.tokens -= 1.0
                token_wait = 0.0
            else:
                token_wait = (1.0 - self.tokens) * (60.0 / self.max_tokens)
                self.tokens = 0.0
            # 最小间隔 (since_last 可能为负，当多线程同时抢占时)
            since_last = max(0.0, now - self.last_request)
            interval_wait = max(0.0, self.min_interval - since_last)
            wait = max(token_wait, interval_wait)
            self.last_request = now + wait
        if wait > 0:
            time.sleep(wait)


# ── API 抽象 ──────────────────────────────────────

class TranslationAPI(ABC):
    @abstractmethod
    def translate(self, prompt: str, system_prompt: str = "") -> str:
        pass


class DeepSeekAPI(TranslationAPI):
    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com", **kwargs):
        if not api_key:
            raise ValueError("API key 未配置")
        self.api_key = api_key
        self.model = model
        self.temperature = kwargs.get("temperature", 0.1)
        self.max_tokens = kwargs.get("max_tokens", 4000)
        self.top_p = kwargs.get("top_p", 0.9)
        self.timeout = kwargs.get("timeout", 60)
        self.url = f"{base_url.rstrip('/')}/v1/chat/completions"

    def translate(self, prompt: str, system_prompt: str = "") -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }

        import time as _time
        max_429_retries = 5
        for attempt in range(max_429_retries + 1):
            try:
                resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
                if resp.status_code == 429:
                    delay = 2 ** attempt  # 1, 2, 4, 8, 16s
                    logger.warning(
                        f"DeepSeek API 429 限流 (attempt {attempt+1}/{max_429_retries+1}), "
                        f"{delay}s 后重试..."
                    )
                    if attempt < max_429_retries:
                        _time.sleep(delay)
                        continue
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            except requests.exceptions.RequestException as e:
                logger.error(f"DeepSeek API 请求失败: {e}")
                raise
            except (KeyError, IndexError) as e:
                logger.error(f"DeepSeek API 响应解析失败: {e}")
                raise


# OpenAI-compatible API providers with their default base URLs
_OPENAI_COMPATIBLE_PROVIDERS = {
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.ai/v1",
    "xiaomi": "https://api.xiaomimimo.com/v1",
}

def create_api_client(config: dict) -> TranslationAPI:
    api_type = config.get("api_type", "deepseek")
    base_url = config.get("api_base_url", "")
    if not base_url:
        base_url = _OPENAI_COMPATIBLE_PROVIDERS.get(api_type, "https://api.deepseek.com")
    return DeepSeekAPI(
        api_key=config.get("api_key", ""),
        model=config.get("model", "deepseek-chat"),
        base_url=base_url,
        temperature=config.get("temperature", 0.1),
        max_tokens=config.get("max_tokens", 4000),
        top_p=config.get("top_p", 0.9),
        timeout=config.get("timeout", 60),
    )


# ── 格式解析 ──────────────────────────────────────

def parse_numbered_list(text: str) -> Dict[int, str]:
    """解析 '<1> xxx\n<2> yyy' → {1:'xxx', 2:'yyy'}"""
    pattern = re.compile(r"^\s*<(\d+)>\s*(.*?)$", re.MULTILINE)
    result = {}
    for m in pattern.finditer(text):
        idx = int(m.group(1))
        result[idx] = m.group(2).strip()
    return result


def parse_json_translation(text: str) -> Dict[int, str]:
    """解析 JSON → {1:'xxx', 2:'yyy'}"""
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
        return {int(k): str(v).strip() for k, v in data.items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def validate_format(source_group: List[pysrt.SubRipItem], translated_text: str, fmt: str = "numbered_list") -> Tuple[bool, Dict[int, str], str]:
    """验证翻译格式
    返回: (success, mapping, error_reason)
    """
    if fmt == "json":
        parsed = parse_json_translation(translated_text)
    else:
        parsed = parse_numbered_list(translated_text)

    if not parsed:
        return False, {}, "无法解析输出格式"

    if len(parsed) != len(source_group):
        return False, {}, f"数量不匹配: {len(parsed)} vs {len(source_group)}"

    expected = {sub.index for sub in source_group}
    actual = set(parsed.keys())
    if expected != actual:
        missing = expected - actual
        extra = actual - expected
        return False, {}, f"编号缺失: {missing}, 多余: {extra}"

    for idx, txt in parsed.items():
        if not txt.strip():
            return False, {}, f"第{idx}行为空"

    return True, parsed, ""


# ── 语言检测 ──────────────────────────────────────

_LANG_LABELS = {
    "ja": "日语", "en": "英语", "zh": "简体中文", "zh-CN": "简体中文",
    "zh-TW": "繁體中文", "ko": "韩语", "fr": "法语", "de": "德语",
    "es": "西班牙语", "pt": "葡萄牙语", "ru": "俄语", "ar": "阿拉伯语",
    "th": "泰语", "vi": "越南语", "id": "印尼语", "it": "意大利语",
}


def detect_source_language(subs: pysrt.SubRipFile, sample_size: int = 20) -> str:
    sample = " ".join(sub.text for sub in subs[:sample_size])
    ja_chars = re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", sample)
    en_chars = re.findall(r"[a-zA-Z]", sample)
    if len(ja_chars) > len(en_chars) * 2:
        return "ja"
    return "en"


# ── Prompt 变量替换 ───────────────────────────────

def resolve_prompt_variables(template: str, variables: dict) -> str:
    """替换模板中的 {var_name} 占位符。"""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


# ── Prompt 构建 ───────────────────────────────────

def build_system_prompt(source_lang: str, fmt: str = "numbered_list", retry: bool = False,
                        custom_template: str = None, target_lang: str = "简体中文") -> str:
    # 构建格式强制要求（自定义 prompt 不可移除此部分）
    if fmt == "json":
        fmt_rules = (
            "输出格式必须为 JSON 对象: {\"1\":\"译文1\",\"2\":\"译文2\",...}\n"
            "键必须与原编号完全一致\n"
            "不要添加任何额外字段或说明\n"
            "只返回 JSON，不要 markdown 代码块"
        )
    else:
        fmt_rules = (
            "输出格式必须严格为 <index> 译文（如 <1> 大家好）\n"
            "编号数量和顺序必须与输入完全一致\n"
            "每条独立成行，不要合并\n"
            "不要添加任何额外说明或标注"
        )

    if retry:
        fmt_suffix = (
            "\n\n⚠️ 警告：上次翻译输出格式错误，请严格遵守上述格式要求！"
        )
    else:
        fmt_suffix = ""

    # 自定义模板路径：系统角色/任务行 + 用户风格指令 + 系统强制格式规则
    if custom_template:
        variables = {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "fmt": fmt,
            "retry": str(retry),
        }
        user_part = resolve_prompt_variables(custom_template, variables)
        lang_label = _LANG_LABELS.get(source_lang, source_lang)
        target_label = _LANG_LABELS.get(target_lang, target_lang)
        role_line = f"你是专业{lang_label}字幕翻译。请将以下{lang_label}逐条翻译为{target_label}。"
        style_line = f"\n风格要求：{user_part}" if user_part.strip() else ""
        system_part = (
            f"\n\n【以下为系统强制格式要求，必须严格遵守】\n"
            f"{fmt_rules}"
            f"{fmt_suffix}"
        )
        return role_line + style_line + system_part

    lang_label = _LANG_LABELS.get(source_lang, source_lang)
    target_label = _LANG_LABELS.get(target_lang, target_lang)
    base = f"你是专业{lang_label}字幕翻译。请将以下{lang_label}逐条翻译为{target_label}。"

    parts = [
        base,
        "要求：",
        "1. 准确传达原文含义，上下文连贯",
        "2. " + fmt_rules,
        "3. 不要添加解释性内容：不在译文后加括号标注英文原文、不增补版本号或日期等解释性后缀",
        "4. 保持原文的叙述节奏和句式结构，直译优先，不要改写为说明书式语言",
    ]

    if not retry:
        # 只在目标语言为中文时展示示例（非中文目标用英文示例会误导 LLM）
        if "中文" in target_label or "Chinese" in target_label:
            parts.extend([
                "",
                "示例输入：",
                "<1> Hello everyone\n<2> welcome back\n<3> today we have something exciting",
                "",
                "示例输出：",
                "<1> 大家好\n<2> 欢迎回来\n<3> 今天我们有个激动人心的消息",
            ])
    else:
        parts.extend([
            "",
            "⚠️ 警告：上次翻译输出格式错误，请严格遵守上述格式要求！",
        ])

    return "\n".join(parts)


def build_batch_prompt(group: List[pysrt.SubRipItem], fmt: str = "numbered_list",
                      custom_template: str = None, source_lang: str = "ja",
                      target_lang: str = "简体中文") -> str:
    if custom_template:
        if fmt == "json":
            items = json.dumps({str(sub.index): sub.text for sub in group}, ensure_ascii=False)
        else:
            items = "\n".join([f"<{sub.index}> {sub.text}" for sub in group])
        variables = {"source_lang": source_lang, "target_lang": target_lang,
                     "fmt": fmt, "items": items}
        return resolve_prompt_variables(custom_template, variables)

    if fmt == "json":
        items = {str(sub.index): sub.text for sub in group}
        body = json.dumps(items, ensure_ascii=False)
    else:
        lines = [f"<{sub.index}> {sub.text}" for sub in group]
        body = "\n".join(lines)

    return f"待翻译：\n{body}\n\n翻译："


def build_single_prompt(subtitle: pysrt.SubRipItem, prev_subs: List[pysrt.SubRipItem],
                       next_subs: List[pysrt.SubRipItem], source_lang: str,
                       custom_template: str = None, target_lang: str = "简体中文") -> Tuple[str, str]:
    """逐条翻译 prompt，返回 (system_prompt, user_prompt)"""
    if custom_template:
        ctx_parts = []
        for s in prev_subs[-2:]:
            ctx_parts.append(f"前文: {s.text}")
        ctx_parts.append(f"当前: {subtitle.text}")
        for s in next_subs[:2]:
            ctx_parts.append(f"后文: {s.text}")
        variables = {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "current_text": subtitle.text,
            "context": "\n".join(ctx_parts),
        }
        return resolve_prompt_variables(custom_template, variables), ""

    lang_label = _LANG_LABELS.get(source_lang, source_lang)
    target_label = _LANG_LABELS.get(target_lang, target_lang)
    system = f"你是专业{lang_label}字幕翻译。请将提供的句子翻译为{target_label}。只输出译文，不要解释，不要加引号。"

    ctx_parts = []
    for s in prev_subs[-2:]:
        ctx_parts.append(f"前文: {s.text}")
    ctx_parts.append(f"当前: {subtitle.text}")
    for s in next_subs[:2]:
        ctx_parts.append(f"后文: {s.text}")

    user = "\n".join(ctx_parts) + "\n\n请只翻译「当前」这句话，直接输出译文："
    return system, user


# ── Split-Brain 翻译器 ────────────────────────────

class SplitBrainTranslator:
    """两阶段翻译：创意翻译 + 结构映射（Vimeo split-brain 模式）。

    Phase A: 纯翻译，不限制行数，追求自然表达。
    Phase B: 将翻译文本按源字幕索引切分映射。

    两阶段失败时兜底使用规则算法。
    """

    def __init__(self, api: TranslationAPI, rate_limiter: RateLimiter,
                 source_lang: str = "ja", target_lang: str = "简体中文"):
        self.api = api
        self.rate_limiter = rate_limiter
        self.source_lang = source_lang
        self.target_lang = target_lang

    def translate_group(self, group: List[pysrt.SubRipItem]) -> Dict[int, str]:
        """Split-brain 翻译一个字幕组，返回 {index: translated_text}。"""
        if not group:
            return {}

        # Phase A: 创意翻译
        creative_prompt = self._build_creative_prompt(group)
        self.rate_limiter.acquire()
        creative_text = self.api.translate(creative_prompt)

        if not creative_text or not creative_text.strip():
            logger.warning("Split-brain Phase A 返回空，回退逐条映射")
            return self._fallback_rule(group, creative_text or "")

        # Phase B: 结构映射
        mapping_prompt = self._build_mapping_prompt(group, creative_text)
        self.rate_limiter.acquire()
        mapping_text = self.api.translate(mapping_prompt)

        result = self._parse_mapping(mapping_text, len(group))
        if result and len(result) == len(group):
            return result

        logger.warning(f"Split-brain Phase B 映射失败 ({len(result) if result else 0}/{len(group)})，使用兜底算法")
        return self._fallback_rule(group, creative_text)

    def _build_creative_prompt(self, group: List[pysrt.SubRipItem]) -> str:
        """构建创意翻译 prompt：强调自然表达，不限制行数。"""
        if self.source_lang == "ja":
            role = "你是专业日语字幕翻译。"
        else:
            role = "你是专业英语字幕翻译。"

        lines = []
        for i, sub in enumerate(group):
            lines.append(f"[{sub.index}] {sub.text}")

        return (
            f"{role}请将以下{len(group)}条字幕翻译成{self.target_lang}。\n\n"
            f"重要：只关注翻译质量和自然表达，不需要保持行数或编号一致。\n"
            f"把整段内容当成一个整体来翻译，用自然流畅的{self.target_lang}表达。\n"
            f"可以适当合并短句或拆分长句，以表达清晰为首要目标。\n\n"
            f"源字幕：\n" + "\n".join(lines) + "\n\n"
            f"请直接输出流畅自然的翻译文本（不需要编号，不需要格式）："
        )

    def _build_mapping_prompt(self, group: List[pysrt.SubRipItem],
                               creative_text: str) -> str:
        """构建结构映射 prompt：把创意翻译切回源行数。"""
        lines = []
        for i, sub in enumerate(group):
            lines.append(f"<{sub.index}> {sub.text}")

        return (
            f"下面有{len(group)}条源字幕（带编号和原文），以及一段翻译文本。\n"
            f"请将翻译文本按语义切分成恰好{len(group)}条，每条对应一条源字幕。\n\n"
            f"源字幕：\n" + "\n".join(lines) + "\n\n"
            f"翻译文本：\n{creative_text}\n\n"
            f"输出格式（严格）：\n" +
            "\n".join([f"<{sub.index}> [译文]" for sub in group]) +
            f"\n\n请直接输出{len(group)}条译文，每条一行，编号严格对应："
        )

    def _parse_mapping(self, text: str, expected_count: int) -> Dict[int, str]:
        """解析映射结果。"""
        if not text:
            return {}
        result = parse_numbered_list(text)
        if len(result) == expected_count:
            return result
        # 尝试 JSON 格式兜底
        json_result = parse_json_translation(text)
        if len(json_result) == expected_count:
            return json_result
        return result if len(result) > 0 else json_result

    def _fallback_rule(self, group: List[pysrt.SubRipItem],
                        creative_text: str) -> Dict[int, str]:
        """规则兜底：将创意翻译文本按源行字符比例分配。"""
        if not creative_text or not creative_text.strip():
            # 完全失败：返回原文
            return {sub.index: sub.text for sub in group}

        # 按源文本长度比例分配翻译文本
        total_chars = sum(len(sub.text) for sub in group)
        if total_chars == 0:
            # 均分
            return {sub.index: creative_text for sub in group}

        # 简单的逐句切分（按标点）
        segments = re.split(r'(?<=[。！？.!?\n])\s*', creative_text)
        segments = [s.strip() for s in segments if s.strip()]

        result = {}
        if len(segments) >= len(group):
            # 足够分配
            for i, sub in enumerate(group):
                result[sub.index] = segments[i] if i < len(segments) else sub.text
        else:
            # 不够分配：按比例
            ratios = [len(sub.text) / total_chars for sub in group]
            seg_idx = 0
            for i, sub in enumerate(group):
                if seg_idx < len(segments):
                    result[sub.index] = segments[seg_idx]
                    seg_idx += 1
                else:
                    result[sub.index] = sub.text

        return result


# ── 语义分组 ──────────────────────────────────────

def group_semantically(
    subs: pysrt.SubRipFile,
    max_size: int = 8,
    max_chars: int = 500,
    min_pause: float = 0.5,
) -> List[List[pysrt.SubRipItem]]:
    """按语义边界分组字幕"""
    groups = []
    current = []
    current_chars = 0

    for i, sub in enumerate(subs):
        text = sub.text.strip()
        if not text:
            continue

        # 终止条件检查（如果 current 非空）
        if current:
            last = current[-1]
            gap = (sub.start.ordinal - last.end.ordinal) / 1000.0
            last_text = last.text.strip()
            ends_sentence = last_text and last_text[-1] in SENTENCE_END_PUNCT

            should_split = (
                len(current) >= max_size
                or current_chars + len(text) > max_chars
                or (ends_sentence and gap >= min_pause)
                or gap >= min_pause * 2  # 较长停顿强制分
            )

            if should_split:
                groups.append(current)
                current = []
                current_chars = 0

        current.append(sub)
        current_chars += len(text)

    if current:
        groups.append(current)

    logger.info(f"语义分组完成: {len(groups)} 组")
    return groups


# ── 人工模式 ──────────────────────────────────────

def write_pending_file(groups: List[List[pysrt.SubRipItem]], output_path: str):
    """输出待人工翻译文件"""
    lines = [f"# 待翻译字幕\n# 共 {len(groups)} 组需要人工翻译\n"]

    for gi, group in enumerate(groups, 1):
        start = group[0].start
        end = group[-1].end
        lines.append(f"\n--- 组 {gi} (时间: {start} -> {end}) ---")
        for sub in group:
            lines.append(f"<{sub.index}> {sub.text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"待人工翻译文件已输出: {output_path}")


def parse_manual_file(manual_file: str) -> Dict[int, str]:
    """解析人工翻译文件，支持多种索引格式"""
    patterns = [
        re.compile(r"^\s*<(\d+)>\s*(.*?)$", re.MULTILINE),      # <12> 译文
        re.compile(r"^\s*\[(\d+)\]\s*(.*?)$", re.MULTILINE),    # [12] 译文
        re.compile(r"^\s*(\d+)\.\s+(.*?)$", re.MULTILINE),      # 12. 译文
        re.compile(r"^\s*(\d+)\)\s+(.*?)$", re.MULTILINE),      # 12) 译文
        re.compile(r"^\s*(\d+)\s+(.+?)$", re.MULTILINE),        # 12 译文
    ]

    with open(manual_file, "r", encoding="utf-8") as f:
        text = f.read()

    for pat in patterns:
        result = {}
        for m in pat.finditer(text):
            idx = int(m.group(1))
            result[idx] = m.group(2).strip()
        if result:
            return result

    return {}


def apply_manual_translation(subs: pysrt.SubRipFile, manual_file: str) -> Tuple[pysrt.SubRipFile, int, List[int]]:
    """应用人工翻译回填
    返回: (subs, applied_count, missing_indices)
    """
    manual_map = parse_manual_file(manual_file)
    applied = 0
    missing = []

    for sub in subs:
        if sub.index in manual_map:
            sub.text = manual_map[sub.index]
            applied += 1
        else:
            missing.append(sub.index)

    if missing:
        logger.warning(f"人工翻译缺失索引: {missing}")
    logger.info(f"人工回填: {applied}/{len(subs)} 条")
    return subs, applied, missing


# ── 日志 ──────────────────────────────────────────

@dataclass
class TranslationLog:
    video: str = ""
    total_groups: int = 0
    success: int = 0
    retry_success: int = 0
    single_fallback: int = 0
    manual_pending: int = 0
    details: List[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "video": self.video,
            "total_groups": self.total_groups,
            "success": self.success,
            "retry_success": self.retry_success,
            "single_fallback": self.single_fallback,
            "manual_pending": self.manual_pending,
            "details": self.details,
        }

    def write(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# ── 主翻译器 ──────────────────────────────────────

class SRTTranslator:
    def __init__(self, config_path: Optional[str] = None):
        self.config = load_config(config_path)
        self.api = create_api_client(self.config)
        self.fmt = self.config.get("output_format", "numbered_list")
        self.source_lang = self.config.get("source_lang", "auto")
        self.max_retries = self.config.get("max_retries", 2)
        self.fallback_to_single = self.config.get("fallback_to_single", True)
        self.manual_fallback = self.config.get("manual_fallback", True)
        self.rate_limiter = RateLimiter(
            rpm=self.config.get("rate_limit", {}).get("requests_per_minute", 20),
            min_interval=self.config.get("rate_limit", {}).get("min_interval_seconds", 0.5),
        )
        self.log = TranslationLog()
        # 翻译 I/O 日志：记录每次 LLM 调用的完整输入输出
        self._io_log: List[dict] = []
        self._semantic_flagged: List[dict] = []
        self._prompt_templates: dict = {}
        self._prompt_version: int = 1
        # 语义核对配置
        self.semantic_check = self.config.get("semantic_check", False)
        self.semantic_threshold = self.config.get("semantic_threshold", 0.70)
        self._verifier = None
        # 自然度 (PPL) 检查配置
        self.naturalness_check = self.config.get("quality_assessment", {}).get(
            "dimensions", {}).get("naturalness", {}).get("enabled", True)
        self.naturalness_threshold = self.config.get("quality_assessment", {}).get(
            "dimensions", {}).get("naturalness", {}).get("threshold", 3.0)
        self.joint_verification = self.config.get("joint_verification", False)
        self.verification_mode = self.config.get("verification_mode", "joint_formula")
        self.sim_drop_limit = self.config.get("sim_drop_limit", 0.05)
        self._ppl_evaluator = None
        # 并发配置
        conc_cfg = self.config.get("concurrency", {})
        self.concurrent_enabled = conc_cfg.get("enabled", False)
        self.max_workers = conc_cfg.get("max_workers", 3)
        # 线程安全锁
        self._log_lock = threading.Lock()
        self._verifier_lock = threading.Lock()
        # 术语替换配置
        term_cfg = self.config.get("terms_dict", {})
        self.term_enabled = term_cfg.get("enabled", False)
        self.term_dict_dir = term_cfg.get("dict_dir", "config/terms/")
        self.term_dict_name = term_cfg.get("default_dict", "minecraft.json")
        # 加载术语表到内存（用于按需注入 prompt），使用预缓存注入器避免 per-call 80MB 分配
        self._glossary_injector: "GlossaryInjector | None" = None
        if self.term_enabled:
            from SRT.glossary_injector import load_glossary, load_glossaries, GlossaryInjector
            if isinstance(self.term_dict_name, list):
                raw_glossary = load_glossaries(self.term_dict_dir, self.term_dict_name)
            else:
                raw_glossary = load_glossary(self.term_dict_dir, self.term_dict_name)
            self._glossary_injector = GlossaryInjector(raw_glossary) if raw_glossary else None
        # 自定义 prompt 配置
        prompt_cfg = self.config.get("custom_prompt", {})
        self.custom_prompt_enabled = prompt_cfg.get("enabled", False)
        self.custom_system_prompt = prompt_cfg.get("system_prompt", "")
        self.custom_batch_prompt = prompt_cfg.get("batch_prompt", "")
        self.custom_single_prompt = prompt_cfg.get("single_prompt", "")
        self.custom_semantic_retry_prompt = prompt_cfg.get("semantic_retry_prompt", "")
        self.custom_naturalness_retry_prompt = prompt_cfg.get("naturalness_retry_prompt", "")
        # 目标语言：优先从配置读取，否则从 source_lang 推断
        target_cfg = self.config.get("target_lang", "")
        if target_cfg and target_cfg != "auto":
            self.target_lang = _LANG_LABELS.get(target_cfg, target_cfg)
        else:
            self.target_lang = "简体中文" if self.source_lang in ("ja", "zh") else "Simplified Chinese"
        # Split-brain 配置
        sb_cfg = self.config.get("split_brain", {})
        self.split_brain_enabled = sb_cfg.get("enabled", False)
        # Multi-agent 配置
        ma_cfg = self.config.get("multi_agent", {})
        self.multi_agent_enabled = ma_cfg.get("enabled", False)

    def translate(self, srt_path: str, timeline_path: str | None = None) -> Tuple[str, str]:
        """主入口
        返回: (translated_srt_path, pending_manual_path)
        pending_manual_path 为空表示全部自动翻译成功

        timeline_path: 若提供，从 Timeline IR 读取 segments 进行翻译，
                       翻译结果回写到 segment.translation。
        """
        # ── Timeline 路径 ──
        if timeline_path and os.path.isfile(timeline_path):
            return self._translate_from_timeline(timeline_path, srt_path)

        # ── SRT 路径（现有逻辑）──
        logger.info(f"开始翻译: {srt_path}")
        subs = pysrt.open(srt_path)
        self._all_subs = subs  # 保存全局字幕列表，供上下文提取使用
        self.log.video = os.path.basename(srt_path)

        # 语言检测
        if self.source_lang == "auto":
            self.source_lang = detect_source_language(subs)
            logger.info(f"检测到源语言: {self.source_lang}")

        # 语义分组
        groups = group_semantically(
            subs,
            max_size=self.config.get("max_group_size", 8),
            max_chars=self.config.get("max_group_chars", 500),
            min_pause=self.config.get("min_pause_gap", 0.5),
        )
        self.log.total_groups = len(groups)

        pending_groups = []

        # ── 断点续传: 从 checkpoint 获取上次完成的组号 ──
        ws_dir = os.path.dirname(os.path.dirname(srt_path))
        last_batch = 0
        try:
            from pipeline.checkpoint import PipelineCheckpoint
            _ck = PipelineCheckpoint.load(ws_dir)
            last_batch = _ck.get_extra("translate", "last_batch", 0)
        except Exception:
            _ck = None

        # 选择翻译方法
        if self.multi_agent_enabled:
            translate_fn = self._translate_group_multi_agent
            logger.info("翻译模式: multi-agent (Translator→Mapper→Reviewer→Polisher)")
        elif self.split_brain_enabled:
            translate_fn = self._translate_group_split_brain
            logger.info("翻译模式: split-brain")
        else:
            translate_fn = self._translate_group_with_fallback
            logger.info("翻译模式: 传统（格式校验 + 降级链）")

        if self.concurrent_enabled:
            logger.info(f"并发翻译模式: max_workers={self.max_workers}")
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_group = {
                    executor.submit(translate_fn, gi, group): (gi, group)
                    for gi, group in enumerate(groups, 1)
                }
                for future in as_completed(future_to_group):
                    gi, group = future_to_group[future]
                    try:
                        success = future.result()
                    except Exception as e:
                        logger.error(f"组 {gi} 并发执行异常: {e}")
                        success = False
                    if not success:
                        pending_groups.append(group)
        else:
            for gi, group in enumerate(groups, 1):
                if gi <= last_batch:
                    continue
                success = translate_fn(gi, group)
                if not success:
                    pending_groups.append(group)
                # Save checkpoint every 5 groups (API calls are expensive)
                if _ck is not None and gi % 5 == 0:
                    _ck.update_extra("translate", last_batch=gi, groups_total=len(groups))
                    _ck.save()
            if _ck is not None:
                _ck.update_extra("translate", last_batch=len(groups), groups_total=len(groups))
                _ck.save()

        # 保存自动翻译结果
        base = os.path.splitext(srt_path)[0]
        auto_path = f"{base}-auto.srt"
        subs.save(auto_path, encoding="utf-8")
        logger.info(f"自动翻译结果已保存: {auto_path}")

        # 按组号排序日志（并发模式完成顺序不确定）
        self.log.details.sort(key=lambda d: d.get("group", 0))

        # 输出待人工翻译
        # 写入翻译 I/O 日志（诊断用）
        if self._io_log:
            io_path = f"{base}-translate-io-log.json"
            with open(io_path, "w", encoding="utf-8") as f:
                json.dump({
                    "video": self.log.video,
                    "model": self.config.get("model", ""),
                    "source_lang": self.source_lang,
                    "target_lang": self.target_lang,
                    "records": self._io_log,
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"翻译 I/O 日志已保存: {io_path}")

        # 写入语义校验未通过记录（人工对比用）
        if self._semantic_flagged:
            sf_path = f"{base}-translate-semantic-flagged.json"
            with open(sf_path, "w", encoding="utf-8") as f:
                json.dump({
                    "video": self.log.video,
                    "threshold": self.semantic_threshold,
                    "flagged": self._semantic_flagged,
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"语义校验标记已保存: {sf_path} ({len(self._semantic_flagged)} 条)")

        # 写入 Prompt 清单
        self._write_prompt_manifest(base)

        if pending_groups:
            pending_path = f"{base}-pending.txt"
            write_pending_file(pending_groups, pending_path)
            self.log.manual_pending = len(pending_groups)
            self.log.write(f"{base}-translate-log.json")
            return auto_path, pending_path

        # 全部成功
        self.log.write(f"{base}-translate-log.json")
        return auto_path, ""

    def _translate_from_timeline(
        self, timeline_path: str, srt_path: str
    ) -> Tuple[str, str]:
        """从 timeline.json (兼容 v1/v2) 读取 segments，翻译后回写 translation。"""
        import json as _json, pysrt, copy

        logger.info(f"开始 Timeline 翻译: {timeline_path}")
        with open(timeline_path, "r", encoding="utf-8") as f:
            tl = _json.load(f)

        is_v2 = tl.get("schema_version") == "2.0"
        source_segments = tl.get("events", []) if is_v2 else tl.get("timeline", [])
        self.log.video = (tl.get("project", {}).get("id", "")
                          if is_v2 else tl.get("audio_id", ""))

        # 构建 pysrt SubRipItem 列表
        subs = pysrt.SubRipFile()
        for seg in source_segments:
            text = (seg.get("text") if isinstance(seg, dict) else seg.text).strip()
            if not text:
                continue
            seg_id = seg.get("id") if isinstance(seg, dict) else seg.id
            seg_start = seg.get("start") if isinstance(seg, dict) else seg.start
            seg_end = seg.get("end") if isinstance(seg, dict) else seg.end
            item = pysrt.SubRipItem(
                index=int(seg_id.split("_")[1]) if "_" in seg_id else 0,
                start=pysrt.SubRipTime(seconds=seg_start),
                end=pysrt.SubRipTime(seconds=seg_end),
                text=text,
            )
            subs.append(item)
        for i, sub in enumerate(subs, 1):
            sub.index = i

        self._all_subs = subs

        if self.source_lang == "auto":
            self.source_lang = detect_source_language(subs)
            logger.info(f"检测到源语言: {self.source_lang}")

        groups = group_semantically(
            subs,
            max_size=self.config.get("max_group_size", 8),
            max_chars=self.config.get("max_group_chars", 500),
            min_pause=self.config.get("min_pause_gap", 0.5),
        )
        self.log.total_groups = len(groups)

        translate_fn = self._translate_group_with_fallback
        if self.multi_agent_enabled:
            translate_fn = self._translate_group_multi_agent
        elif self.split_brain_enabled:
            translate_fn = self._translate_group_split_brain

        for gi, group in enumerate(groups, 1):
            translate_fn(gi, group)

        # 回写 translation
        for sub in subs:
            for seg in source_segments:
                if isinstance(seg, dict):
                    idx = int(seg.get("id", "").split("_")[1]) if "_" in seg.get("id", "") else 0
                else:
                    idx = int(seg.id.split("_")[1]) if "_" in seg.id else 0
                if idx == sub.index:
                    if isinstance(seg, dict):
                        seg["translation"] = sub.text
                    else:
                        seg.translation = sub.text
                    break

        out_dir = os.path.dirname(srt_path)
        out_timeline = os.path.join(out_dir, "timeline.json")
        with open(out_timeline, "w", encoding="utf-8") as f:
            _json.dump(tl, f, ensure_ascii=False, indent=2)
        logger.info(f"Timeline 翻译已保存: {out_timeline}")

        base = os.path.splitext(srt_path)[0]
        auto_path = f"{base}-auto.srt"
        subs.save(auto_path, encoding="utf-8")
        self.log.write(f"{base}-translate-log.json")
        return auto_path, ""

    def apply_manual(self, auto_srt_path: str, manual_file: str) -> str:
        """应用人工翻译回填"""
        subs = pysrt.open(auto_srt_path)
        subs, applied, missing = apply_manual_translation(subs, manual_file)

        base = auto_srt_path.replace("-auto.srt", "")
        final_path = f"{base}-ZH_CN.srt"
        subs.save(final_path, encoding="utf-8")
        logger.info(f"人工回填完成: {final_path}")
        return final_path

    def _translate_group_multi_agent(self, group_index: int, group: List[pysrt.SubRipItem]) -> bool:
        """Multi-Agent 流水线翻译一组字幕: Translator → Mapper → Reviewer → Polisher。"""
        group_label = f"组 {group_index}/{self.log.total_groups}"
        indices = [sub.index for sub in group]
        logger.info(f"[{group_label}] Multi-Agent 翻译 (索引: {indices})")

        from SRT.translation_agents import AgentPipeline
        import tempfile

        work_dir = os.path.join(tempfile.gettempdir(), f"tragent_g{group_index}")
        term_dict_path = os.path.join(
            self.term_dict_dir, self.term_dict_name
        ) if self.term_enabled else ""

        pipeline = AgentPipeline(
            self.api, self.rate_limiter, work_dir,
            source_lang=self.source_lang,
            target_lang=self.target_lang,
            glossary_path=term_dict_path,
        )
        group_dicts = [{"index": sub.index, "text": sub.text} for sub in group]
        glossary_terms = {}
        if term_dict_path and os.path.isfile(term_dict_path):
            try:
                glossary_terms = json.loads(
                    open(term_dict_path, encoding="utf-8").read()
                ).get("terms", {})
            except Exception:
                pass

        t0 = time.time()
        try:
            mapping, mqm_report = pipeline.run_group(
                group_dicts, group_index, glossary_terms,
            )
        except Exception as e:
            logger.error(f"[{group_label}] Multi-Agent 异常: {e}")
            return self._translate_group_with_fallback(group_index, group)

        if not mapping or len(mapping) != len(group):
            logger.warning(f"[{group_label}] Multi-Agent 映射失败，回退传统模式")
            return self._translate_group_with_fallback(group_index, group)

        for sub in group:
            if sub.index in mapping:
                sub.text = mapping[sub.index]

        with self._log_lock:
            self.log.success += 1
            self.log.details.append({
                "group": group_index,
                "status": "success",
                "method": "multi_agent",
                "mqm": mqm_report.get("average_composite", 0),
                "duration": round(time.time() - t0, 2),
            })
        return True

    def _translate_group_split_brain(self, group_index: int, group: List[pysrt.SubRipItem]) -> bool:
        """Split-brain 翻译一组字幕。
        返回: 是否成功
        """
        group_label = f"组 {group_index}/{self.log.total_groups}"
        indices = [sub.index for sub in group]
        logger.info(f"[{group_label}] Split-brain 翻译 (索引: {indices})")

        sb_translator = SplitBrainTranslator(
            self.api, self.rate_limiter,
            source_lang=self.source_lang,
            target_lang=self.target_lang,
        )
        t0 = time.time()
        try:
            mapping = sb_translator.translate_group(group)
        except Exception as e:
            logger.error(f"[{group_label}] Split-brain 异常: {e}")
            return False

        if not mapping or len(mapping) != len(group):
            logger.warning(f"[{group_label}] Split-brain 失败，回退传统模式")
            return self._translate_group_with_fallback(group_index, group)

        # 回填翻译结果
        for sub in group:
            if sub.index in mapping:
                sub.text = mapping[sub.index]

        with self._log_lock:
            self.log.success += 1
            self.log.details.append({
                "group": group_index,
                "status": "success",
                "method": "split_brain",
                "duration": round(time.time() - t0, 2),
            })
        return True

    def _translate_group_with_fallback(self, group_index: int, group: List[pysrt.SubRipItem]) -> bool:
        """翻译一组字幕，带完整降级链
        返回: 是否成功
        """
        group_label = f"组 {group_index}/{self.log.total_groups}"
        indices = [sub.index for sub in group]
        logger.info(f"[{group_label}] 开始翻译 (索引: {indices})")

        # 保存原文，用于翻译后的语义核对
        originals = {sub.index: sub.text for sub in group}

        # 第1次：分组翻译
        t0 = time.time()
        success = self._try_batch_translate(group, retry=False)
        if success:
            # 语义核对 + 自动重新翻译 + 自然度检查
            similarities = {}
            if self.semantic_check:
                # Phase 1: MiniLM 语义验证
                ppl_candidates = []  # (sub, source) pairs that pass semantic check
                for sub in group:
                    source = originals.get(sub.index, "")
                    if not source:
                        continue
                    verifier = self._get_verifier()
                    sim = None
                    if verifier:
                        try:
                            r = verifier.verify(source, sub.text)
                            sim = r["similarity"]
                            similarities[sub.index] = sim
                        except Exception:
                            pass

                    if sim is not None and sim < self.semantic_threshold:
                        # < 0.70 → RefineContrast 语义重翻
                        best = self._verify_and_refine(source, sub.text, sub.index, group)
                        sub.text = best
                    elif sim is None:
                        pass  # verifier unavailable, skip
                    else:
                        # ≥ 0.70 → 候选进入 Phase 2 (PPL 自然度检查)
                        ppl_candidates.append((sub, source))

                # Phase 2: PPL 自然度检查 (MiniLM ≥ 0.70 + naturalness_check)
                ppl_data: dict = {}  # {index: {ppl, baseline, ratio}}
                if ppl_candidates and self.naturalness_check:
                    ppl_eval = self._get_ppl_evaluator()
                    if ppl_eval:
                        texts = [s.text for s, _ in ppl_candidates]
                        try:
                            ppls = ppl_eval.batch_perplexity(texts)
                            # 自适应基线：取 PPL 最低的 30% 的中位数
                            valid_ppls = [p for p in ppls if p > 0]
                            if len(valid_ppls) >= 5:
                                valid_ppls.sort()
                                baseline = valid_ppls[len(valid_ppls) // 3]
                            else:
                                baseline = min(valid_ppls) if valid_ppls else 60.0

                            for i, (sub, source) in enumerate(ppl_candidates):
                                ppl = ppls[i]
                                ppl_data[sub.index] = {
                                    "ppl": round(ppl, 1),
                                    "baseline": round(baseline, 1),
                                    "ratio": round(ppl / baseline, 2) if baseline > 0 else 0,
                                }
                                if ppl > 0 and baseline > 0 and (ppl / baseline) > self.naturalness_threshold:
                                    logger.warning(
                                        f"  ⚠ 索引 {sub.index} PPL 偏高 ({ppl:.0f}/{baseline:.0f}="
                                        f"{ppl/baseline:.1f}x)，自然度重翻..."
                                    )
                                    refined = self._refine_naturalness(
                                        source, sub.text, sub.index, group
                                    )
                                    if refined and refined != sub.text:
                                        if self.joint_verification:
                                            # 闭环验证：联合得分判断语义是否偏离
                                            old_sim = similarities.get(sub.index, 0.70)
                                            old_ratio = ppl / baseline
                                            result = self._verify_naturalness_result(
                                                source, sub.text, refined,
                                                old_sim, old_ratio, baseline,
                                            )
                                            if result["accepted"]:
                                                sub.text = refined
                                                logger.info(
                                                    f"  ✓ 索引 {sub.index}: 自然度重翻已采纳 "
                                                    f"(old={old_sim:.2f}+{old_ratio:.1f}x, "
                                                    f"new={result['new_sim']:.2f}+{result['new_ratio']:.1f}x)"
                                                )
                                            else:
                                                reason = result["reason"]
                                                if reason in ("semantic_drift", "content_degraded"):
                                                    # Tier 2 回退
                                                    pre_tier2_text = sub.text
                                                    if reason == "semantic_drift":
                                                        logger.warning(
                                                            f"  ↳ 索引 {sub.index}: 语义崩溃, 回退语义重试 (Tier 2)..."
                                                        )
                                                        # 用原始正确翻译作为比较基准，而非 Tier 1 的幻觉输出
                                                        best = self._verify_and_refine(
                                                            source, sub.text, sub.index, group
                                                        )
                                                        sub.text = best
                                                    else:
                                                        logger.warning(
                                                            f"  ↳ 索引 {sub.index}: 内容退化 "
                                                            f"({result.get('sim_drop', 0):.2f}), "
                                                            f"回退内容保全重试 (Tier 2)..."
                                                        )
                                                        best = self._refine_content_preserving(
                                                            source, refined, sub.index, group
                                                        )
                                                        if best and best != refined:
                                                            sub.text = best
                                                    # 更新 _semantic_flagged 记录
                                                    for sf in reversed(self._semantic_flagged):
                                                        if sf.get("index") == sub.index and sf.get("reason") == "naturalness_retry":
                                                            sf["reason"] = f"naturalness_retry_rejected:{reason}_fellback"
                                                            sf["kept"] = "second" if sub.text != pre_tier2_text else "first"
                                                            break
                                                else:
                                                    # Gate B 失败: 保留原译，无需重试
                                                    logger.warning(
                                                        f"  ✗ 索引 {sub.index}: 自然度重翻被驳回 "
                                                        f"({reason}), 保留原译"
                                                    )
                                        else:
                                            sub.text = refined
                        except Exception as e:
                            logger.warning(f"PPL 批量推理失败: {e}")
            with self._log_lock:
                self.log.success += 1
                detail = {
                    "group": group_index,
                    "status": "success",
                    "method": "batch",
                    "duration": round(time.time() - t0, 2),
                    "indices": indices,
                }
                if similarities:
                    detail["similarities"] = similarities
                if ppl_data:
                    detail["ppls"] = ppl_data
                self.log.details.append(detail)
            return True

        # 第2次：重试（加粗警告）
        if self.max_retries >= 1:
            logger.warning(f"[{group_label}] 首次失败，尝试重试...")
            t0 = time.time()
            success = self._try_batch_translate(group, retry=True)
            if success:
                with self._log_lock:
                    self.log.retry_success += 1
                    self.log.details.append({
                        "group": group_index,
                        "status": "retry_success",
                        "method": "batch",
                        "duration": round(time.time() - t0, 2),
                        "indices": indices,
                    })
                return True

        # 第3次：逐条降级
        if self.fallback_to_single:
            logger.warning(f"[{group_label}] 重试失败，降级逐条翻译...")
            t0 = time.time()
            success = self._try_single_translate(group)
            if success:
                with self._log_lock:
                    self.log.single_fallback += 1
                    self.log.details.append({
                        "group": group_index,
                        "status": "single_fallback",
                        "method": "single",
                        "duration": round(time.time() - t0, 2),
                        "indices": indices,
                    })
                return True

        # 最终：人工兜底
        if self.manual_fallback:
            logger.warning(f"[{group_label}] 自动翻译全部失败，标记人工翻译")
            with self._log_lock:
                self.log.details.append({
                    "group": group_index,
                    "status": "manual",
                    "reason": "format_mismatch_after_all_attempts",
                    "indices": indices,
                })
            return False

        return False

    def _try_batch_translate(self, group: List[pysrt.SubRipItem], retry: bool = False) -> bool:
        """尝试分组翻译
        成功则回填并返回 True
        """
        system = build_system_prompt(
            self.source_lang, self.fmt, retry=retry,
            custom_template=self.custom_system_prompt if self.custom_prompt_enabled else None,
            target_lang=self.target_lang,
        )
        prompt = build_batch_prompt(
            group, self.fmt,
            custom_template=self.custom_batch_prompt if self.custom_prompt_enabled else None,
            source_lang=self.source_lang, target_lang=self.target_lang,
        )

        # 术语表按需注入：只注入源文本中实际出现的术语
        if self._glossary_injector:
            src_texts = [sub.text for sub in group]
            gloss_str, matched = self._glossary_injector.collect_for_group(src_texts)
            if gloss_str:
                prompt = gloss_str + "\n\n" + prompt

        t0 = time.time()
        try:
            self.rate_limiter.acquire()
            raw = self.api.translate(prompt, system_prompt=system)
            elapsed = time.time() - t0
            success, mapping, reason = validate_format(group, raw, self.fmt)

            # 记录翻译 I/O 日志
            self._io_log.append({
                "type": "batch",
                "group_indices": [sub.index for sub in group],
                "retry": retry,
                "prompt_step": "retry" if retry else "batch",
                "prompt_hash": _prompt_hash(system, prompt),
                "input": {
                    "system_prompt": system,
                    "user_prompt": prompt,
                    "source_texts": {sub.index: sub.text for sub in group},
                },
                "output": {
                    "raw": raw,
                    "parsed": mapping if success else {},
                    "validation_error": "" if success else reason,
                },
                "duration": round(elapsed, 2),
                "timestamp": datetime.now().isoformat(),
            })

            if success:
                for sub in group:
                    sub.text = mapping[sub.index]
                return True
            else:
                logger.warning(f"格式校验失败: {reason}")
                return False
        except Exception as e:
            logger.error(f"API 调用异常: {e}")
            return False

    def _try_single_translate(self, group: List[pysrt.SubRipItem]) -> bool:
        """逐条翻译降级
        每条单独调用，保留前后上下文
        """
        all_subs = list(group[0].__class__.__init__.__self__) if hasattr(group[0], "_file") else []
        # 实际上无法从 SubRipItem 获取完整列表，需要外部传入
        # 这里简化处理：假设 group 中的字幕 index 是连续的
        success_count = 0

        for i, sub in enumerate(group):
            # 获取前后上下文（从 group 内取）
            prev_subs = group[max(0, i - 2) : i]
            next_subs = group[i + 1 : min(len(group), i + 3)]

            system, prompt = build_single_prompt(
                sub, prev_subs, next_subs, self.source_lang,
                custom_template=self.custom_single_prompt if self.custom_prompt_enabled else None,
                target_lang=self.target_lang,
            )

            try:
                self.rate_limiter.acquire()
                t0 = time.time()
                raw = self.api.translate(prompt, system_prompt=system)
                elapsed = time.time() - t0
                translated = raw.strip().strip('"').strip("'")

                # 记录翻译 I/O 日志
                self._io_log.append({
                    "type": "single",
                    "group_indices": [sub.index],
                    "prompt_step": "single",
                    "prompt_hash": _prompt_hash(system, prompt),
                    "input": {
                        "system_prompt": system,
                        "user_prompt": prompt,
                        "source_text": sub.text,
                    },
                    "output": {
                        "raw": raw,
                        "parsed": {sub.index: translated} if translated else {},
                        "empty": not bool(translated),
                    },
                    "duration": round(elapsed, 2),
                    "timestamp": datetime.now().isoformat(),
                })

                if translated:
                    sub.text = translated
                    success_count += 1
                else:
                    logger.warning(f"逐条翻译返回空: 索引 {sub.index}")
            except Exception as e:
                logger.error(f"逐条翻译异常 (索引 {sub.index}): {e}")

        return success_count == len(group)

    def _get_verifier(self):
        """延迟加载语义核验器（双检锁，防止并发重复加载 470MB 模型）"""
        if self._verifier is None and self.semantic_check:
            with self._verifier_lock:
                if self._verifier is None and self.semantic_check:
                    try:
                        VerifierCls = _lazy_import_verifier()
                        self._verifier = VerifierCls(
                            threshold=self.semantic_threshold,
                        )
                    except Exception as e:
                        logger.warning(f"语义核验器加载失败，已跳过: {e}")
                        self._verifier = False  # 标记失败，不再重试
        return self._verifier if self._verifier else None

    def _get_ppl_evaluator(self):
        """延迟加载 PPL 评估器"""
        if self._ppl_evaluator is None and self.naturalness_check:
            try:
                from pipeline.ppl_evaluator import PPLEvaluator
                self._ppl_evaluator = PPLEvaluator()
            except Exception as e:
                logger.warning(f"PPLEvaluator 加载失败: {e}")
                self._ppl_evaluator = False
        return self._ppl_evaluator if self._ppl_evaluator else None

    def _get_lang_labels(self) -> tuple:
        """返回 (源语言标签, 目标语言标签) 用于 prompt 构建"""
        src = _LANG_LABELS.get(self.source_lang, self.source_lang)
        tgt = _LANG_LABELS.get(self.target_lang, self.target_lang)
        return src, tgt

    def _verify_and_refine(self, source_text: str, translated_text: str,
                           sub_index: int, group: List) -> str:
        """
        语义核对 + RefineContrast 重新翻译 (MiniLM < threshold)

        用旧译文做对比锚点，引导 LLM 生成不同的表达。
        """
        verifier = self._get_verifier()
        if verifier is None:
            return translated_text

        try:
            result = verifier.verify(source_text, translated_text)
            if not result["flagged"]:
                return translated_text

            flagged_sim = result["similarity"]
            logger.warning(f"  ⚠ 索引 {sub_index} 语义相似度低 ({flagged_sim:.2f})，RefineContrast 重翻...")

            src_label, tgt_label = self._get_lang_labels()

            # 获取上下文
            prev_subs, next_subs = self._get_context_subs(sub_index, group)
            context_parts = []
            if prev_subs:
                ctx = " ".join(s.text.strip() for s in prev_subs if s.text.strip())
                if ctx:
                    context_parts.append(f"前文：{ctx}")
            if next_subs:
                ctx = " ".join(s.text.strip() for s in next_subs if s.text.strip())
                if ctx:
                    context_parts.append(f"下文：{ctx}")

            # RefineContrast: 使用自定义 prompt 或系统默认
            if self.custom_prompt_enabled and self.custom_semantic_retry_prompt:
                system_msg = self.custom_semantic_retry_prompt.replace(
                    "{source_lang}", src_label
                ).replace("{target_lang}", tgt_label)
            else:
                system_msg = (
                    f"你是专业翻译。请将以下{src_label}字幕翻译成{tgt_label}。"
                    "请结合上下文理解原文含义，用自然流畅的语言准确表达。"
                    "输出只有译文本身，不要添加任何说明。"
                )
            prompt_parts = list(context_parts)
            prompt_parts.append("")
            prompt_parts.append(f"原文：{source_text}")
            prompt_parts.append(f"旧译文（请避免）：{translated_text}")
            prompt_parts.append(f"新译文：")
            prompt = "\n".join(prompt_parts)

            if self._glossary_injector:
                gloss_str, matched = self._glossary_injector.collect_for_group([source_text])
                if gloss_str:
                    prompt = gloss_str + "\n\n" + prompt

            self.rate_limiter.acquire()
            t0 = time.time()
            raw = self.api.translate(prompt, system_prompt=system_msg)
            elapsed = time.time() - t0
            new_translation = raw.strip().strip('"').strip("'")

            # 记录重翻 I/O 日志
            self._io_log.append({
                "type": "semantic_retry",
                "group_indices": [sub_index],
                "prompt_step": "semantic_retry",
                "prompt_hash": _prompt_hash(system_msg, prompt),
                "input": {
                    "system_prompt": system_msg,
                    "user_prompt": prompt,
                    "source_text": source_text,
                },
                "output": {"raw": raw, "parsed": {sub_index: new_translation} if new_translation else {}},
                "duration": round(elapsed, 2),
                "timestamp": datetime.now().isoformat(),
            })

            if not new_translation:
                self._semantic_flagged.append({
                    "index": sub_index,
                    "source": source_text,
                    "translated": translated_text,
                    "similarity": flagged_sim,
                    "retried": True,
                    "new_translated": "",
                    "new_similarity": None,
                    "kept": "first",
                    "reason": "re-translation returned empty",
                })
                return translated_text

            # 对比两版相似度
            new_sim = verifier.verify(source_text, new_translation)["similarity"]

            if new_sim > flagged_sim:
                improvement = new_sim - flagged_sim
                logger.warning(f"  ✓ 索引 {sub_index}: 重新翻译改善 "
                              f"({flagged_sim:.2f}→{new_sim:.2f}, +{improvement:.2f})")
                if new_sim < self.semantic_threshold:
                    logger.warning(f"  ⚠ 索引 {sub_index}: 两次均低于阈值，建议人工复核")
                self._semantic_flagged.append({
                    "index": sub_index,
                    "source": source_text,
                    "translated": translated_text,
                    "similarity": flagged_sim,
                    "retried": True,
                    "new_translated": new_translation,
                    "new_similarity": new_sim,
                    "kept": "second",
                    "improvement": round(improvement, 4),
                })
                return new_translation
            else:
                logger.warning(f"  - 索引 {sub_index}: 重新翻译未改善 "
                              f"({flagged_sim:.2f}→{new_sim:.2f})，保留原译")
                if flagged_sim < self.semantic_threshold:
                    logger.warning(f"  ⚠ 索引 {sub_index}: 两次均低于阈值，建议人工复核")
                self._semantic_flagged.append({
                    "index": sub_index,
                    "source": source_text,
                    "translated": translated_text,
                    "similarity": flagged_sim,
                    "retried": True,
                    "new_translated": new_translation,
                    "new_similarity": new_sim,
                    "kept": "first",
                    "improvement": round(new_sim - flagged_sim, 4),
                })
                return translated_text

        except Exception as e:
            logger.warning(f"  语义核对异常 (索引 {sub_index}): {e}")
            return translated_text

    def _write_prompt_manifest(self, base: str):
        """Write prompt_manifest.json for prompt chain visualization."""
        manifest = {
            "version": self._prompt_version,
            "generated_at": datetime.now().isoformat(),
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "templates": {},
            "config_snapshot": {
                "semantic_threshold": self.semantic_threshold,
                "temperature": self.config.get("temperature", 0.1),
                "model": self.config.get("model", ""),
                "custom_prompt_enabled": self.custom_prompt_enabled,
            },
        }
        for h, tpl in self._prompt_templates.items():
            manifest["templates"][h] = tpl
        manifest_path = f"{base}-prompt-manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        logger.info(f"Prompt 清单已保存: {manifest_path}")

    def _refine_naturalness(self, source_text: str, translated_text: str,
                            sub_index: int, group: List,
                            preserve_content: bool = False) -> Optional[str]:
        """
        自然度重翻 (PPL 偏高 → RefineContrast 自然中文)

        与语义重翻不同：这里侧重用更地道的目标语言重新表达，而非纠正语义错误。

        preserve_content=True: 强调保持原文完整信息量，用于 Gate C 失败后的 Tier 2 回退
        """
        src_label, tgt_label = self._get_lang_labels()
        prev_subs, next_subs = self._get_context_subs(sub_index, group)

        context_parts = []
        if prev_subs:
            ctx = " ".join(s.text.strip() for s in prev_subs if s.text.strip())
            if ctx:
                context_parts.append(f"前文：{ctx}")
        if next_subs:
            ctx = " ".join(s.text.strip() for s in next_subs if s.text.strip())
            if ctx:
                context_parts.append(f"下文：{ctx}")

        if self.custom_prompt_enabled and self.custom_naturalness_retry_prompt:
            system_msg = self.custom_naturalness_retry_prompt.replace(
                "{source_lang}", src_label
            ).replace("{target_lang}", tgt_label)
        elif preserve_content:
            system_msg = (
                f"你是专业翻译。请将以下{src_label}字幕重新翻译成更自然、更地道的{tgt_label}。"
                "严格保持原文的完整信息量——不要增删任何内容要点，不要省略或添加信息。"
                "用日常交流的口吻表达，避免翻译腔（直译/逐字翻译）。"
                "输出只有译文本身，不要添加任何说明。"
            )
        else:
            system_msg = (
                f"你是专业翻译。请将以下{src_label}字幕重新翻译成更自然、更地道的{tgt_label}。"
                "用日常交流的口吻表达，避免翻译腔（直译/逐字翻译）。"
                "输出只有译文本身，不要添加任何说明。"
            )
        prompt_parts = list(context_parts)
        prompt_parts.append("")
        prompt_parts.append(f"原文：{source_text}")
        prompt_parts.append(f"旧译文（请避免）：{translated_text}")
        prompt_parts.append(f"新译文：")
        prompt = "\n".join(prompt_parts)

        if self._glossary_injector:
            gloss_str, matched = self._glossary_injector.collect_for_group([source_text])
            if gloss_str:
                prompt = gloss_str + "\n\n" + prompt

        try:
            self.rate_limiter.acquire()
            t0 = time.time()
            raw = self.api.translate(prompt, system_prompt=system_msg)
            elapsed = time.time() - t0
            refined = raw.strip().strip('"').strip("'")

            self._io_log.append({
                "type": "naturalness_retry",
                "group_indices": [sub_index],
                "prompt_step": "naturalness_retry",
                "prompt_hash": _prompt_hash(system_msg, prompt),
                "input": {
                    "system_prompt": system_msg,
                    "user_prompt": prompt,
                    "source_text": source_text,
                },
                "output": {"raw": raw, "parsed": {sub_index: refined} if refined else {}},
                "duration": round(elapsed, 2),
                "timestamp": datetime.now().isoformat(),
            })

            if refined:
                self._semantic_flagged.append({
                    "index": sub_index,
                    "source": source_text,
                    "translated": translated_text,
                    "similarity": None,
                    "retried": True,
                    "new_translated": refined,
                    "new_similarity": None,
                    "kept": "second",
                    "improvement": 0,
                    "reason": "naturalness_retry",
                })
            return refined
        except Exception as e:
            logger.warning(f"  自然度重翻异常 (索引 {sub_index}): {e}")
            return None

    def _refine_content_preserving(self, source_text: str, translated_text: str,
                                   sub_index: int, group: List) -> Optional[str]:
        """内容保全重试 — Gate C 失败后的 Tier 2 回退。

        与 _refine_naturalness 相同，但强调保持原文完整信息量。
        """
        return self._refine_naturalness(source_text, translated_text,
                                        sub_index, group, preserve_content=True)

    def _verify_naturalness_result(self, source: str, old_text: str,
                                   refined: str, old_sim: float,
                                   old_ratio: float, baseline: float) -> dict:
        """闭环验证：委托到 core/ TextGate.decide()。(批次05 §五)

        Returns: {accepted: bool, kept: str, reason: str, new_sim, new_ratio, ...}
        """
        from core.gates.text_gate import TextGate

        verifier = self._get_verifier()
        if not verifier:
            return {"accepted": True, "kept": "second", "reason": "verifier_unavailable",
                    "new_sim": old_sim, "new_ratio": old_ratio}

        new_sim = verifier.verify(source, refined)["similarity"]

        ppl_eval = self._get_ppl_evaluator()
        if ppl_eval:
            try:
                new_ppl = ppl_eval.perplexity(refined)
            except Exception:
                new_ppl = old_ratio * baseline if baseline > 0 else old_ratio
        else:
            new_ppl = old_ratio * baseline if baseline > 0 else old_ratio
        new_ratio = new_ppl / baseline if baseline > 0 else 1.0

        mode = getattr(self, "verification_mode", "joint_formula")
        sim_drop = getattr(self, "sim_drop_limit", 0.05)
        sem_threshold = getattr(self, "semantic_threshold", 0.70)

        gate = TextGate(
            mode=mode,
            semantic_threshold=sem_threshold,
            sim_drop_limit=sim_drop,
        )
        result = gate.decide(
            old_sim, new_sim, old_ratio, new_ratio,
            source_len=len(source), old_len=len(old_text), new_len=len(refined),
        )

        kept = "first"
        if result.accepted:
            kept = "second"
        elif result.kept_version == "retry":
            kept = "second" if result.accepted else "first"

        return {
            "accepted": result.accepted,
            "kept": kept,
            "reason": result.reason,
            "new_sim": new_sim,
            "new_ratio": new_ratio,
            "improvement": round(old_ratio - new_ratio, 4) if new_ratio < old_ratio else 0,
        }

    def _get_context_subs(self, sub_index: int, group: List) -> Tuple[List, List]:
        """获取某条字幕的上下文（前后各最多 2 条）"""
        all_subs = getattr(self, "_all_subs", None)
        if all_subs is not None:
            idx = next((i for i, s in enumerate(all_subs) if s.index == sub_index), -1)
            if idx >= 0:
                prev = all_subs[max(0, idx-2):idx]
                next_ = all_subs[idx+1:min(len(all_subs), idx+3)]
                return prev, next_

        # 从 group 内取上下文
        for i, sub in enumerate(group):
            if sub.index == sub_index:
                return group[max(0, i-2):i], group[i+1:min(len(group), i+3)]
        return [], []


# ── 便捷函数 ──────────────────────────────────────

def translate_srt(srt_path: str, config_path: Optional[str] = None) -> Tuple[str, str]:
    """一键翻译 SRT 文件"""
    translator = SRTTranslator(config_path)
    return translator.translate(srt_path)


if __name__ == "__main__":
    import argparse

    # 确保项目根目录在 sys.path 中，供语义核验器等模块导入
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_script_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    parser = argparse.ArgumentParser(description="字幕自动翻译")
    parser.add_argument("srt", help="输入 SRT 文件路径")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--manual", default=None, help="人工翻译文件路径（用于回填）")
    args = parser.parse_args()

    translator = SRTTranslator(args.config)

    if args.manual:
        # 回填模式
        auto_path = f"{os.path.splitext(args.srt)[0]}-auto.srt"
        final_path = translator.apply_manual(auto_path, args.manual)
        print(f"人工回填完成: {final_path}")
    else:
        # 翻译模式
        auto_path, pending = translator.translate(args.srt)
        if pending:
            print(f"\n⚠️ 有 {translator.log.manual_pending} 组需人工翻译")
            print(f"待翻文件: {pending}")
            print("请完成人工翻译后运行: python SRT_Translator.py <srt> --manual <pending>")
        else:
            try:
                print(f"\n✅ 全部自动翻译完成: {auto_path}")
            except UnicodeEncodeError:
                # Windows GBK 终端不支持 emoji，兜底
                print(f"\n全部自动翻译完成: {auto_path}")
