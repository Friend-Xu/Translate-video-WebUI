"""
MQM (Multidimensional Quality Metrics) translation quality scorer.

Dimensions and weights:
  Accuracy      0.35 — source meaning preserved
  Fluency       0.30 — natural target language
  Terminology   0.20 — domain terms correct and consistent
  Style         0.10 — register/tone matches source
  Locale        0.05 — date/number/unit conventions

Scores 1-5 per dimension, weighted composite normalized to 0-1.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

MQM_WEIGHTS = {
    "accuracy": 0.35,
    "fluency": 0.30,
    "terminology": 0.20,
    "style": 0.10,
    "locale": 0.05,
}


@dataclass
class MQMScore:
    accuracy: float = 0.0
    fluency: float = 0.0
    terminology: float = 0.0
    style: float = 0.0
    locale: float = 0.0

    @property
    def composite(self) -> float:
        return (
            self.accuracy * MQM_WEIGHTS["accuracy"]
            + self.fluency * MQM_WEIGHTS["fluency"]
            + self.terminology * MQM_WEIGHTS["terminology"]
            + self.style * MQM_WEIGHTS["style"]
            + self.locale * MQM_WEIGHTS["locale"]
        ) / 5.0

    def to_dict(self) -> dict:
        return {
            "accuracy": round(self.accuracy, 3),
            "fluency": round(self.fluency, 3),
            "terminology": round(self.terminology, 3),
            "style": round(self.style, 3),
            "locale": round(self.locale, 3),
            "composite": round(self.composite, 3),
        }

    def verdict(self, threshold: float = 0.6) -> str:
        c = self.composite
        if c >= threshold + 0.1:
            return "PASS"
        elif c >= threshold:
            return "WARN"
        return "FAIL"


class MQMScorer:
    """LLM self-evaluation based MQM translation quality scorer."""

    def __init__(self, api, source_lang: str = "ja", target_lang: str = "Simplified Chinese"):
        self.api = api
        self.source_lang = source_lang
        self.target_lang = target_lang

    def score_single(self, source: str, translation: str, context: str = "",
                     terms: Dict[str, str] = None) -> MQMScore:
        prompt = self._build_mqm_prompt(source, translation, context, terms)
        try:
            raw = self.api.translate(prompt)
            return self._parse_response(raw)
        except Exception:
            return MQMScore()

    def score_group(self, pairs: List[Tuple[str, str]],
                    terms: Dict[str, str] = None) -> List[MQMScore]:
        return [self.score_single(src, tgt, "", terms) for src, tgt in pairs]

    def _build_mqm_prompt(self, source: str, translation: str,
                           context: str = "", terms: Dict[str, str] = None) -> str:
        term_str = ""
        if terms:
            items = [f"  {k} -> {v}" for k, v in list(terms.items())[:20]]
            term_str = "\nGlossary:\n" + "\n".join(items)
        ctx_str = f"\nContext: {context}" if context else ""
        return (
            f"Evaluate this {self.source_lang}->{self.target_lang} translation "
            f"on MQM dimensions (1-5, 5=perfect):\n\n"
            f"Source: {source}\n"
            f"Translation: {translation}"
            f"{ctx_str}"
            f"{term_str}\n\n"
            f"Dimensions:\n"
            f"  accuracy — meaning fully conveyed?\n"
            f"  fluency — natural target language?\n"
            f"  terminology — terms correct and consistent?\n"
            f"  style — register/tone matches source?\n"
            f"  locale — date/number/unit conventions?\n\n"
            f"Output only JSON: "
            f'{{"accuracy":N,"fluency":N,"terminology":N,"style":N,"locale":N}}'
        )

    def _parse_response(self, text: str) -> MQMScore:
        import json, re
        if not text:
            return MQMScore()
        text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return MQMScore()
        try:
            data = json.loads(text[start:end + 1])
            return MQMScore(
                accuracy=float(data.get("accuracy", 0)),
                fluency=float(data.get("fluency", 0)),
                terminology=float(data.get("terminology", 0)),
                style=float(data.get("style", 0)),
                locale=float(data.get("locale", 0)),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return MQMScore()
