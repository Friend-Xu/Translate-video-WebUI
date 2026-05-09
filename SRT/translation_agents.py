"""
Multi-agent translation pipeline following the Conductor pattern.

Agents communicate via filesystem (JSON files), never memory.
Pipeline: Director -> Glossary -> Translator -> Mapper -> Reviewer -> Polisher
"""

import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass, field

from SRT.mqm_scorer import MQMScorer

logger = logging.getLogger("TranslationAgents")


class BaseAgent:
    def __init__(self, name: str, work_dir: str):
        self.name = name
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _write_output(self, filename: str, data: dict):
        path = self.work_dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[{self.name}] wrote {filename}")


class GlossaryAgent(BaseAgent):
    """Load term dictionary, match terms against source subtitles."""

    def run(self, dict_path: str, source_texts: List[str]) -> dict:
        terms = {}
        if dict_path and os.path.isfile(dict_path):
            try:
                data = json.loads(Path(dict_path).read_text("utf-8"))
                all_terms = data.get("terms", {})
                source_concat = " ".join(source_texts).lower()
                terms = {k: v for k, v in all_terms.items()
                         if k.lower() in source_concat}
            except Exception as e:
                logger.warning(f"[{self.name}] glossary load failed: {e}")
        output = {"terms": terms, "term_count": len(terms)}
        self._write_output("glossary_context.json", output)
        return output


class TranslatorAgent(BaseAgent):
    """Creative translation without format or line-count constraints."""

    def run(self, group: List[dict], api, rate_limiter,
            source_lang: str, target_lang: str,
            glossary_terms: Dict[str, str] = None) -> dict:
        lines = [f"[{s['index']}] {s['text']}" for s in group]
        term_str = ""
        if glossary_terms:
            items = [f"  {k} -> {v}" for k, v in list(glossary_terms.items())[:20]]
            term_str = "\nUse these term translations:\n" + "\n".join(items)

        prompt = (
            f"Translate these {source_lang} subtitles into natural {target_lang}. "
            f"Focus on meaning and fluency. Do NOT worry about line count.\n"
            f"{term_str}\n\n"
            + "\n".join(lines)
            + "\n\nOutput as flowing natural text (no numbers, no formatting):"
        )
        rate_limiter.acquire()
        raw = api.translate(prompt)
        output = {"creative_text": raw, "source_indices": [s['index'] for s in group]}
        gid = group[0].get('group_id', '0')
        self._write_output(f"creative_g{gid}.json", output)
        return output


class StructuralMapperAgent(BaseAgent):
    """Map creative translation back to exact SRT line indices."""

    def run(self, group: List[dict], creative_text: str,
            api, rate_limiter) -> dict:
        n = len(group)
        lines = [f"<{s['index']}> {s['text']}" for s in group]
        prompt = (
            f"Below are {n} source subtitle lines and a translated text. "
            f"Split the translation into exactly {n} lines to match the source.\n\n"
            f"Source:\n" + "\n".join(lines) + "\n\n"
            f"Translation:\n{creative_text}\n\n"
            f"Output exactly {n} lines in this format:\n" +
            "\n".join([f"<{s['index']}> [text]" for s in group])
        )
        rate_limiter.acquire()
        raw = api.translate(prompt)
        mapping = self._parse_mapping(raw, n)
        if len(mapping) != n:
            mapping = self._fallback_split(creative_text, group)
        gid = group[0].get('group_id', '0')
        self._write_output(f"mapping_g{gid}.json", {"mapping": mapping})
        return {"mapping": mapping, "source_count": n, "mapped_count": len(mapping)}

    def _parse_mapping(self, text: str, expected: int) -> Dict[int, str]:
        import re
        if not text:
            return {}
        pattern = re.compile(r"^\s*<(\d+)>\s*(.*?)$", re.MULTILINE)
        result = {}
        for m in pattern.finditer(text):
            result[int(m.group(1))] = m.group(2).strip()
        return result if len(result) == expected else {}

    def _fallback_split(self, creative_text: str, group: List[dict]) -> Dict[int, str]:
        import re
        segments = re.split(r'(?<=[。！？.!?])\s*', creative_text)
        segments = [s.strip() for s in segments if s.strip()]
        result = {}
        for i, sub in enumerate(group):
            result[sub['index']] = segments[i] if i < len(segments) else sub['text']
        return result


class ReviewerAgent(BaseAgent):
    """MQM quality evaluation for each translated line."""

    def run(self, source_texts: Dict[int, str], translations: Dict[int, str],
            api, source_lang: str, target_lang: str,
            glossary_terms: Dict[str, str] = None) -> dict:
        scorer = MQMScorer(api, source_lang, target_lang)
        scores = {}
        for idx in source_texts:
            if idx in translations:
                scores[str(idx)] = scorer.score_single(
                    source_texts[idx], translations[idx],
                    terms=glossary_terms,
                ).to_dict()
        avg = 0.0
        if scores:
            avg = sum(s['composite'] for s in scores.values()) / len(scores)
        report = {
            "scores": scores,
            "average_composite": round(avg, 3),
            "verdict": "PASS" if avg >= 0.6 else "WARN" if avg >= 0.5 else "FAIL",
        }
        self._write_output("mqm_report.json", report)
        return report


class PolisherAgent(BaseAgent):
    """Apply term replacements and produce final output."""

    def run(self, mapping: Dict[int, str], glossary_terms: Dict[str, str],
            group: List[dict]) -> dict:
        result = {}
        for sub in group:
            text = mapping.get(sub['index'], sub['text'])
            for term, replacement in glossary_terms.items():
                text = text.replace(term, replacement)
            result[str(sub['index'])] = text
        gid = group[0].get('group_id', '0')
        self._write_output(f"polished_g{gid}.json", {"final": result})
        return {"final": result, "count": len(result)}


class AgentPipeline:
    """Orchestrates the full multi-agent translation pipeline for one group."""

    def __init__(self, api, rate_limiter, work_dir: str,
                 source_lang: str = "ja", target_lang: str = "Simplified Chinese",
                 glossary_path: str = ""):
        self.api = api
        self.rate_limiter = rate_limiter
        self.work_dir = work_dir
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.glossary_path = glossary_path
        os.makedirs(work_dir, exist_ok=True)

    def run_group(self, group: List[dict], group_id: int,
                  glossary_terms: Dict[str, str] = None) -> Tuple[Dict[int, str], dict]:
        """Run full pipeline on one group. Returns (index_mapping, mqm_report)."""
        for s in group:
            s['group_id'] = group_id

        translator = TranslatorAgent("translator", self.work_dir)
        creative = translator.run(
            group, self.api, self.rate_limiter,
            self.source_lang, self.target_lang, glossary_terms,
        )

        mapper = StructuralMapperAgent("mapper", self.work_dir)
        mapping_result = mapper.run(
            group, creative["creative_text"],
            self.api, self.rate_limiter,
        )
        mapping = mapping_result["mapping"]

        reviewer = ReviewerAgent("reviewer", self.work_dir)
        source_dict = {s['index']: s['text'] for s in group}
        mqm = reviewer.run(
            source_dict, {int(k): v for k, v in mapping.items()},
            self.api, self.source_lang, self.target_lang, glossary_terms,
        )

        polisher = PolisherAgent("polisher", self.work_dir)
        polished = polisher.run(mapping, glossary_terms or {}, group)

        return {int(k): v for k, v in polished["final"].items()}, mqm
