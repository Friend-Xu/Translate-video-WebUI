"""
XCometStrategy — xCOMET-lite 端到端翻译质量评分

封装 xCOMET-lite (278M params, mDeBERTa v3 蒸馏),
直接预测 MQM-style 质量分数, 输出 QualityVerdict。

注册名: "xcomet"

模型: Unbabel/xCOMET-lite (~500MB, 首次自动下载到 models/xcomet/)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from core.quality.protocol import (
    QualityStrategy, QualityVerdict, ThresholdConfig, register_strategy,
)

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState
    from core.config.global_config import GlobalConfig


@register_strategy("xcomet")
class XCometStrategy(QualityStrategy):
    """xCOMET-lite — 端到端翻译质量评分

    输入 (source_text, translation) 直接输出 [0,1] 质量分数。
    与人类 MQM 评分 Kendall-Tau > 0.5, 远超 MiniLM+PPL。

    阈值: accept=0.70, review=0.40 (基于 WMT22 分布)
    """

    name = "xcomet"
    _MODEL_ID = "Unbabel/xCOMET-lite"

    def __init__(
        self,
        thresholds: ThresholdConfig | None = None,
        model_id: str | None = None,
        batch_size: int = 8,
    ):
        self._thresholds = thresholds or ThresholdConfig(accept=0.70, review=0.40)
        self._model_id = model_id or self._MODEL_ID
        self._batch_size = batch_size
        self._model = None
        self._tokenizer = None
        self._device = "cuda"

    @property
    def thresholds(self) -> ThresholdConfig:
        return self._thresholds

    @classmethod
    def from_config(cls, config: "GlobalConfig | None" = None) -> "XCometStrategy":
        t = ThresholdConfig(accept=0.70, review=0.40)
        model_id = cls._MODEL_ID
        batch_size = 8
        if config is not None:
            gate_cfg = config.project.translation.get("gate", {})
            t.accept = gate_cfg.get("threshold_accept", 0.70)
            t.review = gate_cfg.get("threshold_reject", 0.40)
            model_id = gate_cfg.get("xcomet_model", cls._MODEL_ID)
            batch_size = gate_cfg.get("xcomet_batch_size", 8)
        return cls(thresholds=t, model_id=model_id, batch_size=batch_size)

    def warmup(self) -> None:
        import os
        import torch

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cache_dir = os.path.join(project_root, "models", "xcomet")
        os.makedirs(cache_dir, exist_ok=True)

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import logging
            _logger = logging.getLogger(__name__)

            _logger.info(f"加载 xCOMET-lite: {self._model_id}")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_id, cache_dir=cache_dir,
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self._model_id, cache_dir=cache_dir,
            ).to(self._device)
            self._model.eval()
            _logger.info("xCOMET-lite 加载完成")
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "xCOMET-lite 加载失败 — 请确认 transformers 已安装且网络可访问 HuggingFace")

    def score_batch(
        self, state: "TimelineProjectState",
    ) -> dict[str, QualityVerdict]:
        results: dict[str, QualityVerdict] = {}

        if self._model is None:
            for es in state.sorted_events():
                results[es.id] = QualityVerdict(
                    score=1.0, gate_decision="A",
                    reason="xcomet_not_loaded", strategy_name=self.name,
                )
            return results

        pairs = []
        for es in state.sorted_events():
            src = es.ir.text_ref or ""
            raw_trans = es.translation
            trans = raw_trans.get("text", "") if isinstance(raw_trans, dict) else (raw_trans or "")
            if src and trans:
                pairs.append((es.id, src, trans))

        if not pairs:
            return results

        batch_scores = self._predict_batch([(s, t) for _, s, t in pairs])

        for (seg_id, src, trans), score in zip(pairs, batch_scores):
            es = state.get_event(seg_id)
            if es is None:
                continue

            trans_slot = es.translation
            if isinstance(trans_slot, str):
                es._data["translation"] = {"text": trans_slot}
            es.translation["quality_score"] = score
            es.provenance["translation_quality"] = {"composite": score, "engine": "xcomet-lite"}

            verdict = QualityVerdict.from_score(score, self._thresholds, self.name)
            verdict.sub_scores = {"xcomet_score": score}
            es.review["gate_decision"] = verdict.gate_decision
            results[seg_id] = verdict

        return results

    def _predict_batch(self, pairs: list[tuple[str, str]]) -> list[float]:
        import torch
        all_scores = []
        for i in range(0, len(pairs), self._batch_size):
            batch = pairs[i:i + self._batch_size]
            sources = [s for s, _ in batch]
            translations = [t for _, t in batch]
            inputs = self._tokenizer(
                sources, translations,
                return_tensors="pt", padding=True, truncation=True, max_length=512,
            ).to(self._device)
            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits.squeeze(-1)
                scores = torch.sigmoid(logits).cpu().tolist()
                if isinstance(scores, float):
                    scores = [scores]
                all_scores.extend(scores)
        return all_scores
