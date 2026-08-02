"""
suggestion.opcode — 建议 patch 的 opcode 词表 (迁移自 timeline/patch/opcode)

大写词表由 GUI/patch_adapter._LEGACY_TO_OP 承接映射到 core OpCode —
保持大写不变量, 前端适配层零改动。
"""
from enum import Enum


class SuggestionOpCode(str, Enum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    RETAG_SPEAKER = "RETAG_SPEAKER"
    SET_TRANSLATION = "SET_TRANSLATION"
    RELINK_WORDS = "RELINK_WORDS"
    ANNOTATE = "ANNOTATE"
    RESIZE = "RESIZE"


def is_valid_opcode(op: str) -> bool:
    return op in {o.value for o in SuggestionOpCode}
