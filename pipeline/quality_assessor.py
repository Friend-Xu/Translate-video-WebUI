"""
QualityAssessor — 多维翻译质量评估

三维正交评分：
  1. Semantic (语义)     — MiniLM cross-lingual similarity
  2. Naturalness (自然度) — Qwen2-0.5B PPL ratio
  3. Structural (结构)    — CPS / duration / overlap 规则

三个维度测量本质不同的东西，不平均成一个总分。
用确定性 Tier 分层：PASS → GLANCE → REVIEW → CRITICAL
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("QualityAssessor")


# ═══════════════════════════════════════════════════════════════
# Data Model
# ═══════════════════════════════════════════════════════════════

class QualityTier(Enum):
    PASS = "pass"
    GLANCE = "glance"
    REVIEW = "review"
    CRITICAL = "critical"


@dataclass
class DimensionScore:
    value: float           # 0.0–1.0 (higher = better)
    threshold: float       # Configurable
    flagged: bool          # True if below threshold
    confidence: float      # 0.0–1.0
    label: str
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "value": round(self.value, 4),
            "threshold": self.threshold,
            "flagged": self.flagged,
            "confidence": round(self.confidence, 4),
            "label": self.label,
            "detail": self.detail,
        }


@dataclass
class QualityScores:
    index: int
    semantic: DimensionScore
    naturalness: DimensionScore
    structural: DimensionScore
    mqm: Optional[DimensionScore] = None
    tier: QualityTier = QualityTier.PASS
    tier_reason: str = ""
    translated_text_hash: str = ""

    def to_dict(self) -> dict:
        d = {
            "index": self.index,
            "scores": {
                "semantic": self.semantic.to_dict(),
                "naturalness": self.naturalness.to_dict(),
                "structural": self.structural.to_dict(),
            },
            "tier": self.tier.value,
            "tierReason": self.tier_reason,
            "textHash": self.translated_text_hash,
        }
        if self.mqm:
            d["scores"]["mqm"] = self.mqm.to_dict()
        return d


# ═══════════════════════════════════════════════════════════════
# Tier Assignment (deterministic rules, not ML)
# ═══════════════════════════════════════════════════════════════

def assign_tier(scores: QualityScores) -> Tuple[QualityTier, str]:
    s = scores.semantic
    n = scores.naturalness
    t = scores.structural

    # CRITICAL: semantic catastrophically bad
    if s.value < s.threshold * 0.5:
        return QualityTier.CRITICAL, "semantic_catastrophic"
    # CRITICAL: structural error (empty, overlap)
    if t.value < 0.3:
        return QualityTier.CRITICAL, "structural_error"
    # CRITICAL: both semantic AND naturalness flagged
    if s.flagged and n.flagged:
        return QualityTier.CRITICAL, "semantic_and_naturalness"

    flagged_count = sum([s.flagged, n.flagged, t.flagged])

    # REVIEW: 2+ flags
    if flagged_count >= 2:
        return QualityTier.REVIEW, f"{flagged_count}_flags"

    # GLANCE: 1 flag
    if flagged_count == 1:
        if s.flagged:
            return QualityTier.GLANCE, "semantic_marginal"
        if n.flagged:
            return QualityTier.GLANCE, "naturalness_marginal"
        return QualityTier.GLANCE, "structural_marginal"

    return QualityTier.PASS, "all_clear"


# ═══════════════════════════════════════════════════════════════
# Dimension Scores
# ═══════════════════════════════════════════════════════════════

def compute_cps(text: str, duration_ms: int) -> float:
    if duration_ms <= 0:
        return 0.0
    char_count = len(text.replace("\n", ""))
    return char_count / (duration_ms / 1000.0)


def structural_score(start_ms: int, end_ms: int, text: str,
                     lang: str = "zh", prev_end_ms: Optional[int] = None,
                     limit_cps: Optional[int] = None,
                     limit_min_dur: float = 0.8,
                     limit_max_dur: float = 7.0) -> DimensionScore:
    if limit_cps is None:
        limit_cps = 12 if lang in ("zh", "ja", "ko") else 20

    duration = (end_ms - start_ms) / 1000.0
    cps = compute_cps(text, end_ms - start_ms)
    issues = []
    score = 1.0

    if cps > limit_cps:
        issues.append(f"CPS {cps:.1f} > {limit_cps}")
        score -= 0.25
    if duration < limit_min_dur:
        issues.append(f"dur {duration:.2f}s < {limit_min_dur}s")
        score -= 0.25
    elif duration > limit_max_dur:
        issues.append(f"dur {duration:.2f}s > {limit_max_dur}s")
        score -= 0.15
    if not text.strip():
        issues.append("empty")
        score = 0.0
    if prev_end_ms is not None and start_ms < prev_end_ms:
        issues.append(f"overlap {prev_end_ms - start_ms}ms")
        score -= 0.4

    score = max(0.0, min(1.0, score))
    flagged = score < 0.80

    return DimensionScore(
        value=round(score, 4),
        threshold=0.80,
        flagged=flagged,
        confidence=1.0,
        label="结构质量",
        detail="; ".join(issues) if issues else f"CPS={cps:.1f}, dur={duration:.1f}s",
    )


def semantic_score(similarity: Optional[float],
                   threshold: float = 0.70,
                   confidence: float = 0.85) -> DimensionScore:
    if similarity is None:
        return DimensionScore(
            value=1.0, threshold=threshold,
            flagged=False, confidence=0.0,
            label="语义相似度", detail="not checked",
        )
    value = round(max(0.0, min(1.0, similarity)), 4)
    return DimensionScore(
        value=value, threshold=threshold,
        flagged=value < threshold, confidence=confidence,
        label="语义相似度", detail=None,
    )


def naturalness_score(ppl: float, baseline_ppl: float,
                      threshold_ratio: float = 3.0,
                      confidence: float = 0.80) -> DimensionScore:
    if ppl <= 0 or baseline_ppl <= 0:
        return DimensionScore(
            value=0.0, threshold=threshold_ratio,
            flagged=True, confidence=0.0,
            label="自然度(PPL比率)", detail="PPL unavailable",
        )
    ratio = ppl / baseline_ppl
    # ratio=1.0 → 1.0, ratio=3.0 → 0.5, ratio=10 → ~0.15
    if ratio <= 1.0:
        value = 1.0
    elif ratio <= threshold_ratio * 2:
        value = 0.5 + 0.5 * (1.0 - (ratio - 1.0) / (threshold_ratio * 2 - 1.0))
    else:
        value = 0.5 * (threshold_ratio / ratio)
    value = round(max(0.0, min(1.0, value)), 4)
    flagged = ratio > threshold_ratio

    return DimensionScore(
        value=value, threshold=threshold_ratio,
        flagged=flagged, confidence=confidence,
        label="自然度(PPL比率)",
        detail=f"PPL={ppl:.1f}, baseline={baseline_ppl:.1f}, ratio={ratio:.2f}",
    )


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_similarities(translate_log_path: str) -> Dict[int, float]:
    if not os.path.isfile(translate_log_path):
        return {}
    with open(translate_log_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sims: Dict[int, float] = {}
    for detail in data.get("details", []):
        for k, v in detail.get("similarities", {}).items():
            sims[int(k)] = float(v)
    return sims


def save_quality_report(report_path: str, report: dict) -> None:
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"质量报告已保存: {report_path}")


def load_quality_report(report_path: str) -> Optional[dict]:
    if not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════
# QualityAssessor — main orchestrator
# ═══════════════════════════════════════════════════════════════

class QualityAssessor:
    """译后质量评估编排器。

    Usage:
        assessor = QualityAssessor(ws_dir="path/to/_project")
        report = assessor.run()
        print(report["summary"])  # tier distribution, baseline PPL, etc.
    """

    def __init__(self, ws_dir: str,
                 semantic_threshold: float = 0.70,
                 naturalness_threshold: float = 3.0,
                 structural_threshold: float = 0.80,
                 naturalness_enabled: bool = True,
                 min_naturalness_chars: int = 3,
                 source_lang: str = "auto"):
        self.ws_dir = ws_dir
        self.translate_dir = os.path.join(ws_dir, "02_translate")
        self.semantic_threshold = semantic_threshold
        self.naturalness_threshold = naturalness_threshold
        self.structural_threshold = structural_threshold
        self.naturalness_enabled = naturalness_enabled
        self.min_naturalness_chars = min_naturalness_chars
        self.source_lang = source_lang

        self._ppl_evaluator = None
        self._srt_items: List[dict] = []

    # ── entry point ──────────────────────────────────────────

    def run(self) -> dict:
        """Run full quality assessment. Returns quality_report dict."""
        t0 = time.time()
        logger.info(f"QualityAssessor 开始: {self.ws_dir}")

        self._load_srt()
        if not self._srt_items:
            logger.warning("无法加载字幕条目")
            return {}

        similarities = self._load_similarities()
        baseline_ppl = self._compute_baseline_ppl() if self.naturalness_enabled else 60.0
        entries = self._compute_all_scores(similarities, baseline_ppl)
        summary = self._build_summary(entries, baseline_ppl)
        report = self._build_report(entries, summary)

        report_path = os.path.join(self.translate_dir, "quality_report.json")
        save_quality_report(report_path, report)

        logger.info(f"QualityAssessor 完成: {summary['total']} entries, "
                    f"{summary['tier_critical']} critical, "
                    f"{summary['tier_review']} review, "
                    f"{summary['tier_glance']} glance, "
                    f"{summary['tier_pass']} pass, "
                    f"耗时 {time.time() - t0:.1f}s")
        return report

    # ── load source data ────────────────────────────────────

    def _load_srt(self):
        """Read machine.srt into _srt_items."""
        import pysrt
        srt_path = os.path.join(self.translate_dir, "machine.srt")
        if not os.path.isfile(srt_path):
            logger.error(f"machine.srt 不存在: {srt_path}")
            return
        subs = pysrt.open(srt_path, encoding="utf-8")
        for sub in subs:
            self._srt_items.append({
                "index": sub.index,
                "start": str(sub.start),
                "end": str(sub.end),
                "startMs": sub.start.ordinal,
                "endMs": sub.end.ordinal,
                "text": sub.text,
            })

    def _load_similarities(self) -> Dict[int, float]:
        log_path = os.path.join(self.translate_dir, "source-translate-log.json")
        return load_similarities(log_path)

    # ── PPL baseline ────────────────────────────────────────

    def _compute_baseline_ppl(self) -> float:
        """Adaptive baseline from top-similarity entries."""
        sims = self._load_similarities()
        if not sims:
            return 60.0
        # Top 30% by similarity, min 5 entries
        sorted_items = sorted(self._srt_items,
                              key=lambda x: sims.get(x["index"], 0),
                              reverse=True)
        top_n = max(5, len(sorted_items) // 3)
        top_texts = [it["text"] for it in sorted_items[:top_n]
                     if len(it["text"]) >= self.min_naturalness_chars]

        try:
            from pipeline.ppl_evaluator import PPLEvaluator
            self._ppl_evaluator = PPLEvaluator()
        except Exception as e:
            logger.warning(f"PPLEvaluator 加载失败: {e}")
            self.naturalness_enabled = False
            return 60.0

        return self._ppl_evaluator.compute_baseline(
            top_texts, min_entries=5, static_fallback=60.0,
        )

    # ── score computation ────────────────────────────────────

    def _compute_all_scores(self, similarities: Dict[int, float],
                            baseline_ppl: float) -> List[QualityScores]:
        texts = [it["text"] for it in self._srt_items]
        ppls: Dict[int, float] = {}

        if self.naturalness_enabled and self._ppl_evaluator:
            try:
                raw = self._ppl_evaluator.batch_perplexity(texts)
                for i, it in enumerate(self._srt_items):
                    if len(it["text"]) >= self.min_naturalness_chars:
                        ppls[it["index"]] = raw[i]
            except Exception as e:
                logger.warning(f"PPL 批量推理失败: {e}")

        entries: List[QualityScores] = []
        for i, it in enumerate(self._srt_items):
            idx = it["index"]
            prev_end = self._srt_items[i - 1]["endMs"] if i > 0 else None

            sem = semantic_score(
                similarities.get(idx),
                threshold=self.semantic_threshold,
            )
            nat = naturalness_score(
                ppls.get(idx, 0.0), baseline_ppl,
                threshold_ratio=self.naturalness_threshold,
                confidence=0.80 if idx in ppls else 0.0,
            )
            st = structural_score(
                it["startMs"], it["endMs"], it["text"],
                lang=self.source_lang,
                prev_end_ms=prev_end,
            )

            scores = QualityScores(
                index=idx,
                semantic=sem,
                naturalness=nat,
                structural=st,
                translated_text_hash=text_hash(it["text"]),
            )
            scores.tier, scores.tier_reason = assign_tier(scores)
            entries.append(scores)

        return entries

    # ── summary ──────────────────────────────────────────────

    def _build_summary(self, entries: List[QualityScores],
                       baseline_ppl: float) -> dict:
        tier_counts = {"pass": 0, "glance": 0, "review": 0, "critical": 0}
        for e in entries:
            tier_counts[e.tier.value] += 1
        return {
            "total": len(entries),
            "tier_pass": tier_counts["pass"],
            "tier_glance": tier_counts["glance"],
            "tier_review": tier_counts["review"],
            "tier_critical": tier_counts["critical"],
            "naturalness_baseline_ppl": round(baseline_ppl, 1),
            "dimension_coverage": {
                "semantic": sum(1 for e in entries if e.semantic.confidence > 0),
                "naturalness": sum(1 for e in entries if e.naturalness.confidence > 0),
                "structural": len(entries),
            },
        }

    def _build_report(self, entries: List[QualityScores],
                      summary: dict) -> dict:
        return {
            "version": 1,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model_versions": {
                "semantic": "paraphrase-multilingual-MiniLM-L12-v2",
                "naturalness": "Qwen/Qwen2-0.5B (local)",
            },
            "config_snapshot": {
                "semantic_threshold": self.semantic_threshold,
                "naturalness_threshold": self.naturalness_threshold,
                "structural_threshold": self.structural_threshold,
            },
            "summary": summary,
            "entries": [e.to_dict() for e in entries],
        }
