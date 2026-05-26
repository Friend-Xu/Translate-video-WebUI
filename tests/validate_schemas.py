"""
validate_schemas.py — 验证现有 JSON 工件是否符合 schemas/ 中的 JSON Schema。

用法: .venv/Scripts/python tests/validate_schemas.py [workspace_dir]

不指定参数时，只验证 schemas/ 自身的语法正确性。
指定 workspace_dir 时，额外验证该目录下的 timeline.json、speaker_map.json 等工件。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("请安装 jsonschema: .venv/Scripts/pip install jsonschema --target _deps/Lib/site-packages")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = PROJECT_ROOT / "schemas"

SCHEMA_FILES = {
    "timeline": "timeline.schema.json",
    "speaker_map": "speaker_map.schema.json",
    "patch_log": "patch_log.schema.json",
    "export_config": "export_config.schema.json",
}


def load_schemas() -> dict[str, dict]:
    """加载所有 schema 文件并验证语法正确性。"""
    schemas = {}
    for name, filename in SCHEMA_FILES.items():
        path = SCHEMAS_DIR / filename
        if not path.is_file():
            print(f"[WARN] Schema 文件不存在: {path}")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                schema = json.load(f)
            assert "$schema" in schema, f"{filename}: 缺少 $schema"
            assert "type" in schema, f"{filename}: 缺少 type"
            assert "$defs" in schema or "properties" in schema, f"{filename}: 缺少 $defs 或 properties"
            schemas[name] = schema
            print(f"[OK] Schema 语法正确: {filename}")
        except json.JSONDecodeError as e:
            print(f"[FAIL] {filename} JSON 语法错误: {e}")
        except AssertionError as e:
            print(f"[FAIL] {filename}: {e}")
    return schemas


def validate_artifact(schema: dict, artifact_path: Path, label: str) -> bool:
    """验证单个 JSON 工件是否符合 schema。"""
    if not artifact_path.is_file():
        print(f"[SKIP] 工件不存在: {artifact_path}")
        return True
    try:
        with open(artifact_path, encoding="utf-8") as f:
            data = json.load(f)
        jsonschema.validate(data, schema)
        print(f"[OK] {label} 通过验证: {artifact_path.name}")
        return True
    except json.JSONDecodeError as e:
        print(f"[FAIL] {label} JSON 语法错误: {e}")
        return False
    except jsonschema.ValidationError as e:
        print(f"[FAIL] {label} Schema 验证失败:")
        print(f"       路径: {'/'.join(str(p) for p in e.absolute_path)}")
        print(f"       消息: {e.message}")
        return False


def main() -> int:
    print("=" * 60)
    print("JSON Schema 验证")
    print(f"Schema 目录: {SCHEMAS_DIR}")
    print("=" * 60)

    schemas = load_schemas()
    if not schemas:
        print("\n没有可用的 schema 文件。")
        return 1

    if len(sys.argv) > 1:
        ws = Path(sys.argv[1])
        if not ws.is_dir():
            print(f"[FAIL] 工作目录不存在: {ws}")
            return 1

        print(f"\n验证工作目录: {ws}")
        artifacts: dict[str, list[tuple[Path, str]]] = {
            "timeline": [(ws / "01_extract" / "timeline.json", "timeline (extract)")],
            "speaker_map": [(ws / "03_speaker" / "speaker_map.json", "speaker_map")],
            "patch_log": [(ws / "04_patch" / "timeline_patches.json", "patch_log")],
        }

        all_ok = True
        for schema_name, paths in artifacts.items():
            schema = schemas.get(schema_name)
            if not schema:
                continue
            for artifact_path, label in paths:
                if not validate_artifact(schema, artifact_path, label):
                    all_ok = False

        if all_ok:
            print(f"\n{'=' * 60}")
            print("全部验证通过.")
        else:
            print(f"\n{'=' * 60}")
            print("存在验证失败项。")
            return 1
        return 0
    else:
        print(f"\n未指定 workspace，只验证 schema 语法。")
        print("指定 workspace 以验证工件: python tests/validate_schemas.py <workspace_dir>")
        return 0


if __name__ == "__main__":
    sys.exit(main())
