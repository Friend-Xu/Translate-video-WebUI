"""
TASK 02 — Opcode System

Six fixed opcodes. No dynamic opcodes allowed.
"""
from enum import Enum


class OpCode(str, Enum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    RETAG_SPEAKER = "RETAG_SPEAKER"
    SET_TRANSLATION = "SET_TRANSLATION"
    RELINK_WORDS = "RELINK_WORDS"
    ANNOTATE = "ANNOTATE"


PAYLOAD_SCHEMA = {
    OpCode.MERGE: {"required": [], "optional": ["gap_threshold"]},
    OpCode.SPLIT: {"required": ["split_point"], "optional": []},
    OpCode.RETAG_SPEAKER: {"required": ["new_speaker"], "optional": []},
    OpCode.SET_TRANSLATION: {"required": ["translation"], "optional": []},
    OpCode.RELINK_WORDS: {"required": ["word_mapping"], "optional": []},
    OpCode.ANNOTATE: {"required": ["key", "value"], "optional": []},
}


def is_valid_opcode(op: str) -> bool:
    return op in {o.value for o in OpCode}
