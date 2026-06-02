"""
Old workspace → Timeline IR 自动导入器 (计划 §11.7)

检测旧格式 workspace (无 timeline.json) 并从 transcript.json、
speaker_timeline.json、machine.srt 自动构建 Timeline IR v2.0。
"""
from __future__ import annotations
import json as _json
import os


def import_workspace_to_timeline(ws_dir: str) -> dict | None:
    """从旧 workspace 自动生成 timeline.json。返回 None 表示已有。"""
    extract_dir = os.path.join(ws_dir, "01_extract")
    if not os.path.isdir(extract_dir):
        return None

    tl_path = os.path.join(extract_dir, "timeline.json")
    if os.path.isfile(tl_path):
        return None

    transcript_path = os.path.join(extract_dir, "transcript.json")
    if not os.path.isfile(transcript_path):
        return None

    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = _json.load(f)

    segments = transcript.get("segments", [])
    lang = transcript.get("language", "")

    events = []
    for seg in segments:
        translation = seg.get("translation", "")
        if isinstance(translation, dict):
            translation = translation.get("text", "") or ""

        words = []
        for w in seg.get("words", []):
            words.append({
                "word": w.get("word", ""),
                "start": w.get("start", 0),
                "end": w.get("end", 0),
                "confidence": w.get("score") or w.get("confidence"),
            })

        events.append({
            "id": seg.get("id", ""),
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": seg.get("text", ""),
            "translation": translation,
            "speaker": seg.get("speaker"),
            "tts_voice_id": None,
            "confidence": seg.get("confidence", 1.0),
            "words": words,
            "review_status": "pending",
            "patch_ids": [],
            "source": "asr",
        })

    # Build speakers from speaker_timeline.json
    speakers = {}
    stl_path = os.path.join(extract_dir, "speaker_timeline.json")
    if os.path.isfile(stl_path):
        with open(stl_path, "r", encoding="utf-8") as f:
            stl = _json.load(f)
        for s in stl.get("speakers", []):
            sid = s.get("id", s.get("speaker", ""))
            if sid:
                speakers[sid] = {
                    "id": sid, "name": s.get("name", sid),
                    "voice_id": s.get("voice_id"),
                    "color": s.get("color"), "is_locked": False,
                }

    # Inject translation from machine.srt
    translate_dir = os.path.join(ws_dir, "02_translate")
    machine_srt = os.path.join(translate_dir, "machine.srt")
    if os.path.isfile(machine_srt) and not any(e.get("translation") for e in events):
        try:
            from SRT.SRT_to_dict import srt_to_dict
            srt_list = srt_to_dict(machine_srt)
            for idx, entry in enumerate(srt_list):
                if idx < len(events):
                    events[idx]["translation"] = entry.get("text", "")
        except Exception:
            pass

    total_dur = max((e["end"] for e in events), default=0)

    timeline = {
        "schema_version": "2.0",
        "project": {
            "id": os.path.basename(ws_dir),
            "source_video": "", "source_lang": lang, "target_lang": "",
        },
        "events": events,
        "speakers": speakers,
        "metadata": {
            "total_duration": round(total_dur, 1),
            "event_count": len(events),
            "speaker_count": len(speakers),
            "pipeline_version": "legacy",
        },
    }

    os.makedirs(extract_dir, exist_ok=True)
    with open(tl_path, "w", encoding="utf-8") as f:
        _json.dump(timeline, f, ensure_ascii=False, indent=2)

    return timeline


def import_and_get_summary(ws_dir: str) -> dict:
    tl = import_workspace_to_timeline(ws_dir)
    if tl is None:
        tl_path = os.path.join(ws_dir, "01_extract", "timeline.json")
        if os.path.isfile(tl_path):
            with open(tl_path, "r", encoding="utf-8") as f:
                tl = _json.load(f)

    if tl is None:
        return {"status": "no_timeline"}

    return {
        "status": "ok",
        "schema_version": tl.get("schema_version"),
        "event_count": len(tl.get("events", [])),
        "speaker_count": len(tl.get("speakers", {})),
        "total_duration": tl.get("metadata", {}).get("total_duration", 0),
    }
