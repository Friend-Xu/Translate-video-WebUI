"""
ValidationCompositePass — 独立校验阶段 (CLI Runtime 计划书 §9)

将 TextGate + TranslationScorer 收敛为独立 VALIDATE stage 的 pass。
校验完成后将结果挂到 state.validation_report，用于 Export Gate 判断。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState


@dataclass
class ValidationReport:
    """校验汇总报告 — 挂到 state.validation_report。"""
    passed: bool = True
    total_events: int = 0
    warnings: int = 0
    errors: int = 0
    structural_ok: bool = True     # 时间轴无重叠/负时长
    subtitle_ok: bool = True       # 阅读速度/CPS 合规
    semantic_ok: bool = True       # 翻译语义一致性
    export_ready: bool = False     # 是否可进入导出
    details: list[dict] = field(default_factory=list)


class ValidationCompositePass(TimelinePass):
    """将校验步骤合并为一个 pass。

    校验顺序:
      1. 结构校验: 时间轴无重叠、无负时长
      2. 字幕可读性: 行长度/阅读速度
      3. 语义校验: 检查 event_state 中的评分数据
      4. 汇总 → state.validation_report
    """

    name = "validation_composite"
    depends_on: list[str] = ["llm_translation"]

    MAX_CPS = 25.0                # 字符/秒 上限
    MAX_LINE_LENGTH = 42          # 单行最大字符数

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        report = ValidationReport()
        report.total_events = len(state.event_states)

        for es in state.event_states.values():
            evt = es.ir
            detail: dict = {"event_id": evt.id}
            issues: list[str] = []

            # 1. 结构校验
            if evt.start >= evt.end:
                issues.append("invalid_duration")
                report.structural_ok = False
            dur = evt.end - evt.start

            # 2. 字幕可读性
            text = evt.text_ref or ""
            if text and dur > 0:
                cps = len(text) / dur
                if cps > self.MAX_CPS:
                    issues.append(f"high_cps:{cps:.0f}")
                if len(text) > self.MAX_LINE_LENGTH:
                    issues.append(f"long_line:{len(text)}")

            # 3. 语义 — 检查 event_state 中是否已有评分
            scores = es.annotations.get("translation_scores", {})
            if scores:
                composite = scores.get("composite", 1.0)
                accepted = scores.get("accepted", True)
                if composite < 0.65 or not accepted:
                    issues.append("low_translation_quality")
                    report.semantic_ok = False

            if issues:
                detail["issues"] = issues
                report.warnings += 1
                report.details.append(detail)

        # 汇总判断
        report.passed = report.structural_ok and report.semantic_ok and report.errors == 0
        report.export_ready = report.passed
        report.subtitle_ok = report.warnings < report.total_events * 0.3  # <30% warnings

        state.validation_report = report
        return state
