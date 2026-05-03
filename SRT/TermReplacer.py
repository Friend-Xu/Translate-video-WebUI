"""
TermReplacer.py — 术语词典替换器

支持多领域术语词典（JSON 配置），按最长匹配原则替换。
"""

import os
import json
import logging
from typing import Dict

logger = logging.getLogger("TermReplacer")


class TermReplacer:
    """术语替换器

    Usage:
        replacer = TermReplacer("config/terms/", "minecraft.json")
        text = replacer.replace("I found a Diamond and some Redstone")
        # -> "I found a 钻石 and some 红石"
    """

    def __init__(self, dict_dir: str = "config/terms/", default_dict: str = "minecraft.json"):
        self.dict_dir = dict_dir
        self.active = self._load_dict(os.path.join(dict_dir, default_dict))

    def _load_dict(self, path: str) -> Dict[str, str]:
        """加载 JSON 术语词典"""
        if not os.path.exists(path):
            logger.warning(f"术语词典不存在: {path}")
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            terms = data.get("terms", {})
            logger.info(f"加载术语词典: {path} ({len(terms)} 条)")
            return terms
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"术语词典解析失败: {e}")
            return {}

    def replace(self, text: str) -> str:
        """按最长匹配原则替换术语

        按术语长度降序排列，避免短词覆盖长词。
        例如: "Cave Spider" 先于 "Spider" 被替换。
        """
        if not self.active:
            return text

        # 按长度降序，确保长词优先匹配
        sorted_terms = sorted(self.active.items(), key=lambda x: -len(x[0]))

        for en, zh in sorted_terms:
            text = text.replace(en, zh)

        return text

    def replace_file(self, srt_path: str, output_path: str = None) -> str:
        """替换 SRT 文件中的术语

        Returns:
            输出文件路径
        """
        import pysrt

        subs = pysrt.open(srt_path)
        replaced_count = 0

        for sub in subs:
            original = sub.text
            sub.text = self.replace(original)
            if sub.text != original:
                replaced_count += 1

        if output_path is None:
            base = os.path.splitext(srt_path)[0]
            output_path = f"{base}-replace.srt"

        subs.save(output_path, encoding="utf-8")
        logger.info(f"术语替换完成: {replaced_count}/{len(subs)} 条被修改，保存至 {output_path}")
        return output_path

    def list_available(self) -> list:
        """列出可用的术语词典"""
        if not os.path.exists(self.dict_dir):
            return []
        return [f for f in os.listdir(self.dict_dir) if f.endswith(".json")]

    def switch_dict(self, dict_name: str):
        """切换术语词典"""
        path = os.path.join(self.dict_dir, dict_name)
        self.active = self._load_dict(path)


# ── 便捷函数 ──────────────────────────────────────

def replace_terms(srt_path: str, dict_dir: str = "config/terms/", dict_name: str = "minecraft.json") -> str:
    """一键替换术语"""
    replacer = TermReplacer(dict_dir, dict_name)
    return replacer.replace_file(srt_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="术语词典替换")
    parser.add_argument("srt", help="输入 SRT 文件路径")
    parser.add_argument("--dict-dir", default="config/terms/", help="词典目录")
    parser.add_argument("--dict", default="minecraft.json", help="词典文件名")
    parser.add_argument("--list", action="store_true", help="列出可用词典")
    parser.add_argument("-o", "--output", default=None, help="输出路径")
    args = parser.parse_args()

    replacer = TermReplacer(args.dict_dir, args.dict)

    if args.list:
        print("可用术语词典:")
        for d in replacer.list_available():
            print(f"  - {d}")
    else:
        output = replacer.replace_file(args.srt, args.output)
        print(f"替换完成: {output}")
