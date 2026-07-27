"""
translation_llm — 逐句 LLM 翻译客户端 (翻译引擎重构 Step 1)

零 core 依赖 (单向依赖: core → pipeline)。DeepSeek V4 Flash + json_object 模式。

设计要点:
  - response_format=json_object: DeepSeek 官方保证语法级合法 JSON;
    prompt 必须含 "json" 字样, schema 级校验 ({dst} 非空) 由本模块完成。
  - 前缀缓存: system prompt 跨调用字节一致时命中 context caching (~1/10 价)。
    命中率经 usage.prompt_cache_hit_tokens 计量并记日志 ——
    缓存只是成本优化, 绝不是正确性依赖。
  - 禁止兜底: 无 API key / 重试耗尽 → TranslationError 响亮抛出,
    由调用方 (pass) 转为 review flag, 绝不静默 mock。
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class TranslationError(RuntimeError):
    """翻译调用彻底失败 (重试耗尽 / 配置缺失) — 响亮抛出, 禁止静默。"""


def load_translate_config(config_path: str | None = None) -> dict:
    """读取 config/translate.yaml 的 translate 节; 文件缺失返回空 dict。"""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "translate.yaml",
        )
    if not os.path.isfile(config_path):
        return {}
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("translate", cfg) if isinstance(cfg, dict) else {}


def _extract_json_obj(raw: str) -> dict:
    """提取任意 JSON 对象; 失败抛 TranslationError 供重试。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_BLOCK_RE.search(raw)
        if not m:
            raise TranslationError(f"输出无 JSON 对象: {raw[:200]!r}")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise TranslationError(f"JSON 解析失败: {e}; {raw[:200]!r}") from e
    if not isinstance(data, dict):
        raise TranslationError(f"输出非 JSON 对象: {raw[:200]!r}")
    return data


def _extract_dst(raw: str) -> str:
    """从 LLM 输出提取 {"dst": ...}; 语法错误抛 TranslationError 供重试。"""
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_BLOCK_RE.search(raw)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        raise TranslationError(f"输出非 JSON 对象: {raw[:200]!r}")
    dst = data.get("dst", "")
    if not isinstance(dst, str) or not dst.strip():
        raise TranslationError(f"dst 缺失或为空: {raw[:200]!r}")
    return dst.strip()


class SentenceTranslator:
    """逐句翻译客户端 — translate(user, system) -> dst_text。"""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = 0.2,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        if not api_key:
            raise TranslationError(
                "未配置翻译 API key (config/translate.yaml 的 translate.api_key "
                "或环境变量 DEEPSEEK_API_KEY)"
            )
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._api_key = api_key

    @classmethod
    def from_config(cls, config_path: str | None = None) -> "SentenceTranslator":
        cfg = load_translate_config(config_path)
        api_key = cfg.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        return cls(
            api_key=api_key,
            model=cfg.get("model", DEFAULT_MODEL),
            base_url=cfg.get("api_base_url", "") or DEFAULT_BASE_URL,
            temperature=float(cfg.get("temperature", 0.2)),
            timeout=float(cfg.get("timeout", 120)),
            max_retries=int(cfg.get("max_retries", 2)),
        )

    def translate(self, user: str, system: str) -> str:
        """逐句翻译。重试耗尽抛 TranslationError。"""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                raw, usage = self._call(user, system)
                dst = _extract_dst(raw)
                self._log_usage(usage)
                return dst
            except TranslationError as e:
                last_error = e
                logger.warning("翻译第 %d 次尝试失败: %s", attempt + 1, e)
        raise TranslationError(
            f"重试 {self.max_retries} 次后仍失败: {last_error}"
        ) from last_error

    def call_json(self, user: str, system: str = "You output strict JSON only.") -> dict:
        """通用 JSON 调用 (预处理等场景) — 返回解析后的 dict, 重试耗尽抛错。"""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                raw, usage = self._call(user, system)
                data = _extract_json_obj(raw)
                self._log_usage(usage)
                return data
            except TranslationError as e:
                last_error = e
                logger.warning("JSON 调用第 %d 次尝试失败: %s", attempt + 1, e)
        raise TranslationError(
            f"重试 {self.max_retries} 次后仍失败: {last_error}"
        ) from last_error

    def _call(self, user: str, system: str) -> tuple[str, dict]:
        import requests
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            # json_object: 语法级合法 JSON; system prompt 须含 "json" 字样
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except Exception as e:
            raise TranslationError(f"API 调用失败: {type(e).__name__}: {e}") from e
        body = resp.json()
        try:
            content = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise TranslationError(f"响应结构异常: {str(body)[:200]!r}") from e
        return content, body.get("usage", {}) or {}

    @staticmethod
    def _log_usage(usage: dict) -> None:
        if not usage:
            return
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", 0)
        total = hit + miss
        if total > 0:
            logger.debug(
                "tokens: %d (缓存命中 %d, %.0f%%)", total, hit, 100.0 * hit / total,
            )
