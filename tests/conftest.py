"""
Timeline 引擎测试 — 共享 Fixtures

为 core/ + timeline/ 模块的单元测试和集成测试提供模拟数据。
所有数据为纯内存构造，不依赖 GPU、模型或外部文件。
"""

import pytest
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR


# ── Core IR fixtures ───────────────────────────────────────

@pytest.fixture
def sample_events() -> dict[str, TimelineEventIR]:
    """3 个模拟事件，跨越 0.0-8.0s，2 个 speaker"""
    return {
        "evt_001": TimelineEventIR(
            id="evt_001", start=0.0, end=2.5,
            speaker_ref="SPEAKER_00", text_ref="Hello world",
        ),
        "evt_002": TimelineEventIR(
            id="evt_002", start=3.0, end=5.0,
            speaker_ref="SPEAKER_01", text_ref="How are you",
        ),
        "evt_003": TimelineEventIR(
            id="evt_003", start=5.5, end=8.0,
            speaker_ref="SPEAKER_00", text_ref="I'm fine",
        ),
    }


@pytest.fixture
def sample_speakers() -> dict[str, SpeakerNodeIR]:
    """2 个模拟说话人"""
    return {
        "SPEAKER_00": SpeakerNodeIR(id="SPEAKER_00", name="主持人"),
        "SPEAKER_01": SpeakerNodeIR(id="SPEAKER_01", name=None),
    }


@pytest.fixture
def sample_project(sample_events, sample_speakers) -> TimelineProjectIR:
    """模拟项目容器"""
    return TimelineProjectIR(events=sample_events, speakers=sample_speakers)


@pytest.fixture
def sample_project_state(sample_project) -> "TimelineProjectState":
    """从 sample_project 构建 TimelineProjectState"""
    from core.runtime.project_state import TimelineProjectState
    return TimelineProjectState(sample_project)


# ── ASR / Pipeline 模拟数据 ────────────────────────────────

@pytest.fixture
def sample_asr_segments() -> list[dict]:
    """模拟 ASR 输出 segments（3 个 segment，含 words）"""
    return [
        {
            "start": 0.0, "end": 2.5, "text": "Hello world",
            "speaker": "SPEAKER_00",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.8, "score": 0.95},
                {"word": "world", "start": 1.0, "end": 2.3, "score": 0.92},
            ],
        },
        {
            "start": 3.0, "end": 5.0, "text": "How are you",
            "speaker": "SPEAKER_01",
            "words": [
                {"word": "How", "start": 3.0, "end": 3.5},
                {"word": "are", "start": 3.6, "end": 4.0},
                {"word": "you", "start": 4.2, "end": 4.8},
            ],
        },
        {
            "start": 5.5, "end": 8.0, "text": "I'm fine",
            "speaker": "SPEAKER_00",
            "words": [
                {"word": "I'm", "start": 5.5, "end": 6.0},
                {"word": "fine", "start": 6.2, "end": 7.8},
            ],
        },
    ]


@pytest.fixture
def sample_speaker_timeline() -> list[tuple]:
    """模拟 pyannote speaker diarization 输出"""
    return [
        ("SPEAKER_00", 0.0, 2.5, 0.95),
        ("SPEAKER_01", 3.0, 5.0, 0.92),
        ("SPEAKER_00", 5.5, 8.0, 0.94),
    ]


# ── Timeline (旧版) fixtures ───────────────────────────────

@pytest.fixture
def sample_timeline_dicts() -> list[dict]:
    """模拟 timeline segment dicts（给 patch/apply 用）"""
    return [
        {
            "id": "seg_001", "type": "speech", "speaker": "SPEAKER_00",
            "start": 0.0, "end": 2.5, "text": "Hello world",
            "translation": "", "overlap": False,
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.8, "score": 0.95, "speaker": "SPEAKER_00"},
                {"word": "world", "start": 1.0, "end": 2.3, "score": 0.92, "speaker": "SPEAKER_00"},
            ],
        },
        {
            "id": "seg_002", "type": "speech", "speaker": "SPEAKER_01",
            "start": 3.0, "end": 5.0, "text": "How are you",
            "translation": "", "overlap": False,
            "words": [
                {"word": "How", "start": 3.0, "end": 3.5, "speaker": "SPEAKER_01"},
                {"word": "are", "start": 3.6, "end": 4.0, "speaker": "SPEAKER_01"},
                {"word": "you", "start": 4.2, "end": 4.8, "speaker": "SPEAKER_01"},
            ],
        },
        {
            "id": "seg_003", "type": "speech", "speaker": "SPEAKER_00",
            "start": 5.5, "end": 8.0, "text": "I'm fine",
            "translation": "", "overlap": False,
            "words": [
                {"word": "I'm", "start": 5.5, "end": 6.0, "speaker": "SPEAKER_00"},
                {"word": "fine", "start": 6.2, "end": 7.8, "speaker": "SPEAKER_00"},
            ],
        },
    ]


@pytest.fixture
def sample_timeline_ir(sample_timeline_dicts):
    """模拟 timeline.ir.TimelineIR（旧版）"""
    from timeline.ir import TimelineIR, TimelineSegment, TimelineWord, SpeakerMapEntry

    segments = []
    for d in sample_timeline_dicts:
        words = [TimelineWord.from_dict(w) for w in d.get("words", [])]
        segments.append(TimelineSegment(
            id=d["id"], type=d.get("type", "speech"),
            speaker=d.get("speaker"), start=d["start"], end=d["end"],
            text=d.get("text", ""), translation=d.get("translation", ""),
            overlap=d.get("overlap", False), words=words,
        ))

    return TimelineIR(
        audio_id="test_audio",
        version="1.0",
        timeline=segments,
        speaker_map={
            "SPEAKER_00": SpeakerMapEntry(alias="主持人"),
            "SPEAKER_01": SpeakerMapEntry(),
        },
        metadata={"lang": "en", "duration": 8.0},
    )
