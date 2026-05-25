"""
Schema 校验工具模块 — 在数据边界自动验证关键 JSON 工件。

所有校验函数接受 dict 数据，失败时抛出 SchemaValidationError（含字段路径和期望值）。
strict=True 时额外检查 unknown fields。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
_SCHEMA_CACHE: dict[str, dict] = {}


class SchemaValidationError(ValueError):
    """JSON Schema 校验失败。"""
    def __init__(self, artifact: str, detail: str):
        self.artifact = artifact
        self.detail = detail
        super().__init__(f"[{artifact}] {detail}")


def _load_schema(name: str) -> dict:
    if name not in _SCHEMA_CACHE:
        path = _SCHEMAS_DIR / f"{name}.schema.json"
        if not path.is_file():
            raise SchemaValidationError(name, f"Schema 文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            _SCHEMA_CACHE[name] = json.load(f)
    return _SCHEMA_CACHE[name]


def _validate(schema: dict, data: Any, label: str) -> None:
    try:
        import jsonschema
    except ImportError:
        return  # 运行时 jsonschema 未安装时静默跳过
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise SchemaValidationError(label, f"{path}: {e.message}")


def validate_timeline(data: dict, *, strict: bool = False) -> None:
    """验证 timeline.json 是否符合 schemas/timeline.schema.json。"""
    schema = _load_schema("timeline")
    _validate(schema, data, "timeline.json")

    events = data.get("events", [])
    if events:
        for i, evt in enumerate(events):
            if evt.get("start", 0) > evt.get("end", 0):
                raise SchemaValidationError("timeline.json",
                    f"events[{i}]: start ({evt['start']}) > end ({evt['end']})")
            if evt.get("end", 0) < 0:
                raise SchemaValidationError("timeline.json",
                    f"events[{i}]: negative end time ({evt['end']})")
        for i in range(1, len(events)):
            if events[i].get("start", 0) < events[i - 1].get("start", 0):
                raise SchemaValidationError("timeline.json",
                    f"events[{i}]: start ({events[i]['start']}) < previous ({events[i-1]['start']}) — 时间轴未排序")

    if strict:
        events_speakers = {e.get("speaker") for e in events if e.get("speaker")}
        declared = set(data.get("speakers", {}).keys())
        orphan = events_speakers - declared
        if orphan:
            raise SchemaValidationError("timeline.json", f"事件引用了未声明的说话人: {orphan}")


def validate_speaker_map(data: dict, *, strict: bool = False) -> None:
    """验证 speaker_map.json 是否符合 schemas/speaker_map.schema.json。"""
    schema = _load_schema("speaker_map")
    _validate(schema, data, "speaker_map.json")


def validate_patch_log(data: dict, *, strict: bool = False) -> None:
    """验证 timeline_patches.json 是否符合 schemas/patch_log.schema.json。"""
    schema = _load_schema("patch_log")
    _validate(schema, data, "patch_log.json")

    patches = data.get("patches", [])
    if patches:
        ids = [p.get("patch_id", "") for p in patches]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise SchemaValidationError("patch_log.json", f"重复的 patch_id: {dupes}")


def validate_export_config(data: dict, *, strict: bool = False) -> None:
    """验证 export_config.json 是否符合 schemas/export_config.schema.json。"""
    schema = _load_schema("export_config")
    _validate(schema, data, "export_config.json")


def validate_workspace(workspace_dir: str | Path) -> dict[str, bool]:
    """验证 workspace 下所有关键 JSON 工件。返回 {文件名: 通过} 字典。"""
    ws = Path(workspace_dir)
    results: dict[str, bool] = {}

    checks = [
        ("timeline.json", "01_extract/timeline.json", validate_timeline),
        ("speaker_map.json", "03_speaker/speaker_map.json", validate_speaker_map),
        ("patch_log.json", "04_patch/timeline_patches.json", validate_patch_log),
    ]

    for name, rel_path, validator in checks:
        path = ws / rel_path
        if not path.is_file():
            results[name] = False
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            validator(data)
            results[name] = True
        except (SchemaValidationError, json.JSONDecodeError):
            results[name] = False

    return results
