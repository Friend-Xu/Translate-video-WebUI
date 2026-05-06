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

import os
import sys
import re
import json
import time
import logging
import threading
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
    def __init__(self, api_key: str, model: str = "deepseek-chat", **kwargs):
        if not api_key:
            raise ValueError("DeepSeek API key 未配置")
        self.api_key = api_key
        self.model = model
        self.temperature = kwargs.get("temperature", 0.1)
        self.max_tokens = kwargs.get("max_tokens", 4000)
        self.top_p = kwargs.get("top_p", 0.9)
        self.timeout = kwargs.get("timeout", 60)
        self.url = "https://api.deepseek.com/v1/chat/completions"

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

        try:
            resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.RequestException as e:
            logger.error(f"DeepSeek API 请求失败: {e}")
            raise
        except (KeyError, IndexError) as e:
            logger.error(f"DeepSeek API 响应解析失败: {e}")
            raise


def create_api_client(config: dict) -> TranslationAPI:
    api_type = config.get("api_type", "deepseek")
    if api_type == "deepseek":
        return DeepSeekAPI(
            api_key=config.get("api_key", ""),
            model=config.get("model", "deepseek-chat"),
            temperature=config.get("temperature", 0.1),
            max_tokens=config.get("max_tokens", 4000),
            top_p=config.get("top_p", 0.9),
            timeout=config.get("timeout", 60),
        )
    raise NotImplementedError(f"API 类型 '{api_type}' 尚未实现")


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

def detect_source_language(subs: pysrt.SubRipFile, sample_size: int = 20) -> str:
    sample = " ".join(sub.text for sub in subs[:sample_size])
    ja_chars = re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", sample)
    en_chars = re.findall(r"[a-zA-Z]", sample)
    if len(ja_chars) > len(en_chars) * 2:
        return "ja"
    return "en"


# ── Prompt 构建 ───────────────────────────────────

def build_system_prompt(source_lang: str, fmt: str = "numbered_list", retry: bool = False) -> str:
    if source_lang == "ja":
        base = "你是专业日语字幕翻译。请将以下日语逐条翻译成简体中文。"
    else:
        base = "你是专业英语字幕翻译。请将以下英文逐条翻译成简体中文。"

    if fmt == "json":
        fmt_rules = (
            "输出格式必须为 JSON 对象: {\"1\":\"译文1\",\"2\":\"译文2\",...}\n"
            "键必须与原编号完全一致\n"
            "不要添加任何额外字段或说明\n"
            "只返回 JSON，不要 markdown 代码块"
        )
        example_in = '{"1":"Hello everyone","2":"welcome back","3":"today we have something exciting"}'
        example_out = '{"1":"大家好","2":"欢迎回来","3":"今天我们有个激动人心的消息"}'
    else:
        fmt_rules = (
            "输出格式必须严格为 <index> 译文（如 <1> 大家好）\n"
            "编号数量和顺序必须与输入完全一致\n"
            "每条独立成行，不要合并\n"
            "不要添加任何额外说明或标注"
        )
        example_in = "<1> Hello everyone\n<2> welcome back\n<3> today we have something exciting"
        example_out = "<1> 大家好\n<2> 欢迎回来\n<3> 今天我们有个激动人心的消息"

    parts = [
        base,
        "要求：",
        "1. 保持口语化风格，上下文连贯",
        "2. " + fmt_rules,
    ]

    if not retry:
        parts.extend([
            "",
            "示例输入：",
            example_in,
            "",
            "示例输出：",
            example_out,
        ])
    else:
        parts.extend([
            "",
            "⚠️ 警告：上次翻译输出格式错误，请严格遵守上述格式要求！",
            "",
            "示例：",
            example_out,
        ])

    return "\n".join(parts)


def build_batch_prompt(group: List[pysrt.SubRipItem], fmt: str = "numbered_list") -> str:
    if fmt == "json":
        items = {str(sub.index): sub.text for sub in group}
        body = json.dumps(items, ensure_ascii=False)
    else:
        lines = [f"<{sub.index}> {sub.text}" for sub in group]
        body = "\n".join(lines)

    return f"待翻译：\n{body}\n\n翻译："


def build_single_prompt(subtitle: pysrt.SubRipItem, prev_subs: List[pysrt.SubRipItem], next_subs: List[pysrt.SubRipItem], source_lang: str) -> Tuple[str, str]:
    """逐条翻译 prompt，返回 (system_prompt, user_prompt)"""
    if source_lang == "ja":
        system = "你是专业日语字幕翻译。请将提供的句子翻译成简体中文。只输出译文，不要解释，不要加引号。"
    else:
        system = "You are a professional English subtitle translator. Translate the provided sentence into Simplified Chinese. Output only the translation, no explanations, no quotes."

    ctx_parts = []
    for s in prev_subs[-2:]:
        ctx_parts.append(f"前文: {s.text}")
    ctx_parts.append(f"当前: {subtitle.text}")
    for s in next_subs[:2]:
        ctx_parts.append(f"后文: {s.text}")

    user = "\n".join(ctx_parts) + "\n\n请只翻译「当前」这句话，直接输出译文："
    return system, user


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
        # 语义核对配置
        self.semantic_check = self.config.get("semantic_check", False)
        self.semantic_threshold = self.config.get("semantic_threshold", 0.65)
        self._verifier = None
        # 并发配置
        conc_cfg = self.config.get("concurrency", {})
        self.concurrent_enabled = conc_cfg.get("enabled", False)
        self.max_workers = conc_cfg.get("max_workers", 3)
        # 线程安全锁
        self._log_lock = threading.Lock()
        # 术语替换配置
        term_cfg = self.config.get("terms_dict", {})
        self.term_enabled = term_cfg.get("enabled", False)
        self.term_dict_dir = term_cfg.get("dict_dir", "config/terms/")
        self.term_dict_name = term_cfg.get("default_dict", "minecraft.json")

    def translate(self, srt_path: str) -> Tuple[str, str]:
        """主入口
        返回: (translated_srt_path, pending_manual_path)
        pending_manual_path 为空表示全部自动翻译成功
        """
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

        if self.concurrent_enabled:
            logger.info(f"并发翻译模式: max_workers={self.max_workers}")
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_group = {
                    executor.submit(self._translate_group_with_fallback, gi, group): (gi, group)
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
                success = self._translate_group_with_fallback(gi, group)
                if not success:
                    pending_groups.append(group)

        # 保存自动翻译结果
        base = os.path.splitext(srt_path)[0]
        auto_path = f"{base}-auto.srt"
        subs.save(auto_path, encoding="utf-8")
        logger.info(f"自动翻译结果已保存: {auto_path}")

        # 术语替换（配置中 enabled=true 时生效）
        if self.term_enabled:
            try:
                replace_terms_fn = _lazy_import_term_replacer()
                replaced = replace_terms_fn(
                    auto_path,
                    dict_dir=self.term_dict_dir,
                    dict_name=self.term_dict_name,
                )
                logger.info(f"术语替换完成: {replaced}")
            except Exception as e:
                logger.warning(f"术语替换失败，已跳过: {e}")

        # 按组号排序日志（并发模式完成顺序不确定）
        self.log.details.sort(key=lambda d: d.get("group", 0))

        # 输出待人工翻译
        if pending_groups:
            pending_path = f"{base}-pending.txt"
            write_pending_file(pending_groups, pending_path)
            self.log.manual_pending = len(pending_groups)
            self.log.write(f"{base}-translate-log.json")
            return auto_path, pending_path

        # 全部成功
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
            with self._log_lock:
                self.log.success += 1
                self.log.details.append({
                    "group": group_index,
                    "status": "success",
                    "method": "batch",
                    "duration": round(time.time() - t0, 2),
                })
            # 语义核对 + 自动重新翻译（目前仅日语生效）
            if self.semantic_check and self.source_lang == "ja":
                for sub in group:
                    source = originals.get(sub.index, "")
                    if source:
                        best = self._verify_and_refine(
                            source, sub.text, sub.index, group
                        )
                        sub.text = best
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
                })
            return False

        return False

    def _try_batch_translate(self, group: List[pysrt.SubRipItem], retry: bool = False) -> bool:
        """尝试分组翻译
        成功则回填并返回 True
        """
        system = build_system_prompt(self.source_lang, self.fmt, retry=retry)
        prompt = build_batch_prompt(group, self.fmt)

        try:
            self.rate_limiter.acquire()
            raw = self.api.translate(prompt, system_prompt=system)
            success, mapping, reason = validate_format(group, raw, self.fmt)

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

            system, prompt = build_single_prompt(sub, prev_subs, next_subs, self.source_lang)

            try:
                self.rate_limiter.acquire()
                raw = self.api.translate(prompt, system_prompt=system)
                translated = raw.strip().strip('"').strip("'")

                if translated:
                    sub.text = translated
                    success_count += 1
                else:
                    logger.warning(f"逐条翻译返回空: 索引 {sub.index}")
            except Exception as e:
                logger.error(f"逐条翻译异常 (索引 {sub.index}): {e}")

        return success_count == len(group)

    def _get_verifier(self):
        """延迟加载语义核验器"""
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

    def _verify_and_refine(self, source_text: str, translated_text: str,
                           sub_index: int, group: List) -> str:
        """
        语义核对 + 自动重新翻译
        
        当一条翻译被标记为低质时，自动用上下文重新翻译并比较两版质量。
        返回相似度更高的版本。
        """
        verifier = self._get_verifier()
        if verifier is None:
            return translated_text

        try:
            result = verifier.verify(source_text, translated_text)
            if not result["flagged"]:
                return translated_text  # 质量不错，不折腾

            flagged_sim = result["similarity"]
            logger.warning(f"  ⚠ 索引 {sub_index} 疑似低质 (相似度: {flagged_sim:.2f})，尝试重新翻译...")

            # 获取上下文相邻字幕
            prev_subs, next_subs = self._get_context_subs(sub_index, group)

            # 构建上下文，作为 system 信息注入
            context_parts = []
            if prev_subs:
                ctx = " ".join(s.text.strip() for s in prev_subs if s.text.strip())
                if ctx:
                    context_parts.append(f"前文：{ctx}")
            if next_subs:
                ctx = " ".join(s.text.strip() for s in next_subs if s.text.strip())
                if ctx:
                    context_parts.append(f"下文：{ctx}")

            # 构建重翻 prompt（单条，含原文和上下文）
            system_msg = (
                "你是专业翻译。请将以下日语字幕翻译成简体中文。"
                "注意：这不是逐句工作，要结合上下文准确理解含义。"
                "输出只有译文本身，不要添加任何说明。"
            )
            prompt_parts = list(context_parts)  # 加入上下文
            prompt_parts.append(f"")
            prompt_parts.append(f"原文：{source_text}")
            prompt_parts.append(f"译文：")
            prompt = "\n".join(prompt_parts)

            # 调用 API
            self.rate_limiter.acquire()
            raw = self.api.translate(prompt, system_prompt=system_msg)
            new_translation = raw.strip().strip('"').strip("'")

            if not new_translation:
                logger.warning(f"  索引 {sub_index}: 重新翻译返回空，保留原译")
                return translated_text

            # 对比两版相似度
            new_sim = verifier.verify(source_text, new_translation)["similarity"]

            if new_sim > flagged_sim:
                improvement = new_sim - flagged_sim
                logger.warning(f"  ✓ 索引 {sub_index}: 重新翻译改善 "
                              f"({flagged_sim:.2f}→{new_sim:.2f}, +{improvement:.2f})")
                if new_sim < self.semantic_threshold:
                    logger.warning(f"  ⚠ 索引 {sub_index}: 两次均低于阈值，建议人工复核")
                return new_translation
            else:
                logger.warning(f"  - 索引 {sub_index}: 重新翻译未改善 "
                              f"({flagged_sim:.2f}→{new_sim:.2f})，保留原译")
                if flagged_sim < self.semantic_threshold:
                    logger.warning(f"  ⚠ 索引 {sub_index}: 两次均低于阈值，建议人工复核")
                return translated_text

        except Exception as e:
            logger.warning(f"  语义核对异常 (索引 {sub_index}): {e}")
            return translated_text

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
