"""
日语字幕处理器 — 基于 segment 时间戳 + MeCab 分词边界切分

注意：whisperX 对日语的"词级"时间戳是按单个字符拆分的，
且时间分配极不均匀（一个假名可能占数秒），因此不依赖逐字符时间戳。
策略：在 segment 级别做断句，segment 内部先用 MeCab 分词，
按词汇边界 + 时长/字符数限制进行切分。

依赖：
  - fugashi + ipadic（MeCab 分词，运行时可选）
"""

import os
import logging

from Json_Convert_Srt import seconds_to_srt_time


class JapaneseProcessor:
    """日语字幕处理器 — 基于 segment 时间戳 + MeCab 分词边界切分"""

    def __init__(self, max_duration=5.0, max_chars=35, min_duration=0.8):
        self.srt_entries = []
        self.entry_count = 1
        # 日语结束标点
        self.sentence_end_punctuation = {'。', '？', '！', '?', '!', '…', '」', '』'}
        # 控制参数
        self.max_duration = max_duration      # 单段最大时长（秒）
        self.max_chars = max_chars            # 单段最大字符数（日语字符更宽）
        self.min_duration = min_duration      # 最小持续时间（秒）
        # MeCab 分词器（延迟初始化）
        self._tagger = None

    @staticmethod
    def _interpolate_word_timestamps(words: list, seg_start: float, seg_end: float):
        """Fill missing start/end timestamps by interpolating between neighbors.

        When whisper/wav2vec2 skips tokens like numbers, the resulting gaps
        cause _split_by_word_gaps to misidentify split points because every
        untimestamped character inherits the full segment boundaries.
        """
        if not words:
            return

        n = len(words)
        i = 0
        while i < n:
            w = words[i]
            if w.get("start") is not None and w.get("end") is not None:
                i += 1
                continue

            run_start = i
            prev_end = words[run_start - 1].get("end") if run_start > 0 else None

            run_end = run_start
            while run_end < n:
                w2 = words[run_end]
                if w2.get("start") is not None and w2.get("end") is not None:
                    break
                run_end += 1

            next_start = words[run_end].get("start") if run_end < n else None

            gap_start = seg_start if prev_end is None else prev_end
            gap_end = seg_end if next_start is None else next_start
            gap_duration = max(gap_end - gap_start, 0.0)

            run_words = words[run_start:run_end]
            total_chars = sum(len(w.get("word", "")) for w in run_words)
            if total_chars == 0:
                total_chars = len(run_words)

            elapsed = gap_start
            for w in run_words:
                char_ratio = len(w.get("word", "")) / total_chars
                w_dur = gap_duration * char_ratio
                w["start"] = round(elapsed, 3)
                w["end"] = round(elapsed + w_dur, 3)
                elapsed += w_dur

            i = run_end

    def _get_tagger(self):
        """延迟初始化 MeCab 分词器，失败返回 None"""
        if self._tagger is not None:
            return self._tagger
        try:
            import ipadic
            from fugashi import GenericTagger
            dicdir = ipadic.DICDIR
            rcfile = os.path.join(dicdir, 'mecabrc')
            # 路径可能含空格，用双引号包围
            self._tagger = GenericTagger(f'-d "{dicdir}" -r "{rcfile}"')
            return self._tagger
        except Exception as e:
            logging.getLogger("SRT_Extractor").warning(f"[MeCab] 分词器初始化失败: {e}")
            return None

    def _split_text(self, text):
        """按日语句末标点拆分文本，返回 [(子句, 是否句末), ...]"""
        if not text:
            return []

        parts = []
        current = ""
        for char in text:
            current += char
            if char in self.sentence_end_punctuation:
                parts.append((current, True))
                current = ""
        if current:
            parts.append((current, False))
        return parts

    def _mecab_split(self, text, start_time, end_time):
        """用 MeCab 按词汇边界切分长文本，返回 [(子句, start, end), ...]
        失败返回 None，调用方 fallback 到 _linear_split
        """
        tagger = self._get_tagger()
        if tagger is None:
            return None

        total_duration = end_time - start_time

        # 如果总时长不超过 max_duration 且字数不超过 max_chars，无需切分
        if total_duration <= self.max_duration and len(text) <= self.max_chars:
            return [(text, start_time, end_time)]

        try:
            tokens = [word.surface for word in tagger(text)]
        except Exception:
            return None

        if not tokens:
            return None

        # 按词汇边界组合成子句（不超过 max_chars）
        groups = []
        current_tokens = []
        current_chars = 0

        for tok in tokens:
            tok_len = len(tok)
            # 如果当前段已超限 或 加这个词会超限，先结算当前段
            if current_chars > 0 and (current_chars >= self.max_chars or current_chars + tok_len > self.max_chars):
                groups.append(current_tokens)
                current_tokens = [tok]
                current_chars = tok_len
            else:
                current_tokens.append(tok)
                current_chars += tok_len

        if current_tokens:
            groups.append(current_tokens)

        # 按 token 数量比例分配时间
        total_tokens = len(tokens)
        token_idx = 0
        result = []
        for grp in groups:
            grp_text = "".join(grp)
            n_toks = len(grp)

            if not result:
                part_start = start_time
            else:
                part_start = result[-1][2]

            if len(result) == len(groups) - 1:
                part_end = end_time
            else:
                ratio = n_toks / total_tokens if total_tokens > 0 else 1.0 / len(groups)
                part_end = part_start + total_duration * ratio

            part_end = max(part_end, part_start + self.min_duration)
            part_end = min(part_end, end_time)
            result.append((grp_text, part_start, part_end))
            token_idx += n_toks

        return result

    def _linear_split(self, text, start_time, end_time):
        """对无标点的长文本按字符数线性切分，返回 [(子句, start, end), ...]"""
        if not text:
            return []

        # 优先用 MeCab 词汇边界切分
        mecab_parts = self._mecab_split(text, start_time, end_time)
        if mecab_parts is not None:
            return mecab_parts

        total_chars = len(text)
        total_duration = end_time - start_time

        # 如果总时长不超过 max_duration 且字数不超过 max_chars，无需切分
        if total_duration <= self.max_duration and total_chars <= self.max_chars:
            return [(text, start_time, end_time)]

        # 按 max_chars 切分
        result = []
        n_parts = max(2, int(total_chars / self.max_chars) + 1)
        chars_per_part = total_chars // n_parts

        idx = 0
        for i in range(n_parts):
            if idx >= total_chars:
                break
            part_start = start_time + (total_duration * idx / total_chars)
            if i == n_parts - 1:
                part_text = text[idx:]
                part_end = end_time
            else:
                take = chars_per_part
                part_text = text[idx:idx + take]
                idx += take
                part_end = start_time + (total_duration * idx / total_chars)

            part_end = max(part_end, part_start + self.min_duration)
            result.append((part_text, part_start, part_end))

        return result

    def _split_by_word_gaps(self, text, words, seg_start, seg_end):
        """利用 words 之间的大间隙切分长 segment。
        日语 whisperX 的逐字符时间戳虽然不均匀，但大间隙通常对应真实停顿。
        返回 [(子句, start, end), ...] 或 None（无法切分）
        """
        if not words or len(words) < 2:
            return None

        GAP_THRESHOLD = 0.6  # 字符间间隙阈值（秒）

        # 收集字符时间戳
        char_infos = []
        for w in words:
            wtext = w.get("word", "").strip()
            ws = w.get("start", seg_start)
            we = w.get("end", seg_end)
            for c in wtext:
                char_infos.append({"char": c, "start": ws, "end": we})

        if len(char_infos) != len(text):
            # words 和 text 长度不匹配，fallback
            return None

        # 找大间隙位置
        split_indices = []
        for i in range(1, len(char_infos)):
            gap = char_infos[i]["start"] - char_infos[i - 1]["end"]
            if gap >= GAP_THRESHOLD:
                split_indices.append(i)

        if not split_indices:
            return None

        # 按间隙切分
        parts = []
        start_idx = 0
        for idx in split_indices:
            part_text = text[start_idx:idx]
            part_start = char_infos[start_idx]["start"]
            part_end = char_infos[idx - 1]["end"]
            # 确保最小持续时间
            part_end = max(part_end, part_start + self.min_duration)
            parts.append((part_text, part_start, part_end))
            start_idx = idx

        # 最后一段
        part_text = text[start_idx:]
        part_start = char_infos[start_idx]["start"]
        part_end = seg_end
        part_end = max(part_end, part_start + self.min_duration)
        parts.append((part_text, part_start, part_end))

        return parts

    def smart_punctuation(self, segments):
        """智能标点处理：基于 gap 判断拼接或补句号

        逻辑：
        - 当前段无句末标点 + gap <= 0.3s -> 拼接下一段（日语不加空格）
        - 当前段无句末标点 + gap > 0.3s -> 补句号 '。'
        - 拼接后检查新句末是否有标点，无则继续检查下一段
        """
        if not segments:
            return segments

        result = []
        i = 0
        max_gap = 0.3  # 统一使用 0.3s 阈值

        while i < len(segments):
            current = dict(segments[i])  # 复制，避免修改原始数据
            text = current['text'].strip()

            # 已有句末标点 -> 直接保留
            if text and text[-1] in self.sentence_end_punctuation:
                result.append(current)
                i += 1
                continue

            # 无句末标点 -> 检查与后续段的关系
            merged_text = text
            merged_end = current['end']
            j = i + 1

            found_sentence = False
            while j < len(segments):
                next_seg = segments[j]
                gap = next_seg['start'] - merged_end

                # gap 过大 -> 停止拼接，给当前段补句号
                if gap > max_gap:
                    break

                # gap 小 -> 拼接（日语不加空格）
                # 不同说话人不拼接
                cur_spk = current.get('speaker')
                nxt_spk = next_seg.get('speaker')
                if cur_spk is not None and nxt_spk is not None and cur_spk != nxt_spk:
                    break
                next_text = next_seg['text'].strip()
                merged_text += next_text
                merged_end = next_seg['end']

                # 拼接后检查是否有句末标点
                if merged_text and merged_text[-1] in self.sentence_end_punctuation:
                    # 找到完整句 -> 提交合并结果
                    result.append({
                        'text': merged_text.strip(),
                        'start': current['start'],
                        'end': merged_end,
                        'speaker': current.get('speaker'),
                    })
                    i = j + 1
                    found_sentence = True
                    break

                j += 1
            else:
                # 循环正常结束（非 break）-> 没找到标点
                # 给合并结果补句号（日语用 '。'）
                result.append({
                    'text': merged_text.strip() + '。',
                    'start': current['start'],
                    'end': merged_end,
                    'speaker': current.get('speaker'),
                })
                i = j + 1 if j > i else i + 1
                continue

            if not found_sentence:
                # gap 过大导致 break，当前段未提交，补句号
                result.append({
                    'text': merged_text.strip() + '。',
                    'start': current['start'],
                    'end': merged_end,
                    'speaker': current.get('speaker'),
                })
                i = j
            continue

        return result

    def process_segments(self, segments):
        # 先进行智能标点处理
        segments = self.smart_punctuation(segments)

        for segment in segments:
            seg_text = segment.get("text", "").strip()
            seg_start = segment.get("start", 0)
            seg_end = segment.get("end", seg_start)
            seg_duration = seg_end - seg_start

            if not seg_text:
                continue

            # Step 1: 按句末标点拆分
            parts = self._split_text(seg_text)

            # 如果没有标点且文本太长，需要进一步处理
            if len(parts) == 1 and not parts[0][1]:
                # 无标点句：优先按 word 间隙切分，fallback 到线性切分
                words = segment.get("words", [])
                self._interpolate_word_timestamps(words, seg_start, seg_end)
                sub_parts = self._split_by_word_gaps(parts[0][0], words, seg_start, seg_end)
                if sub_parts is None:
                    sub_parts = self._linear_split(parts[0][0], seg_start, seg_end)
                for sub_text, sub_start, sub_end in sub_parts:
                    self.srt_entries.append({
                        "index": self.entry_count,
                        "start": sub_start,
                        "end": sub_end,
                        "text": sub_text.strip(),
                        "speaker": segment.get("speaker"),
                    })
                    self.entry_count += 1
            elif len(parts) == 1 and len(parts[0][0]) > self.max_chars:
                # 单句有标点但超长：仍需按长度切分
                words = segment.get("words", [])
                self._interpolate_word_timestamps(words, seg_start, seg_end)
                sub_parts = self._split_by_word_gaps(parts[0][0], words, seg_start, seg_end)
                if sub_parts is None:
                    sub_parts = self._linear_split(parts[0][0], seg_start, seg_end)
                for sub_text, sub_start, sub_end in sub_parts:
                    self.srt_entries.append({
                        "index": self.entry_count,
                        "start": sub_start,
                        "end": sub_end,
                        "text": sub_text.strip(),
                        "speaker": segment.get("speaker"),
                    })
                    self.entry_count += 1
            else:
                # 有标点：线性分配时间到每个子句
                total_chars = sum(len(p[0]) for p in parts)
                current_time = seg_start

                for i, (part_text, is_sentence_end) in enumerate(parts):
                    if not part_text:
                        continue

                    # 计算该子句的时间占比
                    part_chars = len(part_text)
                    if i == len(parts) - 1:
                        part_end = seg_end
                    else:
                        part_duration = seg_duration * (part_chars / total_chars)
                        part_end = current_time + part_duration

                    # 确保最小持续时间
                    part_end = max(part_end, current_time + self.min_duration)

                    self.srt_entries.append({
                        "index": self.entry_count,
                        "start": current_time,
                        "end": part_end,
                        "text": part_text.strip(),
                        "speaker": segment.get("speaker"),
                    })
                    self.entry_count += 1
                    current_time = part_end

    def finalize(self):
        """后处理钩子（当前无操作，保留接口兼容性）"""
        pass

    def generate_srt_output(self):
        """生成SRT格式文本"""
        srt_output = ""
        for entry in self.srt_entries:
            start_time = seconds_to_srt_time(entry["start"])
            end_time = seconds_to_srt_time(entry["end"])
            srt_output += f"{entry['index']}\n"
            srt_output += f"{start_time} --> {end_time}\n"
            srt_output += f"{entry['text']}\n\n"
        return srt_output
