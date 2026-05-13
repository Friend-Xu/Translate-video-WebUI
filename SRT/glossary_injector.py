"""
术语表按需注入模块 — 扫描源文本，只将实际出现的术语注入翻译 prompt。

避免全量术语表注入导致 token 浪费（310 条 → 仅命中 0-3 条）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Tuple


def _is_valid_glossary_term(term: str) -> bool:
    stripped = term.strip()
    if not stripped:
        return False
    if "§" in stripped:
        return False
    if " " not in stripped:
        return False
    return True


def load_glossary(dict_dir: str, dict_name: str) -> Dict[str, str]:
    """加载术语表 JSON 文件，返回 {源术语: 目标译名} 映射。"""
    path = os.path.join(dict_dir, dict_name)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("terms", {})
    filtered = {k: v for k, v in raw.items() if _is_valid_glossary_term(k)}
    return filtered


def load_glossaries(dict_dir: str, dict_names: list[str]) -> Dict[str, str]:
    """加载并合并多个术语表，后面的覆盖前面的同名术语。"""
    merged: Dict[str, str] = {}
    for name in dict_names:
        terms = load_glossary(dict_dir, name)
        merged.update(terms)
    return merged


def scan_matches(text: str, glossary: Dict[str, str]) -> Dict[str, str]:
    """扫描单段文本，返回命中的术语 {源术语: 目标译名}。

    按术语长度降序匹配（长术语优先于短术语），使用单词边界避免子串误匹配。
    """
    matched: Dict[str, str] = {}
    sorted_terms = sorted(glossary.keys(), key=len, reverse=True)
    escaped_terms = {t: re.escape(t) for t in sorted_terms}
    covered_ranges: List[Tuple[int, int]] = []

    for term in sorted_terms:
        pattern = r"\b" + escaped_terms[term] + r"\b"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start, end = match.start(), match.end()
            if any(cs <= start < ce or cs < end <= ce for cs, ce in covered_ranges):
                continue
            matched[term] = glossary[term]
            covered_ranges.append((start, end))

    return matched


def collect_glossary_for_group(
    texts: List[str], glossary: Dict[str, str]
) -> Tuple[str, Dict[str, str]]:
    """扫描一组字幕文本，返回 (prompt 注入字符串, 命中术语 dict)。"""
    all_matched: Dict[str, str] = {}
    for text in texts:
        hits = scan_matches(text, glossary)
        all_matched.update(hits)

    if not all_matched:
        return "", {}

    lines = ["术语对照（请严格使用以下译名）："]
    for src, tgt in all_matched.items():
        lines.append(f"  {src} → {tgt}")
    return "\n".join(lines), all_matched


class GlossaryInjector:
    """术语表注入器 — 预缓存排序键、转义键，消除 per-call 80MB 临时分配。

    原 scan_matches() 每次调用重建 sorted_terms + escaped_terms（218K 条目 = ~80MB）。
    改为构造时一次性缓存，之后 scan() / collect_for_group() 直接复用，0 额外分配。
    """

    def __init__(self, glossary: Dict[str, str]):
        self.glossary = glossary
        self._sorted_terms: List[str] = sorted(glossary.keys(), key=len, reverse=True)
        self._escaped_terms: Dict[str, str] = {t: re.escape(t) for t in self._sorted_terms}

    def scan(self, text: str) -> Dict[str, str]:
        """扫描单段文本，返回命中的术语 {源术语: 目标译名}。

        按术语长度降序匹配（长术语优先于短术语），使用单词边界避免子串误匹配。
        """
        matched: Dict[str, str] = {}
        covered_ranges: List[Tuple[int, int]] = []

        for term in self._sorted_terms:
            pattern = r"\b" + self._escaped_terms[term] + r"\b"
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.start(), match.end()
                if any(cs <= start < ce or cs < end <= ce for cs, ce in covered_ranges):
                    continue
                matched[term] = self.glossary[term]
                covered_ranges.append((start, end))

        return matched

    def collect_for_group(
        self, texts: List[str]
    ) -> Tuple[str, Dict[str, str]]:
        """扫描一组字幕文本，返回 (prompt 注入字符串, 命中术语 dict)。"""
        all_matched: Dict[str, str] = {}
        for text in texts:
            hits = self.scan(text)
            all_matched.update(hits)

        if not all_matched:
            return "", {}

        lines = ["术语对照（请严格使用以下译名）："]
        for src, tgt in all_matched.items():
            lines.append(f"  {src} → {tgt}")
        return "\n".join(lines), all_matched
