"""
Timeline Fusion — 从现有 pipeline 输出构建 TimelineIR

将 VAD、ASR、Alignment、Speaker 信息合并到统一 Timeline IR。
纯数据变换，零显存，不加载音频。
"""

from __future__ import annotations

from .ir import TimelineIR, TimelineSegment, TimelineWord, SpeakerMapEntry


def _make_segment_id(index: int) -> str:
    return f"seg_{index:03d}"


def from_extract_result(
    segments: list[dict],
    words: list[dict] | None = None,
    speaker_timeline: list | None = None,
    audio_id: str = "",
    metadata: dict | None = None,
) -> TimelineIR:
    """从 extract_subtitles 的 result["segments"] 构建 TimelineIR。

    Args:
        segments: transcript.json 的 segments 列表
        words: 全局 word 列表（可选，segments 的 words 已包含时忽略）
        speaker_timeline: [(speaker_id, start, end, confidence), ...] or None
        audio_id: 视频 stem 名称
        metadata: 额外元数据 (lang, duration, sample_rate, ...)
    """
    timeline_segments: list[TimelineSegment] = []
    speaker_ids: set[str] = set()

    for i, seg in enumerate(segments):
        seg_words = [
            TimelineWord(
                word=w.get("word", "").strip(),
                start=w.get("start", 0.0),
                end=w.get("end", 0.0),
                score=w.get("score", 1.0),
                speaker=w.get("speaker"),
            )
            for w in seg.get("words", [])
        ]

        speaker = seg.get("speaker")
        if speaker:
            speaker_ids.add(speaker)

        ts = TimelineSegment(
            id=_make_segment_id(i + 1),
            type="speech",
            speaker=speaker,
            start=seg.get("start", 0.0),
            end=seg.get("end", 0.0),
            text=seg.get("text", "").strip(),
            translation="",
            overlap=False,
            words=seg_words,
        )
        timeline_segments.append(ts)

    # 如果还传了全局 words（segment words 为空时兜底）
    if words and not any(ts.words for ts in timeline_segments):
        for w in words:
            w_spk = w.get("speaker")
            if w_spk:
                speaker_ids.add(w_spk)

    # 构建 speaker_map
    speaker_map: dict[str, SpeakerMapEntry] = {}
    for spk in sorted(speaker_ids):
        speaker_map[spk] = SpeakerMapEntry()

    # 检测 overlap
    _mark_overlaps(timeline_segments)

    return TimelineIR(
        audio_id=audio_id,
        version="1.0",
        timeline=timeline_segments,
        speaker_map=speaker_map,
        metadata=metadata or {},
    )


def _mark_overlaps(segments: list[TimelineSegment]) -> None:
    """检测并标记重叠 segment。相邻段跨 speaker 且时间交集即标记。"""
    for i in range(len(segments) - 1):
        a, b = segments[i], segments[i + 1]
        if a.end > b.start and a.speaker != b.speaker:
            a.overlap = True
            b.overlap = True


# ── Migration Layer ───────────────────────────────────────

def to_project_ir(timeline_ir: TimelineIR):
    """旧 IR → 新 IR 深度迁移。"""
    from core.ir.timeline_event import TimelineEventIR as NewEvent
    from core.ir.speaker import SpeakerNodeIR
    from core.ir.project import TimelineProjectIR

    events: dict[str, NewEvent] = {}
    speakers: dict[str, SpeakerNodeIR] = {}

    for i, seg in enumerate(timeline_ir.timeline):
        eid = seg.id if seg.id else f"evt_{i + 1:03d}"
        spk = seg.speaker
        if spk and spk not in speakers:
            entry = timeline_ir.speaker_map.get(spk)
            name = entry.alias if entry and entry.alias else None
            speakers[spk] = SpeakerNodeIR(id=spk, name=name)

        events[eid] = NewEvent(
            id=eid, start=seg.start, end=seg.end,
            speaker_ref=spk, text_ref=seg.text, source="asr",
        )

    metadata = dict(timeline_ir.metadata)
    metadata.setdefault("_migrated_from", "timeline.ir")

    return TimelineProjectIR(events=events, speakers=speakers)


def from_project_ir(project_ir) -> TimelineIR:
    """新 IR → 旧 IR 反向迁移。"""
    segments = []
    speaker_ids = set()

    for evt in project_ir.event_list:
        spk = evt.speaker_ref
        seg = TimelineSegment(
            id=evt.id, type="speech", speaker=spk,
            start=evt.start, end=evt.end, text=evt.text_ref,
            translation="", overlap=False, words=[],
        )
        segments.append(seg)
        if spk:
            speaker_ids.add(spk)

    speaker_map = {}
    for spk_id in speaker_ids:
        spk_ir = project_ir.speakers.get(spk_id)
        alias = spk_ir.name if spk_ir and spk_ir.name else ""
        speaker_map[spk_id] = SpeakerMapEntry(alias=alias)

    audio_id = "migrated"
    return TimelineIR(
        audio_id=audio_id, version="1.0",
        timeline=segments, speaker_map=speaker_map,
        metadata={},
    )
