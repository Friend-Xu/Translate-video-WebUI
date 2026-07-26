"""
timeline_io — timeline.json 的唯一 canonical persist/load (数据结构重设计 Phase 2)

取代三处分散且格式不一致的实现:
  - tvw.py:_persist_timeline       (写 dict 译文, 无 project 块)
  - server.py:_persist_core_timeline (写 string 译文, 有 project 块, 已是死代码)
  - workflow_orchestrator reload   (只读 6 字段, 丢 translation/words → 毁译文)

设计: 以 Event 模型为干净中转, 互逆由 extract/apply + Event.from_dict 保证。
  extract_event:        乱态 slot (translation 三态 / audio_ref 顶层) → 干净 Event
  apply_event_to_state: 干净 Event → 乱态 slot (供现有 pass 消费)

磁盘格式: v2.0 (匹配前端 _load_timeline_v2 + 裸读取端, 避免破坏 WebUI)。
v3.0 原生格式连同前端读取端迁移一起留待 Phase 3。

禁止兜底: load 缺必填字段显式 raise; translation/words 缺失保持 None/[] 不臆造。
"""
from __future__ import annotations
import glob as _glob
import json
import os

from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.event_model import (
    Event, Word, Translation, TTSAudio, Review, Semantic,
)

TIMELINE_REL_PATH = os.path.join("01_extract", "timeline.json")


# ── 乱态 slot → 干净 Event ──────────────────────────────────

def _norm_words(raw: list) -> list[Word]:
    words = []
    for w in raw or []:
        if not isinstance(w, dict):
            continue
        words.append(Word(
            word=w.get("word", ""),
            start=float(w.get("start", 0.0)),
            end=float(w.get("end", 0.0)),
            confidence=w.get("confidence", w.get("score")),
        ))
    return words


def _extract_translation(es) -> Translation | None:
    """兼容 translation 三态: dict(含 text) / 纯字符串 / 空 (config-only)。"""
    raw = es.translation
    engine = es.provenance.get("translation_engine", "")
    if isinstance(raw, dict):
        text = raw.get("text", "")
        if not text:
            return None
        return Translation(
            text=text,
            engine=raw.get("engine", "") or engine,
            quality_score=raw.get("quality_score"),
            similarity=raw.get("similarity"),
        )
    if isinstance(raw, str) and raw:
        return Translation(text=raw, engine=engine)
    return None


def _extract_tts(es) -> TTSAudio | None:
    """audio_ref 可能在 derivatives 顶层 (patch _replace) 或 tts 槽。"""
    audio_ref = es.derivatives.get("audio_ref") or es.tts.get("audio_ref")
    if not audio_ref:
        return None
    duration = es.derivatives.get("duration") or es.tts.get("duration", 0.0)
    engine = es.derivatives.get("engine") or es.tts.get("engine", "")
    return TTSAudio(
        audio_path=audio_ref,
        duration=float(duration or 0.0),
        engine=engine or "",
        speed_factor=1.0,
        quality_score=es.provenance.get("tts_score"),
    )


def extract_event(es) -> Event:
    """从乱态 TimelineEventState 提取干净 Event (persist 用)。"""
    spk = es.ir.speaker_ref
    if not spk:
        spk_slot = es.speaker
        if isinstance(spk_slot, dict):
            spk = spk_slot.get("speaker_id")
    gate = es.provenance.get("gate_decision")
    review = Review(
        status=es.review.get("review_status", "pending"),
        flags=list(es.review.get("flags", [])),
        gate_decision=gate if gate in ("A", "B", "C") else None,
        notes=es.review.get("notes", ""),
    )
    return Event(
        id=es.id,
        start=es.start,
        end=es.end,
        text=es.ir.text_ref,
        source=es.ir.source,
        speaker=spk or None,
        confidence=float(es.provenance.get("confidence", 1.0)),
        words=_norm_words(es.asr.get("words", [])),
        semantic=Semantic(embedding_ref=es.semantic.get("embedding_ref", "") or ""),
        translation=_extract_translation(es),
        tts=_extract_tts(es),
        review=review,
    )


# ── 干净 Event → 乱态 slot (load 用) ────────────────────────

def apply_event_to_state(event: Event, state: TimelineProjectState) -> None:
    """把干净 Event 的数据填入 TimelineProjectState 的乱态 slot。

    填充目标与现有 pass 的读取端对齐:
      es.asr["words"]            ← asr_composite / speaker pass 读
      es._data["translation"]    ← tts pass .get("text") 读 (dict 态)
      es._data["audio_ref"]      ← video_export .derivatives.get("audio_ref") 读
      es.tts["audio_ref"]        ← tts pass skip 检查读
      es.speaker["speaker_id"]   ← speaker 相关读
      es.provenance[...]         ← confidence / gate_decision / translation_engine
      es.review[...]             ← review_status
    """
    es = state.get_event(event.id)
    if es is None:
        return
    es.asr["words"] = [w.to_dict() for w in event.words]
    if event.translation is not None:
        t = event.translation
        es._data["translation"] = {
            "text": t.text, "engine": t.engine,
            "quality_score": t.quality_score, "similarity": t.similarity,
            "config": {},
        }
        if t.engine:
            es.provenance["translation_engine"] = t.engine
    if event.tts is not None:
        es._data["audio_ref"] = event.tts.audio_path   # video_export 读顶层
        es.tts["audio_ref"] = event.tts.audio_path     # tts skip 检查读槽
        es.tts["duration"] = event.tts.duration
        es.tts["engine"] = event.tts.engine
    if event.speaker:
        es.speaker["speaker_id"] = event.speaker
    es.provenance["confidence"] = event.confidence
    es.review["review_status"] = event.review.status
    if event.review.gate_decision:
        es.provenance["gate_decision"] = event.review.gate_decision


# ── persist: state → timeline.json v2.0 (前端兼容) ────────────

def _event_to_v2_dict(e: Event) -> dict:
    """干净 Event → v2.0 event dict (匹配 _load_timeline_v2 + 前端裸读取端)。

    translation 写 dict (保留 engine/score), 前端 speaker_load 等
    以 isinstance(dict) → .get("text") 正确处理。
    """
    return {
        "id": e.id,
        "start": e.start,
        "end": e.end,
        "text": e.text,
        "translation": e.translation.to_dict() if e.translation else "",
        "speaker": e.speaker,
        "tts_voice_id": None,
        "confidence": e.confidence,
        "words": [w.to_dict() for w in e.words],
        "review_status": e.review.status,
        "patch_ids": [],
        "source": e.source,
        "overlap": None,
    }


def state_to_v2_dict(state: TimelineProjectState, project_id: str,
                     video_path: str, lang: str, ws_dir: str = "") -> dict:
    events = [extract_event(es) for es in state.sorted_events()]
    events.sort(key=lambda e: e.start)

    def _spk_entry(sid, name=None, conf=None, emb=""):
        return {"id": sid, "name": name or sid, "label": name or sid,
                "voice_id": None, "color": None, "is_locked": False,
                "embedding_ref": emb or "", "confidence": conf,
                "total_duration": None, "segment_count": None}

    speakers: dict[str, dict] = {}
    for e in events:
        if e.speaker and e.speaker not in speakers:
            speakers[e.speaker] = _spk_entry(e.speaker)
    for sid, node in state.ir.speakers.items():
        conf = getattr(node, "confidence", None)
        emb = getattr(node, "embedding_ref", None)
        nm = getattr(node, "name", None) or sid
        if sid not in speakers:
            speakers[sid] = _spk_entry(sid, nm, conf, emb or "")
        else:
            if conf is not None:
                speakers[sid]["confidence"] = conf
            if emb:
                speakers[sid]["embedding_ref"] = emb
    if ws_dir:
        emb_dir = os.path.join(ws_dir, "_embeddings")
        if os.path.isdir(emb_dir):
            for npy in _glob.glob(os.path.join(emb_dir, "speaker_*.npy")):
                sid = os.path.basename(npy)[len("speaker_"):-len(".npy")]
                if sid in speakers:
                    speakers[sid]["embedding_ref"] = npy

    total_dur = max((e.end for e in events), default=0.0)
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "2.0",
        "project": {"id": project_id, "source_video": video_path,
                    "source_lang": lang, "target_lang": "",
                    "created_at": now_iso, "updated_at": now_iso},
        "events": [_event_to_v2_dict(e) for e in events],
        "speakers": speakers,
        "metadata": {"total_duration": round(total_dur, 1),
                     "event_count": len(events),
                     "speaker_count": len(speakers),
                     "pipeline_version": "phase2"},
    }


def persist_state(state: TimelineProjectState, ws_dir: str, video_path: str,
                  lang: str, project_id: str = "") -> str:
    """将 TimelineProjectState 持久化为 timeline.json v2.0 (前端兼容)。返回路径。"""
    tl_path = os.path.join(ws_dir, TIMELINE_REL_PATH)
    os.makedirs(os.path.dirname(tl_path), exist_ok=True)
    pid = project_id or os.path.basename(ws_dir.rstrip("/\\"))
    data = state_to_v2_dict(state, pid, video_path, lang, ws_dir)
    with open(tl_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return tl_path


# ── load: timeline.json → state ─────────────────────────────

def load_state(path: str) -> TimelineProjectState:
    """从 timeline.json 重建 TimelineProjectState, 全字段回填 (含 translation/words)。

    禁止兜底: 文件缺失或缺必填字段显式 raise, 不静默返回空 state。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"load_state: timeline.json 不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    events_data = data.get("events", [])
    if isinstance(events_data, dict):
        events_data = list(events_data.values())

    ir_events: dict[str, TimelineEventIR] = {}
    ir_speakers: dict[str, SpeakerNodeIR] = {}
    clean_events: list[Event] = []

    for ev in events_data:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("id") or ev.get("event_id")
        if not eid:
            continue
        # 兼容 v2: translation 可能是 string, 归一为 dict
        ev = dict(ev)
        tr = ev.get("translation")
        if isinstance(tr, str):
            ev["translation"] = {"text": tr} if tr else None
        event = Event.from_dict(ev)   # 缺必填字段在此显式 raise
        clean_events.append(event)
        ir_events[eid] = TimelineEventIR(
            id=eid, start=event.start, end=event.end,
            speaker_ref=event.speaker, text_ref=event.text,
            source=event.source,
        )
        if event.speaker and event.speaker not in ir_speakers:
            ir_speakers[event.speaker] = SpeakerNodeIR(id=event.speaker)

    # speakers 注册表 (v3 speakers 块)
    for sid, s in (data.get("speakers") or {}).items():
        if sid not in ir_speakers:
            ir_speakers[sid] = SpeakerNodeIR(
                id=sid, name=s.get("label") or s.get("name"),
                embedding_ref=s.get("embedding_ref") or None,
                confidence=s.get("confidence"),
            )

    ir = TimelineProjectIR(events=ir_events, speakers=ir_speakers)
    state = TimelineProjectState(ir)
    for event in clean_events:
        apply_event_to_state(event, state)
    return state


def load_state_for_workspace(ws_dir: str) -> TimelineProjectState:
    """从工作区加载 timeline.json (orchestrator 续跑场景)。"""
    return load_state(os.path.join(ws_dir, TIMELINE_REL_PATH))
