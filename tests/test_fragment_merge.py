"""
时间戳幻觉碎片合并规则 — 独立测试

规则:
  1. 文本仅含数字/标点，长度 < 10 字符
  2. 与任何邻居段有时间重叠（start/end 被偷的证据）
  → 合并到前一段（whisper从前一段幻想了这个数字）

测试场景:
  A: end 被偷 (已知案例 "2025.")
  B: start 被偷 (start < prev.end)
  C: start 和 end 都被偷
  D: 正常短数字，不合并 (gap 正常，无重叠)
  E: 不是数字的短段，不合并
  F: 第一段就是碎片 (无前段可合并)

用法:
    .venv/Scripts/python tests/test_fragment_merge.py
"""
from __future__ import annotations
import re

_DIGIT_ONLY = re.compile(r'^[\d\s.,;:!?\'\"%$\-]+$')

def is_hallucinated_fragment(seg: dict) -> bool:
    text = seg['text'].strip()
    return bool(_DIGIT_ONLY.match(text)) and len(text) < 10

def has_overlap(a: dict, b: dict) -> bool:
    return a['start'] < b['end'] and b['start'] < a['end']

def merge_fragments(segments: list) -> list:
    result = []
    for curr in segments:
        s = dict(curr)  # copy
        prev = result[-1] if result else None

        is_frag = is_hallucinated_fragment(s)
        has_overlap = False

        # Check overlap with BOTH neighbors
        if prev and (prev['start'] < s['end'] and s['start'] < prev['end']):
            has_overlap = True
        # Check with next (peek ahead in original list)
        # We look ahead in the remaining segments
        remaining = segments[len(result):]
        if len(remaining) > 1:
            nxt = remaining[1]
            if s['start'] < nxt['end'] and nxt['start'] < s['end']:
                has_overlap = True

        if is_frag and has_overlap and prev:
            # Merge backward: use max(prev.end, frag.start) as merged end.
            # - If end was stolen: frag.start > prev.end → use frag.start (not stolen end)
            # - If start was stolen: frag.start < prev.end → keep prev.end (don't truncate)
            prev['end'] = max(prev['end'], s['start'])
            prev['start'] = min(prev['start'], s['start'])
            prev['text'] = prev['text'].rstrip() + ' ' + s['text'].strip()
            prev['words'] = prev.get('words', []) + s.get('words', [])
        else:
            result.append(s)
    return result


def test_a():
    """场景 A: end 被偷"""
    segs = [
        {'text': 'this time for October', 'start': 0.45, 'end': 6.49},
        {'text': '2025.', 'start': 7.11, 'end': 15.49},
        {'text': 'This list is heavy', 'start': 7.15, 'end': 15.49},
    ]
    r = merge_fragments(segs)
    assert len(r) == 2
    assert 'October 2025.' in r[0]['text']
    print('A PASS: end stolen → merged backward')

def test_b():
    """场景 B: start 被偷"""
    segs = [
        {'text': 'the total is', 'start': 10.0, 'end': 13.0},
        {'text': '42.', 'start': 12.0, 'end': 16.0},
        {'text': 'next chapter', 'start': 13.5, 'end': 18.0},
    ]
    r = merge_fragments(segs)
    assert len(r) == 2
    assert '42.' in r[0]['text']
    print('B PASS: start stolen → merged backward')

def test_c():
    """场景 C: 两端都被偷"""
    segs = [
        {'text': 'the score is', 'start': 5.0, 'end': 8.0},
        {'text': '100.', 'start': 7.0, 'end': 15.0},
        {'text': 'next topic', 'start': 10.0, 'end': 14.0},
    ]
    r = merge_fragments(segs)
    assert len(r) == 2
    assert r[0]['start'] == 5.0
    print('C PASS: both stolen → merged backward, start preserved')

def test_d():
    """场景 D: 正常短数字，无重叠 → 不合并"""
    segs = [
        {'text': 'the answer is', 'start': 0.0, 'end': 2.0},
        {'text': '7.', 'start': 2.5, 'end': 3.0},
        {'text': 'and we move on', 'start': 3.5, 'end': 6.0},
    ]
    r = merge_fragments(segs)
    assert len(r) == 3
    print('D PASS: normal digit → not merged')

def test_e():
    """场景 E: 非数字短段，有重叠 → 不合并"""
    segs = [
        {'text': 'let us begin', 'start': 0.0, 'end': 2.0},
        {'text': 'OK.', 'start': 1.5, 'end': 5.0},
        {'text': 'the first topic', 'start': 3.0, 'end': 7.0},
    ]
    r = merge_fragments(segs)
    assert len(r) == 3
    print('E PASS: non-digit fragment → not merged')

def test_f():
    """场景 F: 第一段就是碎片 → 无前段可合并"""
    segs = [
        {'text': '2025.', 'start': 0.0, 'end': 5.0},
        {'text': 'Welcome everyone', 'start': 2.0, 'end': 8.0},
    ]
    r = merge_fragments(segs)
    assert len(r) == 2
    print('F PASS: fragment at start → kept as-is')

def test_g():
    """场景 G: 真实 transcript 数据测试"""
    segs = [
        {'text': 'Hey there, it\'s Endiverse, we are back again with another '
                 '30 mods of the month, this time for October',
         'start': 0.45, 'end': 6.49},
        {'text': '2025.', 'start': 7.11, 'end': 15.49},
        {'text': 'This list is heavy with content mods and huge updates, '
                 'so sit tight and let\'s dive into the',
         'start': 7.15, 'end': 15.49},
        {'text': 'video.', 'start': 15.57, 'end': 15.76},
        {'text': 'Royal variations has been around for a while now.',
         'start': 18.91, 'end': 21.16},
        {'text': 'The idea of the mod was to add captain variations of '
                 'the hostile vanilla maps.',
         'start': 21.20, 'end': 25.68},
    ]
    r = merge_fragments(segs)
    # "2025." should merge into "October"
    has_2025 = any('2025' in s['text'] for s in r)
    october_with_2025 = any('October' in s['text'] and '2025' in s['text'] for s in r)
    print(f'G PASS: 2025 present={has_2025}, merged with October={october_with_2025}')
    for s in r:
        print(f'  [{s["start"]:.2f}-{s["end"]:.2f}] \"{s["text"][:70]}\"')
    assert october_with_2025, '2025 must be merged with October'
    assert not any(s['text'].strip() == '2025.' for s in r), '2025. should NOT be standalone'


if __name__ == '__main__':
    test_a()
    test_b()
    test_c()
    test_d()
    test_e()
    test_f()
    test_g()
    print('\nAll 7 tests passed')
