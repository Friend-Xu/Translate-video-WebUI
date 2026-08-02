"""
normalize_v1_timeline.py — 一次性迁移 v1 timeline.json → v2 (架构收束)

背景: extract_subtitles.py 旧提取链生成 v1 timeline.json ({version:"1.0", timeline:[]})。
架构收束后 v1 生成链退役, GUI 不再做运行时迁移 — 旧工作区用本脚本一次性迁移。

用法:
    python tools/normalize_v1_timeline.py --root <dir>        # 递归迁移目录下所有 timeline.json
    python tools/normalize_v1_timeline.py --root <dir> --dry-run   # 只报告不写
    python tools/normalize_v1_timeline.py --root <dir> --no-backup # 不写 .v1.bak

行为:
    - v2 (schema_version=="2.0") 文件原样跳过 (幂等)
    - v1 文件迁移后原子覆写, 原文件备份为 <path>.v1.bak
    - 既不是 v1 也不是 v2 的文件显式报错 (禁止兜底)
"""
from __future__ import annotations
import argparse
import json
import os


def is_v2(data: dict) -> bool:
    return data.get("schema_version") == "2.0"


def is_v1(data: dict) -> bool:
    return isinstance(data.get("timeline"), list)


def normalize_data(data: dict) -> dict:
    """v1 dict → v2 dict。字段映射与旧 server._load_timeline_v2 迁移分支一致。"""
    if is_v2(data):
        return data
    if not is_v1(data):
        raise ValueError(
            "既不是 v2 (schema_version=2.0) 也不是 v1 (timeline[]) 的 timeline.json"
        )

    events = []
    for seg in data.get("timeline", []):
        translation = seg.get("translation", "")
        if isinstance(translation, dict):
            translation = translation.get("text", "") or ""

        words = []
        for w in seg.get("words", []):
            words.append({
                "word": w.get("word", ""),
                "start": w.get("start", 0),
                "end": w.get("end", 0),
                "confidence": w.get("score") if w.get("score") is not None else w.get("confidence"),
            })

        events.append({
            "id": seg.get("id", ""),
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": seg.get("text", ""),
            "translation": translation,
            "speaker": seg.get("speaker"),
            "tts_voice_id": None,
            "confidence": 1.0,
            "words": words,
            "review_status": "pending",
            "patch_ids": [],
            "source": "asr",
            "overlap": seg.get("overlap") or None,
        })

    old_speaker_map = data.get("speaker_map", {})
    speakers = {}
    for sid, sm in old_speaker_map.items():
        speakers[sid] = {
            "id": sid,
            "name": sm.get("alias") or sm.get("name"),
            "voice_id": sm.get("voice_id"),
            "color": None,
            "is_locked": False,
            "total_duration": None,
            "segment_count": None,
        }

    old_metadata = data.get("metadata", {})
    total_dur = old_metadata.get("duration") or (
        max((e["end"] for e in events), default=0) if events else 0
    )
    return {
        "schema_version": "2.0",
        "project": {
            "id": "",
            "source_video": "",
            "source_lang": old_metadata.get("lang", ""),
            "target_lang": "",
            "created_at": None,
            "updated_at": None,
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


def normalize_file(path: str, backup: bool = True) -> bool:
    """迁移单个 timeline.json。返回是否发生迁移；v2 输入返回 False。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if is_v2(data):
        return False

    migrated = normalize_data(data)
    if backup:
        bak = path + ".v1.bak"
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(migrated, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return True


def scan_timeline_files(root: str) -> list[str]:
    """递归收集 root 下所有 timeline.json。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "__pycache__", ".git")]
        if "timeline.json" in filenames:
            found.append(os.path.join(dirpath, "timeline.json"))
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 v1 timeline.json 到 v2")
    parser.add_argument("--root", default=".", help="扫描根目录 (默认当前目录)")
    parser.add_argument("--dry-run", action="store_true", help="只报告不写文件")
    parser.add_argument("--no-backup", action="store_true", help="不写 .v1.bak 备份")
    args = parser.parse_args()

    files = scan_timeline_files(args.root)
    migrated, skipped, failed = [], [], []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if is_v2(data):
                skipped.append(path)
            elif args.dry_run:
                migrated.append(path)
            else:
                if normalize_file(path, backup=not args.no_backup):
                    migrated.append(path)
        except Exception as exc:
            failed.append((path, str(exc)))

    for path in migrated:
        print(f"[migrate] {path}")
    for path in skipped:
        print(f"[skip v2]  {path}")
    for path, err in failed:
        print(f"[FAILED]  {path}: {err}")
    print(f"\n迁移 {len(migrated)}, 跳过 {len(skipped)}, 失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
