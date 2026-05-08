"""
英语字幕处理器 — 基于 segment 级时间戳 + punctuate-all 标点恢复
从 Json_to_Srt.py JsonToSrtConverter 英语提取逻辑演进而来

依赖: models/punctuate-all (kredor/punctuate-all 标点恢复模型)
"""

import json
import os
import re
import sys

from Json_Convert_Srt import seconds_to_srt_time


class EnglishProcessor:
    """英语字幕处理器 — segment 级 + 单词数限制 + punctuate-all 标点恢复

    max_chars 在此处理器中表示最大单词数（非字符数），用于 split_long_segments。
    """

    def __init__(self, max_chars=50, min_duration=0.7, max_gap=0.5,
                 space_optimization=True):
        self.srt_entries = []
        self.entry_count = 1
        self.max_chars = max_chars          # 最大单词数
        self.min_duration = min_duration
        self.max_gap = max_gap
        self.space_optimization = space_optimization

        # 英语标点（与 Json_to_Srt.py 完全一致）
        self.sentence_end_punctuations = {'.', '?', '!', '。', '？', '！', '…'}
        self.comma_punctuations = {',', '，', '、', ';', '；'}
        self.all_punctuations = self.sentence_end_punctuations | self.comma_punctuations

        # ── 预加载 punctuate-all 标点恢复模型 ──
        self._punct_pipe = None
        self._init_punctuation_pipe()

    # ═══════════════════════════════════════════════════════
    #  punctuate-all 模型初始化和标点恢复
    # ═══════════════════════════════════════════════════════

    def _init_punctuation_pipe(self):
        """预加载 kredor/punctuate-all 标点恢复模型（CPU 推理）"""
        try:
            from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
            srt_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(os.path.dirname(srt_dir), "models", "punctuate-all")
            if not os.path.isdir(model_path):
                print(f"[EnglishProcessor] punctuate-all 模型未找到: {model_path}")
                return
            tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            model = AutoModelForTokenClassification.from_pretrained(model_path, local_files_only=True)
            self._punct_pipe = pipeline(
                "ner", model=model, tokenizer=tokenizer,
                aggregation_strategy="none", device=-1
            )
            print("[EnglishProcessor] punctuate-all 模型加载完成")
        except Exception as e:
            print(f"[EnglishProcessor] punctuate-all 加载失败: {e}")
            self._punct_pipe = None

    @staticmethod
    def _interpolate_word_timestamps(words: list, seg_start: float, seg_end: float):
        """Fill missing start/end timestamps by interpolating between neighbors.

        When whisper/wav2vec2 skips tokens like numbers, the resulting gaps
        cause downstream time allocation to fall back to segment boundaries,
        starving adjacent sub-segments of their fair time share.
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

    @staticmethod
    def _fix_decimal_spaces(text):
        """修复 whisperX 数字 artifacts: "1 .19" → "1.19" """
        text = re.sub(r'(\d)\s+\.(\d)', r'\1.\2', text)
        text = re.sub(r'(\d)\s+\.\s+(\d)', r'\1.\2', text)
        return text

    def _restore_punctuation(self, text):
        """用 punctuate-all 恢复标点，返回带标点的文本"""
        if self._punct_pipe is None:
            return text

        text = self._fix_decimal_spaces(text)
        words = text.split()
        if not words:
            return text

        chunk_size = 230
        overlap = 5
        tagged = []

        for i in range(0, len(words), chunk_size - overlap):
            chunk = words[i:i + chunk_size]
            if not chunk:
                break
            actual_overlap = 0 if i + chunk_size >= len(words) else overlap
            chunk_text = " ".join(chunk)
            result = self._punct_pipe(chunk_text)
            char_index = 0
            result_index = 0
            limit = len(chunk) - actual_overlap if actual_overlap else len(chunk)
            for j, word in enumerate(chunk[:limit]):
                char_index += len(word) + 1
                label = "0"
                while result_index < len(result) and char_index > result[result_index]["end"]:
                    label = result[result_index]["entity"]
                    result_index += 1
                tagged.append((word, label))

        output = []
        for word, label in tagged:
            output.append(word)
            if label == "0":
                output.append(" ")
            elif label in ".,?-:":
                if word.endswith(label):
                    output.append(" ")
                else:
                    output.append(label + " ")
        return "".join(output).strip()

    def _find_punct_in_restored(self, restored_text):
        """在恢复标点的文本中找切分点，返回切分单词数。
        优先句末标点 → 逗号类标点，均未找到返回 0。
        """
        # ① 句末标点
        for i in range(len(restored_text) - 1, -1, -1):
            if self.is_sentence_ender(restored_text[i]):
                return len(restored_text[:i + 1].split())
        # ② 逗号类标点
        for i in range(len(restored_text) - 1, -1, -1):
            if self.is_comma_punctuation(restored_text[i]):
                return len(restored_text[:i + 1].split())
        return 0

    # ═══════════════════════════════════════════════════════
    #  切分点查找（新优先级）
    # ═══════════════════════════════════════════════════════

    def _find_split_point_words(self, text):
        """在不超过 max_chars 单词的文本中找最佳切分点

        优先级:
          ① 句子结束标点 (. ? !) 处切分
          ② 逗号类标点 (, ; :) 处切分
          ③ punctuate-all 恢复标点 → 重试 ① ②
          ④ 英语连词 (and but or so yet for nor) 前面切分
          ⑤ 英语介词 (in on at by with to from) 前面切分
          ⑥ 强制在文本末尾切分

        返回: 切分位置（字符索引），即 first_part = text[:pos]
        """
        # ① 句子结束标点
        for i in range(len(text) - 1, -1, -1):
            if self.is_sentence_ender(text[i]):
                return i + 1

        # ② 逗号类标点
        for i in range(len(text) - 1, -1, -1):
            if self.is_comma_punctuation(text[i]):
                return i + 1

        # ③ punctuate-all 恢复标点 → 重试 ① ②
        if self._punct_pipe is not None:
            restored = self._restore_punctuation(text)
            if restored != text:
                word_idx = self._find_punct_in_restored(restored)
                if word_idx > 0:
                    orig_words = text.split()
                    if word_idx <= len(orig_words):
                        prefix = " ".join(orig_words[:word_idx])
                        return len(prefix)

        # ④ 英语连词（在前面切分）
        conjunctions = [' and ', ' but ', ' or ', ' so ', ' yet ', ' for ', ' nor ']
        for conj in conjunctions:
            idx = text.rfind(conj)
            if idx > 0:
                return idx

        # ⑤ 英语介词（在前面切分）
        prepositions = [' in ', ' on ', ' at ', ' by ', ' with ', ' to ', ' from ']
        for prep in prepositions:
            idx = text.rfind(prep)
            if idx > 0:
                return idx

        # ⑥ 强制切分
        return len(text)

    # ═══════════════════════════════════════════════════════
    #  从 Json_to_Srt.py 复刻的方法
    # ═══════════════════════════════════════════════════════

    def is_punctuation(self, char):
        return char in self.all_punctuations

    def is_sentence_ender(self, char):
        return char in self.sentence_end_punctuations

    def is_comma_punctuation(self, char):
        return char in self.comma_punctuations

    def detect_and_handle_silence(self, segments):
        """精确静音处理：确保字幕不覆盖空白区域"""
        if not segments:
            return segments

        processed = []
        prev_end = segments[0]['start']

        for i, seg in enumerate(segments):
            start = seg['start']
            end = seg['end']
            text = seg['text']

            gap = start - prev_end

            if i > 0 and gap > self.max_gap:
                prev_seg = processed[-1]
                new_end = prev_seg['start'] + max(
                    self.min_duration,
                    min(prev_seg['end'] - prev_seg['start'],
                        prev_end + self.min_duration)
                )
                processed[-1]['end'] = new_end

            if gap > self.max_gap:
                start = max(start, prev_end + self.max_gap)

            duration = end - start
            if duration < self.min_duration:
                end = start + self.min_duration

            processed.append({
                'text': text,
                'start': start,
                'end': end,
                'words': seg.get('words', [])
            })

            prev_end = end

        return processed

    def split_long_segments(self, segments):
        """分割过长的字幕段 — 基于单词数限制 + punctuate-all 标点辅助

        状态变量:
          word_count: 当前累积片段的总单词数
          current_text[]: 当前字幕的文本片段列表

        切分触发: word_count + 新段单词数 > max_chars (最大单词数)
        切分优先级: _find_split_point_words 控制
        """
        processed = []
        current_text = []
        current_start = None
        current_end = None
        word_count = 0

        for seg in segments:
            text = seg['text']
            start = seg['start']
            end = seg['end']
            seg_words = len(text.split())

            if current_start is None:
                current_start = start
                current_end = end

            # ── 溢出：需要切分 ──
            if word_count + seg_words > self.max_chars:
                # 拼接当前累积 + 新段
                full_text = " ".join(current_text) + " " + text
                words = full_text.split()
                accumulated_count = word_count  # 已累积单词数
                seg_words_list = seg.get("words", [])  # 本段单词级时间戳
                self._interpolate_word_timestamps(seg_words_list, start, end)

                consumed = 0
                # 迭代切分：除最后一块外全部提交
                while consumed + self.max_chars < len(words):
                    lookahead_end = min(consumed + self.max_chars, len(words))
                    split_word_idx = None

                    # ── 阶段 1: 从左往右，见到 . ? ! , ; : 直接切 ──
                    for i in range(consumed, lookahead_end):
                        w = words[i]
                        if w and (self.is_sentence_ender(w[-1]) or self.is_comma_punctuation(w[-1])):
                            split_word_idx = i
                            break

                    if split_word_idx is not None:
                        chunk_words = words[consumed:split_word_idx + 1]
                    else:
                        # ── 阶段 2: 无标点 → punctuate-all 补标点后找 ──
                        window_text = " ".join(words[consumed:lookahead_end])
                        if self._punct_pipe is not None:
                            restored = self._restore_punctuation(window_text)
                            rwords = restored.split()
                            punct_found = False
                            for ri, rw in enumerate(rwords):
                                if rw and (self.is_sentence_ender(rw[-1]) or self.is_comma_punctuation(rw[-1])):
                                    chunk_words = words[consumed:consumed + ri + 1]
                                    punct_found = True
                                    break
                            if not punct_found:
                                chunk_words = words[consumed:lookahead_end]
                        else:
                            chunk_words = words[consumed:lookahead_end]

                    chunk_text = " ".join(chunk_words)
                    chunk_size = len(chunk_words)

                    # 时间戳：优先单词级（策略三），其次段边界
                    if consumed < accumulated_count:
                        chunk_start = current_start
                    else:
                        seg_idx = consumed - accumulated_count
                        chunk_start = seg_words_list[seg_idx].get('start', start) if seg_idx < len(seg_words_list) else start

                    last_idx = consumed + chunk_size - 1
                    if last_idx < accumulated_count:
                        chunk_end = current_end
                    else:
                        seg_last_idx = last_idx - accumulated_count
                        chunk_end = seg_words_list[seg_last_idx].get('end', end) if seg_last_idx < len(seg_words_list) else (current_end if current_end is not None else end)

                    if chunk_end - chunk_start < self.min_duration:
                        chunk_end = chunk_start + self.min_duration

                    processed.append({
                        'text': chunk_text,
                        'start': chunk_start,
                        'end': chunk_end
                    })

                    consumed += chunk_size

                # 最后一块（≤ max_chars）→ 放回 current_text，保持跨段累积
                remaining_words = words[consumed:]
                second_part = " ".join(remaining_words) if remaining_words else ""

                current_text = [second_part] if second_part else []
                word_count = len(second_part.split()) if second_part else 0

                # 尾段时间戳：优先从剩余单词的时间戳取
                if remaining_words and seg_words_list:
                    ridx = consumed - accumulated_count
                    if 0 <= ridx < len(seg_words_list):
                        current_start = seg_words_list[ridx].get('start', start)
                    rend_idx = (consumed + len(remaining_words) - 1) - accumulated_count
                    if 0 <= rend_idx < len(seg_words_list):
                        current_end = seg_words_list[rend_idx].get('end', end)
                else:
                    current_start = start
                    current_end = end

            # ── 正常累积 ──
            else:
                current_text.append(text)
                word_count += seg_words
                current_end = end

                # 句子结束标点 → 立即提交
                if text and self.is_sentence_ender(text[-1]):
                    if current_end - current_start < self.min_duration:
                        current_end = current_start + self.min_duration

                    processed.append({
                        'text': " ".join(current_text).strip(),
                        'start': current_start,
                        'end': current_end
                    })

                    current_text = []
                    current_start = None
                    current_end = None
                    word_count = 0

        # ── 尾段提交 ──
        if current_text:
            if current_end - current_start < self.min_duration:
                current_end = current_start + self.min_duration
            processed.append({
                'text': " ".join(current_text).strip(),
                'start': current_start,
                'end': current_end
            })

        return processed

    def merge_short_segments(self, segments):
        """合并过短的字幕段 — 基于单词数限制"""
        if not segments:
            return []

        merged = []
        current = segments[0]

        for next_seg in segments[1:]:
            gap = next_seg['start'] - current['end']
            cur_text = current['text'].strip()
            nxt_text = next_seg['text'].strip()
            cur_words = len(cur_text.split())
            nxt_words = len(nxt_text.split())

            can_merge = (
                gap <= self.max_gap and
                cur_words + nxt_words <= self.max_chars and
                not (cur_text[-1] in self.sentence_end_punctuations if cur_text else False)
            )

            if can_merge:
                separator = ' ' if self.space_optimization else ''
                current['text'] = f"{cur_text}{separator}{nxt_text}"
                current['end'] = next_seg['end']
            else:
                merged.append(current)
                current = next_seg

        merged.append(current)
        return merged

    def ensure_time_sync(self, segments):
        """严格时间同步验证"""
        if len(segments) < 2:
            return segments

        for i in range(1, len(segments)):
            prev = segments[i - 1]
            curr = segments[i]
            if prev['end'] > curr['start']:
                overlap = prev['end'] - curr['start']
                correction = overlap / 2
                prev['end'] -= correction
                curr['start'] += correction

        prev_end = segments[0]['end']
        for i in range(1, len(segments)):
            curr = segments[i]
            gap = curr['start'] - prev_end

            if gap > self.max_gap:
                segments[i - 1]['end'] = min(
                    segments[i - 1]['end'],
                    prev_end + self.min_duration
                )
                if gap > 2.0:
                    curr['text'] = "[...] " + curr['text']

            prev_end = curr['end']

        return segments

    def smart_punctuation(self, segments):
        """智能标点处理：基于 gap 判断拼接或补句号

        逻辑：
        - 当前段无句末标点 + gap ≤ max_gap → 拼接下一段
        - 当前段无句末标点 + gap > max_gap → 补句号
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

            # 已有句末标点 → 直接保留
            if text and self.is_sentence_ender(text[-1]):
                result.append(current)
                i += 1
                continue

            # 无句末标点 → 检查与后续段的关系
            merged_text = text
            merged_end = current['end']
            j = i + 1

            while j < len(segments):
                next_seg = segments[j]
                gap = next_seg['start'] - merged_end

                # gap 过大 → 停止拼接，给当前段补句号
                if gap > max_gap:
                    break

                # gap 小 → 拼接
                next_text = next_seg['text'].strip()
                merged_text += " " + next_text
                merged_end = next_seg['end']

                # 拼接后检查是否有句末标点
                if merged_text and self.is_sentence_ender(merged_text[-1]):
                    # 找到完整句 → 提交合并结果
                    merged_words = list(current.get('words', []))
                    for k in range(i + 1, j + 1):
                        merged_words.extend(segments[k].get('words', []))
                    result.append({
                        'text': merged_text.strip(),
                        'start': current['start'],
                        'end': merged_end,
                        'words': merged_words
                    })
                    i = j + 1
                    break

                j += 1
            else:
                # 循环正常结束（非 break）→ 没找到标点
                # 给合并结果补句号（英语用 '.'）
                merged_words = list(current.get('words', []))
                for k in range(i + 1, j):
                    merged_words.extend(segments[k].get('words', []))
                result.append({
                    'text': merged_text.strip() + '.',
                    'start': current['start'],
                    'end': merged_end,
                    'words': merged_words
                })
                i = j + 1 if j > i else i + 1
                continue

            # break 出来（找到了句末标点）→ 已处理，继续下一轮
            continue

        return result

    def ensure_punctuation_at_end(self, segments):
        """确保每行字幕以标点符号结尾（不随意添加标点）"""
        for i in range(len(segments)):
            text = segments[i]['text'].strip()
            if not text:
                continue

            if not self.is_sentence_ender(text[-1]) and not self.is_comma_punctuation(text[-1]):
                if i < len(segments) - 1:
                    next_text = segments[i + 1]['text'].strip()
                    if next_text and self.is_sentence_ender(next_text[0]):
                        segments[i]['text'] = text + next_text[0]
                        segments[i + 1]['text'] = next_text[1:]

        return segments

    # ── 主处理流程 ──

    def process_segments(self, segments):
        """英语字幕处理主流程

        管线: 静音 → 智能标点 → 分割长段 → 合并短段 → 时间同步 → 标点收尾 → srt_entries
        """
        if not segments:
            return

        print(f"初始分段数: {len(segments)}")

        segments = self.detect_and_handle_silence(segments)
        print(f"静音处理后: {len(segments)}段")

        segments = self.smart_punctuation(segments)
        print(f"智能标点后: {len(segments)}段")

        segments = self.split_long_segments(segments)
        print(f"分割长段后: {len(segments)}段")

        segments = self.merge_short_segments(segments)
        print(f"合并短段后: {len(segments)}段")

        segments = self.ensure_time_sync(segments)
        segments = self.ensure_punctuation_at_end(segments)

        for i, seg in enumerate(segments, start=1):
            self.srt_entries.append({
                "index": i,
                "start": seg['start'],
                "end": seg['end'],
                "text": seg['text']
            })
        self.entry_count = len(self.srt_entries) + 1

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

    def __del__(self):
        """释放 punctuate-all 模型内存"""
        if self._punct_pipe is not None:
            del self._punct_pipe
            self._punct_pipe = None


# ── 导出入口（向后兼容） ──

def convert_json_to_srt(json_input):
    """导出入口 — 委托到 Json_Convert_Srt.convert_json_to_srt"""
    from Json_Convert_Srt import convert_json_to_srt as _impl
    return _impl(json_input)


# ── 独立运行测试 ──

if __name__ == "__main__":
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        json_path = input("JSON文件路径: ").strip()

    if not os.path.exists(json_path):
        print(f"错误: JSON文件不存在 - {json_path}")
        sys.exit(1)

    srt_content = convert_json_to_srt(json_path)
    srt_path = os.path.splitext(json_path)[0] + '.srt'

    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)

    print(f"SRT文件转换完成！已保存至: {srt_path}")
