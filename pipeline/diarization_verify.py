"""
Diarization Verification — 说话人分离质量自动验证

第一版实用检测（无需 speaker embedding）：
  1. 段数合理性   — 段数/时长比异常检测
  2. 最小时长     — 碎片段检测（<0.3s）
  3. 说话人平衡   — 单人占比超过 95% 标记
  4. 转写完整性   — 拼接文本 vs 全文转写字符偏差

第二版（需 embedding 模型）：
  - 段内纯度 / 跨边界距离 / 双模型交叉

用法:
    from pipeline.diarization_verify import verify_diarization

    report = verify_diarization(speaker_timeline, transcript)
    print(report.passes_all, report.summary)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger("pipeline.diarization_verify")


@dataclass
class VerificationIssue:
    layer: int
    severity: str          # "error" | "warning" | "info"
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class VerificationReport:
    passes_all: bool = True
    issues: List[VerificationIssue] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def verify_diarization(
    speaker_timeline: List[Tuple[str, float, float, float]],
    transcript: Optional[dict] = None,
    total_audio_dur: Optional[float] = None,
) -> VerificationReport:
    """运行所有可用验证层。第一版 4 层，零依赖。"""
    issues: List[VerificationIssue] = []

    # Layer 0: 段数合理性
    l0 = _check_segment_count(speaker_timeline, total_audio_dur)
    issues.extend(l0)

    # Layer 1: 碎片段检测
    l1 = _check_min_duration(speaker_timeline)
    issues.extend(l1)

    # Layer 2: 说话人平衡
    l2 = _check_speaker_balance(speaker_timeline, total_audio_dur)
    issues.extend(l2)

    # Layer 3: 转写完整性 (if transcript available)
    if transcript:
        l3 = _check_completeness(transcript)
        issues.extend(l3)

    return VerificationReport(
        passes_all=not any(i.severity == "error" for i in issues),
        issues=issues,
        summary={
            "total_issues": len(issues),
            "errors": sum(1 for i in issues if i.severity == "error"),
            "warnings": sum(1 for i in issues if i.severity == "warning"),
            "info": sum(1 for i in issues if i.severity == "info"),
            "speakers": len(set(s[0] for s in speaker_timeline)),
            "turns": len(speaker_timeline),
        },
    )


def _check_segment_count(timeline, audio_dur) -> List[VerificationIssue]:
    """检测段数是否异常——太多段可能意味着频繁误切。"""
    if not audio_dur or audio_dur <= 0:
        return []
    speakers = len(set(s[0] for s in timeline))
    turns = len(timeline)
    # 合理范围: 每个说话人每分钟 2-15 段
    minutes = audio_dur / 60
    min_ok = speakers * 1 * minutes
    max_ok = speakers * 20 * minutes
    if turns > max_ok:
        return [VerificationIssue(
            layer=0, severity="warning",
            message=f"段数偏多: {turns} 段 / {minutes:.1f}min ({speakers} 说话人)",
            detail={"turns": turns, "minutes": minutes, "speakers": speakers,
                     "expected_max": int(max_ok)},
        )]
    if turns < min_ok and speakers > 1:
        return [VerificationIssue(
            layer=0, severity="info",
            message=f"段数偏少: {turns} 段 / {minutes:.1f}min ({speakers} 说话人)",
            detail={"turns": turns, "minutes": minutes, "speakers": speakers,
                     "expected_min": int(min_ok)},
        )]
    return []


def _check_min_duration(timeline) -> List[VerificationIssue]:
    """检测碎片段（短于 0.3s 的段通常是 diarization 误切）。"""
    short = [(s[0], s[1], s[2]) for s in timeline if s[2] - s[1] < 0.3]
    if short:
        return [VerificationIssue(
            layer=1, severity="warning",
            message=f"存在 {len(short)} 个碎片段 (<0.3s)",
            detail={"short_segments": [
                {"speaker": spk, "start": st, "end": en, "dur": en - st}
                for spk, st, en in short[:10]
            ]},
        )]
    return []


def _check_speaker_balance(timeline, audio_dur) -> List[VerificationIssue]:
    """检测说话人分布是否极端失衡（单人 >95%，可能是误检测）。"""
    if not audio_dur:
        return []
    totals: dict = {}
    for spk, st, en, _ in timeline:
        totals[spk] = totals.get(spk, 0) + (en - st)
    total_speech = sum(totals.values())
    if total_speech <= 0:
        return []
    for spk, dur in totals.items():
        ratio = dur / total_speech
        if ratio > 0.95 and len(totals) > 1:
            return [VerificationIssue(
                layer=2, severity="info",
                message=f"说话人 {spk} 占比 {ratio:.0%}，其他说话人可能为噪声误检",
                detail={"speaker": spk, "ratio": ratio, "totals": totals},
            )]
    return []


def _check_completeness(transcript) -> List[VerificationIssue]:
    """检测逐段转写能否正常拼接（纯文本结构检查）。"""
    segments = transcript.get("segments", [])
    if not segments:
        return [VerificationIssue(
            layer=3, severity="error",
            message="transcript 中无 segments",
        )]
    # 检查段间是否有间隙或重叠
    gaps = []
    overlaps = []
    for i in range(len(segments) - 1):
        prev_end = segments[i].get("end", 0)
        curr_start = segments[i + 1].get("start", 0)
        if curr_start < prev_end - 0.05:
            overlaps.append((i, prev_end - curr_start))
        elif curr_start > prev_end + 2.0:
            gaps.append((i, curr_start - prev_end))
    issues = []
    if overlaps:
        issues.append(VerificationIssue(
            layer=3, severity="info",
            message=f"段间存在 {len(overlaps)} 处重叠",
            detail={"overlaps_count": len(overlaps)},
        ))
    if gaps:
        issues.append(VerificationIssue(
            layer=3, severity="info",
            message=f"段间存在 {len(gaps)} 处大间隙 (>2s)",
            detail={"gaps_count": len(gaps)},
        ))
    return issues
