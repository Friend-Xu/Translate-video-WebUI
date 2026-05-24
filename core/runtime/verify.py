"""
双写比对器 — 新旧系统输出 diff

在旧 pipeline 完全不变的前提下，运行新 runtime 并比对输出。
差异写入 timeline_diff.txt。行为等价时文件为空。
"""
from __future__ import annotations
import json
import os


def dual_write_verify(
    old_timeline,               # timeline.ir.TimelineIR (旧系统)
    segments: list[dict],        # 原始 ASR segments (转录结果)
    speaker_timeline: list | None,  # [(speaker_id, start, end, conf), ...]
    output_dir: str,
) -> dict:
    """并行运行新系统，双写输出并比对。

    Returns:
        {"status": "ok" | "diff" | "error", "diff_count": int, "diff_file": str}
    """
    try:
        new_output = _build_v2_output(segments, speaker_timeline)
        old_output = _extract_old_output(old_timeline)
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    diffs = _compare(old_output, new_output)
    diff_path = os.path.join(output_dir, "timeline_diff.txt")
    v2_path = os.path.join(output_dir, "timeline_v2.json")

    # 写 v2 影子输出
    with open(v2_path, "w", encoding="utf-8") as f:
        json.dump(new_output, f, ensure_ascii=False, indent=2)

    # 写差异报告
    with open(diff_path, "w", encoding="utf-8") as f:
        if diffs:
            for d in diffs:
                f.write(f"[{d['field']}] old={d['old']} new={d['new']}\n")
        else:
            f.write("# 行为等价 — 无差异\n")

    return {
        "status": "diff" if diffs else "ok",
        "diff_count": len(diffs),
        "diff_file": diff_path,
        "v2_file": v2_path,
    }


def _build_v2_output(segments: list[dict], speaker_timeline: list | None) -> dict:
    """用 core/ 新系统构建输出"""
    from core.ir import TimelineEventIR, SpeakerNodeIR, TimelineProjectIR
    from core.runtime import TimelineProjectState, SynthesisEngine

    # 收集 speaker
    speakers: dict[str, SpeakerNodeIR] = {}
    speaker_assignments = _build_speaker_map(segments, speaker_timeline)

    # 构建 events
    events: dict[str, TimelineEventIR] = {}
    for i, seg in enumerate(segments):
        eid = f"evt_{i + 1:03d}"
        spk = speaker_assignments.get(i) or seg.get("speaker")
        if spk and spk not in speakers:
            speakers[spk] = SpeakerNodeIR(id=spk)

        events[eid] = TimelineEventIR(
            id=eid,
            start=seg.get("start", 0.0),
            end=seg.get("end", 0.0),
            speaker_ref=spk,
            text_ref=seg.get("text", "").strip(),
            source="asr",
        )

    ir = TimelineProjectIR(events=events, speakers=speakers)
    state = TimelineProjectState(ir)
    engine = SynthesisEngine()
    rendered = engine.render_all(state)
    rendered_speakers = engine.render_speakers(state)

    return {
        "version": "2.0",
        "events": rendered,
        "speakers": rendered_speakers,
    }


def _build_speaker_map(
    segments: list[dict], speaker_timeline: list | None
) -> dict[int, str]:
    """根据 speaker_timeline 分配 speaker 到 segment 索引"""
    mapping: dict[int, str] = {}
    if not speaker_timeline:
        return mapping
    for i, seg in enumerate(segments):
        seg_mid = (seg.get("start", 0) + seg.get("end", 0)) / 2
        for spk_id, s_start, s_end, _ in speaker_timeline:
            if s_start <= seg_mid <= s_end:
                mapping[i] = spk_id
                break
    return mapping


def _extract_old_output(old_timeline) -> list[dict]:
    """从旧 TimelineIR 提取标准化输出"""
    result = []
    for seg in old_timeline.timeline:
        result.append({
            "id": seg.id,
            "start": seg.start,
            "end": seg.end,
            "speaker": seg.speaker,
            "text": seg.text,
            "source": "asr",
        })
    return result


def _compare(old: list[dict], new: dict) -> list[dict]:
    """比较旧输出和新系统的 events 列表"""
    diffs = []
    new_events = new.get("events", [])

    if len(old) != len(new_events):
        diffs.append({
            "field": "event_count",
            "old": len(old),
            "new": len(new_events),
        })
        return diffs

    for i, (o, n) in enumerate(zip(old, new_events)):
        for key in ("start", "end", "speaker", "text"):
            ov, nv = o.get(key), n.get(key)
            if isinstance(ov, float) and isinstance(nv, float):
                if abs(ov - nv) > 0.01:
                    diffs.append({
                        "field": f"events[{i}].{key}",
                        "old": ov,
                        "new": nv,
                    })
            elif ov != nv:
                diffs.append({
                    "field": f"events[{i}].{key}",
                    "old": ov,
                    "new": nv,
                })

    return diffs
