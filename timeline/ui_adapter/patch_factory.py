"""patch_factory.py — WebUI parameter controls to Patch mapping (定稿 §11.4)."""
from __future__ import annotations
from core.runtime.patch import Patch, OpCode
import time, uuid

def _uid(p='patch'): return '%s_%s' % (p, uuid.uuid4().hex[:8])

def make_override_config(event_id, slot, field, value, author='user', base_version=-1):
    def _nest(path, v):
        parts = path.split('.')
        r = v
        for p in reversed(parts): r = {p: r}
        return r
    return Patch(id=_uid('override'), target_id=event_id, op=OpCode.OVERRIDE_CONFIG,
        value={'slot': slot, 'partial_config': _nest(field, value), 'base_version': base_version},
        timestamp=time.time(), author=author, confidence=1.0)

def make_set_config(event_id, slot, config_block, author='user'):
    return Patch(id=_uid('set'), target_id=event_id, op=OpCode.SET_CONFIG,
        value={'slot': slot, 'config_block': config_block}, timestamp=time.time(), author=author)

def make_reset_config(event_id, slot, fields=None, author='user'):
    val = {'slot': slot}
    if fields is not None: val['fields'] = fields
    return Patch(id=_uid('reset'), target_id=event_id, op=OpCode.RESET_CONFIG,
        value=val, timestamp=time.time(), author=author)

def make_batch_set_config(event_ids, slot, config_block, author='user'):
    return Patch(id=_uid('batch'), target_id=event_ids[0] if event_ids else '',
        op=OpCode.BATCH_SET_CONFIG, targets=event_ids,
        value={'slot': slot, 'config_block': config_block}, timestamp=time.time(), author=author)

def make_undo_patch(original, previous_state):
    from core.runtime.snapshot_manager import generate_undo_patch
    return generate_undo_patch(original, previous_state)
