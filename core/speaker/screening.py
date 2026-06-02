"""
Speaker Screening Layer — 纯信号规则筛查（零模型依赖）

检测 pyannote 不关心的信号质量问题：
  规则1: 段落时长 < min_duration → 声纹不足 → 🔴
  规则2: 段落间有重叠 → 切片污染 → 🔴
  规则3: 段落内有剧烈能量脉冲 → 可能多人同时说话 → 🟡

所有规则都不依赖任何 ML 模型，纯 numpy + subprocess 可完成。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScreeningIssue:
    """单个筛查问题。"""
    segment_id: str
    speaker_id: str
    start_sec: float
    end_sec: float
    rule: str          # "too_short" | "overlap" | "energy_spike"
    severity: str       # "critical" | "warning"
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class ScreeningConfig:
    """筛查参数。"""
    min_duration_sec: float = 1.2        # 规则1 最短时长
    overlap_tolerance_sec: float = 0.05  # 规则2 重叠容忍
    energy_spike_ratio: float = 3.0      # 规则3 能量脉冲阈值 (倍于均值)


class ScreeningLayer:
    """信号规则筛查器 — 纯信号处理，零模型依赖。"""

    def __init__(self, config: Optional[ScreeningConfig] = None):
        self.cfg = config or ScreeningConfig()

    def screen(self, speaker_timeline: list[dict],
               vocals_path: Optional[str] = None) -> list[ScreeningIssue]:
        """对说话人时间线执行所有筛查规则。"""
        issues: list[ScreeningIssue] = []
        issues.extend(self._check_duration(speaker_timeline))
        issues.extend(self._check_overlap(speaker_timeline))
        if vocals_path and os.path.isfile(vocals_path):
            issues.extend(self._check_energy_spikes(speaker_timeline, vocals_path))
        return issues

    # ── 规则1: 短句 ───────────────────────────────

    def _check_duration(self, timeline: list[dict]) -> list[ScreeningIssue]:
        issues = []
        for seg in timeline:
            dur = seg.get("end", 0) - seg.get("start", 0)
            if dur < self.cfg.min_duration_sec:
                issues.append(ScreeningIssue(
                    segment_id=seg.get("id", f"{seg.get('speaker')}_{seg.get('start')}"),
                    speaker_id=seg.get("speaker", "?"),
                    start_sec=seg.get("start", 0),
                    end_sec=seg.get("end", 0),
                    rule="too_short",
                    severity="critical",
                    message=f"段落过短 ({dur:.1f}s < {self.cfg.min_duration_sec}s)，声纹提取不可靠",
                    detail={"duration": dur, "min_required": self.cfg.min_duration_sec},
                ))
        return issues

    # ── 规则2: 重叠 ───────────────────────────────

    def _check_overlap(self, timeline: list[dict]) -> list[ScreeningIssue]:
        issues = []
        sorted_segs = sorted(timeline, key=lambda s: (s.get("start", 0), s.get("end", 0)))
        for i in range(len(sorted_segs) - 1):
            a, b = sorted_segs[i], sorted_segs[i + 1]
            a_end, b_start = a.get("end", 0), b.get("start", 0)
            overlap = a_end - b_start
            if overlap > self.cfg.overlap_tolerance_sec and a.get("speaker") != b.get("speaker"):
                for seg in (a, b):
                    issues.append(ScreeningIssue(
                        segment_id=seg.get("id", f"{seg.get('speaker')}_{seg.get('start')}"),
                        speaker_id=seg.get("speaker", "?"),
                        start_sec=seg.get("start", 0),
                        end_sec=seg.get("end", 0),
                        rule="overlap",
                        severity="critical",
                        message=f"与相邻段重叠 {overlap:.2f}s，声纹可能被污染",
                        detail={"overlap_sec": overlap, "with_segment": b.get("id") if seg == a else a.get("id")},
                    ))
        return issues

    # ── 规则3: 能量脉冲 ───────────────────────────

    def _check_energy_spikes(self, timeline: list[dict],
                              vocals_path: str) -> list[ScreeningIssue]:
        """检测段落内是否有多人同时说话的剧烈能量脉冲。

        ffmpeg 提取振幅 → 计算 RMS 能量 → 标记超出阈值 N 倍的片段。
        """
        issues = []
        try:
            from pipeline.utils import get_ffmpeg_exe
            ffmpeg = get_ffmpeg_exe()
        except Exception:
            return issues

        for seg in timeline:
            start, end = seg.get("start", 0), seg.get("end", 0)
            dur = end - start
            if dur < 0.5:
                continue  # 太短，规则1已经标记

            try:
                result = subprocess.run([
                    ffmpeg, "-y", "-i", vocals_path,
                    "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                    "-af", "astats=metadata=1:reset=1", "-f", "null", "-",
                ], capture_output=True, text=True, timeout=15,
                   encoding="utf-8", errors="replace")

                rms_peak = None
                rms_avg = None
                for line in result.stderr.split("\n"):
                    if "RMS peak dB" in line:
                        try:
                            rms_peak = float(line.split("=")[-1].strip())
                        except ValueError:
                            pass
                    if "RMS level dB" in line:
                        try:
                            rms_avg = float(line.split("=")[-1].strip())
                        except ValueError:
                            pass

                if rms_peak is not None and rms_avg is not None and (rms_peak - rms_avg) > 10:
                    ratio = 10 ** ((rms_peak - rms_avg) / 20)
                    if ratio > self.cfg.energy_spike_ratio:
                        issues.append(ScreeningIssue(
                            segment_id=seg.get("id", f"{seg.get('speaker')}_{seg.get('start')}"),
                            speaker_id=seg.get("speaker", "?"),
                            start_sec=start, end_sec=end,
                            rule="energy_spike",
                            severity="warning",
                            message=f"段落内能量脉冲 {(rms_peak - rms_avg):.1f}dB 峰均比 (x{ratio:.1f})，可能多人同时说话",
                            detail={"rms_peak_db": rms_peak, "rms_avg_db": rms_avg, "ratio": ratio},
                        ))
            except Exception:
                continue

        return issues


def screening_report(issues: list[ScreeningIssue]) -> dict:
    """将筛查问题列表转为可序列化的报告。"""
    by_severity: dict[str, list[dict]] = {"critical": [], "warning": []}
    for iss in issues:
        by_severity[iss.severity].append({
            "segment_id": iss.segment_id,
            "speaker_id": iss.speaker_id,
            "start": iss.start_sec,
            "end": iss.end_sec,
            "rule": iss.rule,
            "severity": iss.severity,
            "message": iss.message,
            "detail": iss.detail,
        })
    return {
        "total_issues": len(issues),
        "critical_count": len(by_severity["critical"]),
        "warning_count": len(by_severity["warning"]),
        "issues": issues,
    }
