"""
Schema 验证工具 — 通用 JSON Schema 验证器 (设计文档 §9)
"""
from __future__ import annotations
import json
import os
from functools import lru_cache

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "schemas",
)

_SCHEMA_FILES = {
    "timeline": "timeline.schema.json",
    "timeline_v3": "timeline_v3.schema.json",
    "patch_log": "patch_log.schema.json",
    "export_config": "export_config.schema.json",
    "speaker_map": "speaker_map.schema.json",
}


@lru_cache(maxsize=16)
def _load_schema(name: str) -> dict | None:
    path = os.path.join(_SCHEMA_DIR, _SCHEMA_FILES.get(name, name))
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_json(data: dict, schema_name: str) -> tuple[bool, list[str]]:
    schema = _load_schema(schema_name)
    if schema is None:
        return False, [f"Schema not found: {schema_name}"]
    if not _HAS_JSONSCHEMA:
        return True, []
    validator = jsonschema.Draft7Validator(schema)
    errors = [e.message for e in validator.iter_errors(data)]
    return len(errors) == 0, errors


def assert_valid_timeline_v2(data: dict) -> None:
    ok, errs = validate_json(data, "timeline")
    if not ok:
        raise AssertionError("timeline v2 schema failed:\n" + "\n".join(errs))


def assert_valid_timeline_v3(data: dict) -> None:
    ok, errs = validate_json(data, "timeline_v3")
    if not ok:
        raise AssertionError("timeline v3 schema failed:\n" + "\n".join(errs))


def assert_valid_patch_log(data: dict) -> None:
    ok, errs = validate_json(data, "patch_log")
    if not ok:
        raise AssertionError("patch_log schema failed:\n" + "\n".join(errs))
