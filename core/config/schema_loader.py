"""
SchemaLoader — JSON Schema 加载与校验 (定稿 §10.6)

从 schemas/ir_v2/ 目录加载各槽位的 config Schema，
提供 validate(slot, config) → (bool, str|None) 接口。
"""
from __future__ import annotations
import json
import os
from typing import Optional, Tuple


class SchemaLoader:
    """加载并缓存 JSON Schema 文件，提供配置校验。

    用法:
        loader = SchemaLoader("schemas/ir_v2/")
        ok, err = loader.validate("asr", {"model": "large-v3"})
    """

    # 槽位名 → Schema 文件名（不含扩展名）
    SLOT_TO_SCHEMA = {
        "audio": "audio_config",
        "asr": "asr_config",
        "speaker": "speaker_config",
        "semantic": "semantic_config",
        "translation": "translation_config",
        "tts_routing": "tts_config_routing",
        "tts_cosyvoice": "tts_config_cosyvoice",
        "tts_chattts": "tts_config_chattts",
        "tts_edge": "tts_config_edge",
        "emotion": "emotion_config",
    }

    def __init__(self, schema_dir: str):
        self._schema_dir = schema_dir
        self._cache: dict[str, dict] = {}

    def validate(self, slot: str, config: dict) -> Tuple[bool, Optional[str]]:
        """校验 config dict 是否符合 slot 的 Schema。

        Returns:
            (True, None) — 校验通过
            (False, error_msg) — 校验失败，error_msg 包含具体原因
        """
        import jsonschema

        schema = self._load_schema(slot)
        if schema is None:
            return False, f"Schema not found for slot: {slot}"

        try:
            jsonschema.validate(instance=config, schema=schema)
            return True, None
        except jsonschema.ValidationError as e:
            return False, str(e)
        except jsonschema.SchemaError as e:
            return False, f"Schema error: {e}"

    def get_schema(self, slot: str) -> dict | None:
        """获取指定槽位的 Schema dict（用于自省）。"""
        return self._load_schema(slot)

    def _load_schema(self, slot: str) -> dict | None:
        """加载并缓存 Schema 文件。"""
        if slot in self._cache:
            return self._cache[slot]

        filename = self.SLOT_TO_SCHEMA.get(slot)
        if filename is None:
            return None

        filepath = os.path.join(self._schema_dir, f"{filename}.schema.json")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            schema = json.load(f)

        self._cache[slot] = schema
        return schema
