"""
XCometStrategy — xCOMET-lite 端到端翻译质量评分

xCOMET-lite (278M params, mDeBERTa-v3-base 蒸馏) 直接预测 [0,1] 质量分数。
与人类 MQM 评分 Kendall-Tau > 0.5, 远超 MiniLM+PPL。

注册名: "xcomet"

模型 (均为本地路径, 零运行时下载):
  - 基座: models/mdeberta-v3-base        (架构 + 分词器, microsoft/mdeberta-v3-base)
  - 权重: models/XCOMET-lite/pytorch_model.bin  (蒸馏权重, Unbabel/xCOMET-lite)
  - 源码: models/xCOMET-lite-main/        (GitHub NL2G/xCOMET-lite, sys.path 注入)

加载方式: xCOMET-lite 无 config.json, 不能用 transformers 直接加载;
必须用专用 XCOMETLite 类 (xcomet/deberta_encoder.py) — 曾错误使用
AutoModelForSequenceClassification.from_pretrained, 该实现从未真实跑通。
"""
from __future__ import annotations
import logging
import os
import threading
from typing import TYPE_CHECKING

from core.quality.protocol import (
    QualityStrategy, QualityVerdict, ThresholdConfig, register_strategy,
)

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState
    from core.config.global_config import GlobalConfig

_logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "models", "xCOMET-lite-main")
_BASE_DIR = os.path.join(_PROJECT_ROOT, "models", "mdeberta-v3-base")
_WT_PATH = os.path.join(_PROJECT_ROOT, "models", "XCOMET-lite", "pytorch_model.bin")


@register_strategy("xcomet")
class XCometStrategy(QualityStrategy):
    """xCOMET-lite — 端到端翻译质量评分 (本地模型, 零下载)"""

    name = "xcomet"

    def __init__(
        self,
        thresholds: ThresholdConfig | None = None,
        batch_size: int = 8,
    ):
        self._thresholds = thresholds or ThresholdConfig(accept=0.70, review=0.40)
        self._batch_size = batch_size
        self._model = None
        self._load_lock = threading.Lock()

    @property
    def thresholds(self) -> ThresholdConfig:
        return self._thresholds

    @classmethod
    def from_config(cls, config: "GlobalConfig | None" = None) -> "XCometStrategy":
        t = ThresholdConfig(accept=0.70, review=0.40)
        batch_size = 8
        if config is not None:
            gate_cfg = config.project.translation.get("gate", {})
            t.accept = gate_cfg.get("threshold_accept", 0.70)
            t.review = gate_cfg.get("threshold_reject", 0.40)
            batch_size = gate_cfg.get("xcomet_batch_size", 8)
        return cls(thresholds=t, batch_size=batch_size)

    def warmup(self) -> None:
        """加载 xCOMET-lite (基座 + 蒸馏权重)。失败时响亮 log, 不静默。"""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import sys
                import torch
                if _SRC_DIR not in sys.path:
                    sys.path.insert(0, _SRC_DIR)
                from xcomet.deberta_encoder import XCOMETLite

                if not (os.path.isdir(_BASE_DIR) and os.path.isfile(_WT_PATH)):
                    raise FileNotFoundError(
                        f"xCOMET-lite 模型缺失: 基座 {_BASE_DIR} 或权重 {_WT_PATH} "
                        "(需从 HF 下载 microsoft/mdeberta-v3-base + Unbabel/xCOMET-lite)"
                    )

                _logger.info("加载 xCOMET-lite (基座 %s)", _BASE_DIR)
                model = XCOMETLite(pretrained_model=_BASE_DIR)
                sd = torch.load(_WT_PATH, map_location="cpu", weights_only=False)
                model.load_state_dict(sd)
                model.eval()
                self._model = model
                _logger.info("xCOMET-lite 加载完成 (%d M 参数)",
                             sum(p.numel() for p in model.parameters()) / 1e6)
            except Exception as e:
                _logger.error("xCOMET-lite 加载失败: %s", e)

    def score_batch(
        self, state: "TimelineProjectState",
    ) -> dict[str, QualityVerdict]:
        results: dict[str, QualityVerdict] = {}
        # warmup 由调用方 (TranslationQualityPass.apply) 负责;
        # 未 warmup (self._model None) = 未加载 → 诚实降级 (契约测试锁定)

        if self._model is None:
            # 禁止兜底: 模型未加载时给虚假满分 A 会让"质量门控通过"成为谎言
            # (英文配音视频事故同款)。诚实降级: 全部置 B + 人工审核。
            _logger.warning(
                "xCOMET-lite 未加载 — 无法评分, 全部事件置 Gate B + 人工审核, "
                "不给虚假满分")
            for es in state.sorted_events():
                results[es.id] = QualityVerdict(
                    score=0.0, gate_decision="B",
                    reason="xcomet_not_loaded", strategy_name=self.name,
                    needs_human=True,
                )
            return results

        pairs = []
        for es in state.sorted_events():
            src = es.ir.text_ref or ""
            # 槽位类型化 (Phase 3A): es.translation 恒为 Translation 对象
            trans = (es.translation.text or "") if es.translation else ""
            if src and trans:
                pairs.append((es.id, src, trans))

        if not pairs:
            return results

        try:
            import torch
            gpus = 1 if torch.cuda.is_available() else 0
            out = self._model.predict(
                [{"src": s, "mt": t} for _, s, t in pairs],
                batch_size=self._batch_size, gpus=gpus,
            )
            scores = list(out.scores)
        except Exception as e:
            _logger.error("xCOMET-lite 评分失败: %s", e)
            for es in state.sorted_events():
                results[es.id] = QualityVerdict(
                    score=0.0, gate_decision="B",
                    reason="xcomet_predict_failed", strategy_name=self.name,
                    needs_human=True,
                )
            return results

        for (seg_id, src, trans), score in zip(pairs, scores):
            es = state.get_event(seg_id)
            if es is None:
                continue
            es.translation.quality_score = score
            es.provenance["translation_quality"] = {"composite": score, "engine": "xcomet-lite"}
            verdict = QualityVerdict.from_score(score, self._thresholds, self.name)
            verdict.sub_scores = {"xcomet_score": score}
            es.review.gate_decision = verdict.gate_decision
            results[seg_id] = verdict

        return results
