"""
Fuse transcript.json + speaker_timeline.json → timeline.json (v2.0)

Reads transcript.json (read-only ASR data) and speaker_timeline.json (read-only
diarization data), splits long segments at speaker turn boundaries using word-level
timestamps, computes overlap intervals for partial overlaps, and writes the correct
timeline.json as the single source of truth.
"""
import json, os, sys
from datetime import datetime, timezone

def fuse(extract_dir: str) -> dict:
    with open(os.path.join(extract_dir, "transcript.json"), "r", encoding="utf-8") as f:
        tj = json.load(f)
    segments = tj.get("segments", [])

    with open(os.path.join(extract_dir, "speaker_timeline.json"), "r", encoding="utf-8") as f:
        stl = json.load(f)
    turns = stl.get("turns", [])
    speakers_raw = stl.get("speakers", [])

    normalized_turns = []
    for t in turns:
        spk = t.get("speaker", "")
        s = float(t.get("start", 0))
        e = float(t.get("end", 0))
        if spk and s < e:
            normalized_turns.append((spk, s, e))
    normalized_turns.sort(key=lambda x: x[1])

    events = []
    speakers_out = {}

    for si, seg in enumerate(segments):
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        words = seg.get("words", [])
        text = seg.get("text", "")
        translation = seg.get("translation", "")
        seg_id = seg.get("id") or f"seg_{si+1:03d}"

        overlapping_turns = []
        for spk, ts, te in normalized_turns:
            if ts < seg_end and te > seg_start:
                overlapping_turns.append((spk, ts, te))

        if not overlapping_turns:
            events.append(build_event(seg_id, seg_start, seg_end, text, translation,
                                       "UNKNOWN", words, []))
            continue

        # Merge adjacent turns of same speaker
        merged_turns = []
        for spk, ts, te in overlapping_turns:
            ts = max(ts, seg_start)
            te = min(te, seg_end)
            if merged_turns and merged_turns[-1][0] == spk and ts - merged_turns[-1][2] < 0.5:
                merged_turns[-1] = (spk, merged_turns[-1][1], te)
            else:
                merged_turns.append((spk, ts, te))

        # Split points at speaker boundaries
        boundaries = []
        for i in range(1, len(merged_turns)):
            mid = (merged_turns[i-1][2] + merged_turns[i][1]) / 2
            boundaries.append(mid)

        if not boundaries:
            best_spk = merged_turns[0][0]
            events.append(build_event(seg_id, seg_start, seg_end, text, translation,
                                       best_spk, words, []))
            if best_spk not in speakers_out:
                speakers_out[best_spk] = {"id": best_spk, "label": best_spk, "confidence": None, "embedding_ref": None}
            continue

        all_split_points = [seg_start] + boundaries + [seg_end]
        for i in range(len(all_split_points) - 1):
            sub_start = all_split_points[i]
            sub_end = all_split_points[i+1]

            best_spk, best_overlap = None, 0
            for spk, ts, te in overlapping_turns:
                overlap = min(sub_end, te) - max(sub_start, ts)
                if overlap > best_overlap:
                    best_overlap, best_spk = overlap, spk
            if not best_spk:
                best_spk = "UNKNOWN"

            # Assign words by midpoint
            sub_words = []
            sub_text_parts = []
            for w in words:
                w_mid = (w.get("start", 0) + w.get("end", 0)) / 2
                if sub_start <= w_mid < sub_end:
                    sub_words.append(w)
                    sub_text_parts.append(w.get("word", ""))

            sub_text = "".join(sub_text_parts) if sub_text_parts else text

            # Overlap intervals with other speakers
            overlap_intervals = []
            for spk2, ts2, te2 in overlapping_turns:
                if spk2 == best_spk:
                    continue
                o_start = max(sub_start, ts2)
                o_end = min(sub_end, te2)
                if o_end > o_start:
                    overlap_intervals.append({"start": round(o_start, 3), "end": round(o_end, 3)})

            sub_id = f"{seg_id}_{chr(97+i)}" if len(all_split_points) > 3 else seg_id
            events.append(build_event(sub_id, sub_start, sub_end, sub_text, translation,
                                       best_spk, sub_words, overlap_intervals))
            if best_spk not in speakers_out:
                speakers_out[best_spk] = {"id": best_spk, "label": best_spk, "confidence": None, "embedding_ref": None}

    for spk_data in speakers_raw:
        sid = spk_data.get("id", "")
        if sid and sid not in speakers_out:
            speakers_out[sid] = {"id": sid, "label": spk_data.get("name", sid),
                                  "confidence": None, "embedding_ref": None}

    # Load embeddings
    import glob as _glob
    emb_dir = os.path.join(os.path.dirname(extract_dir), "_embeddings")
    if os.path.isdir(emb_dir):
        import numpy as _np
        for npy_path in _glob.glob(os.path.join(emb_dir, "speaker_*.npy")):
            fname = os.path.basename(npy_path)
            sid = fname.replace("speaker_", "").replace(".npy", "")
            if sid in speakers_out:
                speakers_out[sid]["embedding_ref"] = npy_path
                try:
                    centroid = _np.load(npy_path)
                    speakers_out[sid]["centroid_norm"] = float(_np.linalg.norm(centroid))
                except Exception:
                    pass

    return {
        "schema_version": "2.0",
        "metadata": {
            "event_count": len(events),
            "speaker_count": len(speakers_out),
            "language": tj.get("language", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "events": events,
        "speakers": speakers_out,
    }


def build_event(eid, start, end, text, translation, speaker, words, overlap_intervals):
    evt = {
        "id": eid, "start": round(start, 3), "end": round(end, 3),
        "text": text, "speaker": speaker, "source": "asr", "confidence": 1.0,
    }
    if translation:
        if isinstance(translation, dict):
            evt["translation"] = translation
        elif isinstance(translation, str) and translation:
            evt["translation"] = {"text": translation}
    if words:
        evt["words"] = words
    if overlap_intervals:
        evt["overlap_intervals"] = overlap_intervals
    return evt


if __name__ == "__main__":
    ws = sys.argv[1] if len(sys.argv) > 1 else "D:/Workspace/Translate_video/source_file/Test_JP_project"
    extract_dir = os.path.join(ws, "01_extract")
    tl = fuse(extract_dir)
    tl_path = os.path.join(extract_dir, "timeline.json")
    if os.path.exists(tl_path):
        os.rename(tl_path, tl_path + ".bak")
        print(f"Backed up to {tl_path}.bak")
    with open(tl_path, "w", encoding="utf-8") as f:
        json.dump(tl, f, ensure_ascii=False, indent=2)
    print(f"timeline.json: {tl['metadata']['event_count']} events, {tl['metadata']['speaker_count']} speakers")
    n_overlap = sum(1 for e in tl["events"] if e.get("overlap_intervals"))
    print(f"With overlap_intervals: {n_overlap}")
