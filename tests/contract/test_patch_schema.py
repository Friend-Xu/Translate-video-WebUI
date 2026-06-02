"""
Schema 契约测试 — patch_log.schema.json v3.0 (批次7)
"""
import pytest
from datetime import datetime, timezone
from core.runtime.patch import Patch, OpCode
from core.testing.schema_validator import validate_json


@pytest.mark.schema
class TestPatchLogSchema:

    def _patch_to_dict(self, p: Patch) -> dict:
        return {
            "patch_id": p.id, "opcode": str(p.op),
            "targets": [p.target_id], "author": p.author,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "applied",
        }

    def test_all_opcodes_valid(self):
        patches = []
        for i, op in enumerate(OpCode):
            p = Patch(id=f"p_{i}", target_id="evt_001", op=op.name.lower(),
                      value={}, author="system")
            patches.append(self._patch_to_dict(p))
        data = {"schema_version": "3.0", "patches": patches}
        ok, errs = validate_json(data, "patch_log")
        assert ok, f"All OpCodes valid: {errs[:3]}"

    def test_minimal_patch_valid(self):
        data = {
            "schema_version": "3.0",
            "patches": [{
                "patch_id": "p1", "opcode": "SET_TRANSLATION",
                "targets": ["evt_001"], "author": "system",
                "timestamp": datetime.now(timezone.utc).isoformat(), "status": "applied",
            }],
        }
        ok, errs = validate_json(data, "patch_log")
        assert ok, f"Minimal: {errs}"

    def test_missing_opcode_fails(self):
        data = {
            "schema_version": "3.0",
            "patches": [{"patch_id": "p1", "targets": ["e1"], "author": "system",
                         "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        ok, _ = validate_json(data, "patch_log")
        assert not ok

    def test_invalid_opcode_fails(self):
        data = {
            "schema_version": "3.0",
            "patches": [{"patch_id": "p1", "opcode": "INVALID_OP",
                         "targets": ["e1"], "author": "system",
                         "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        ok, _ = validate_json(data, "patch_log")
        assert not ok
