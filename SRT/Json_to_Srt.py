import os
import json
import pysrt
import string
import re
from datetime import timedelta


class JsonToSrtConverter:
    # 多语言预设参数
    LANGUAGE_PRESETS = {
        # 日语预设
        "ja": {
            "max_chars": 35,
            "max_words": 999,  # 禁用单词限制
            "min_duration": 0.8,
            "max_gap": 0.3,
            "space_optimization": False,  # 禁用空格优化
            "formatter": "japanese"
        },
        # 英语预设
        "en": {
            "max_chars": 50,
            "max_words": 12,
            "min_duration": 0.7,
            "max_gap": 1.0,
            "space_optimization": True,  # 保留单词间空格
            "formatter": "english"
        },
        # 中文预设
        "zh": {
            "max_chars": 25,  # 中文字符较宽
            "max_words": 999,  # 禁用单词限制
            "min_duration": 0.9,
            "max_gap": 0.8,
            "space_optimization": False,
            "formatter": "chinese"
        },
        # 韩语预设
        "ko": {
            "max_chars": 30,
            "max_words": 999,
            "min_duration": 0.85,
            "max_gap": 0.75,
            "space_optimization": False,
            "formatter": "korean"
        },
        # 默认预设（其他语言）
        "default": {
            "max_chars": 45,
            "max_words": 15,
            "min_duration": 0.75,
            "max_gap": 0.85,
            "space_optimization": True,
            "formatter": "general"
        }
    }

    def __init__(self, json_path, srt_path=None, lang="auto", **kwargs):
        """
        json_path: Whisper生成的JSON字幕文件路径
        srt_path: 输出的SRT文件路径（可选）
        lang: 字幕语言（支持'auto'自动检测）
        **kwargs: 可覆盖预设参数
        """
        self.json_path = json_path
        self.srt_path = srt_path or os.path.splitext(json_path)[0] + '.srt'

        # 语言检测（如果设置为auto）
        self.lang = self.detect_language() if lang == "auto" else lang.lower()

        # 获取语言预设
        preset = self.LANGUAGE_PRESETS.get(self.lang, self.LANGUAGE_PRESETS["default"])

        # 应用预设参数，允许kwargs覆盖
        self.max_chars = kwargs.get('max_chars', preset["max_chars"])
        self.max_words = kwargs.get('max_words', preset["max_words"])
        self.min_duration = kwargs.get('min_duration', preset["min_duration"])
        self.max_gap = kwargs.get('max_gap', preset["max_gap"])
        self.space_optimization = kwargs.get('space_optimization', preset["space_optimization"])
        self.formatter_type = kwargs.get('formatter', preset["formatter"])

        # 语言专用标点符号
        self.set_language_specific_punctuations()

    def detect_language(self):
        """从JSON文件中检测语言"""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('language', 'en').lower()
        except:
            return 'en'  # 默认英语

    def set_language_specific_punctuations(self):
        """设置语言专用标点符号"""
        # 通用标点
        self.sentence_end_punctuations = {'.', '?', '!', '。', '？', '！', '…'}
        self.comma_punctuations = {',', '，', '、', ';', '；'}

        # 语言特定标点
        if self.lang == "ja":  # 日语
            self.japanese_punctuations = {'。', '、', '・', '「', '」', '『', '』', '【', '】', '（', '）', '！', '？', '…'}
            self.all_punctuations = self.sentence_end_punctuations | self.comma_punctuations | self.japanese_punctuations
        elif self.lang == "zh":  # 中文
            self.chinese_punctuations = {'。', '，', '、', '；', '：', '？', '！', '「', '」', '『', '』', '（', '）', '【', '】', '…'}
            self.all_punctuations = self.sentence_end_punctuations | self.comma_punctuations | self.chinese_punctuations
        elif self.lang == "ko":  # 韩语
            self.korean_punctuations = {'.', '?', '!', '。', '?', '!', ',', '，', '、', ';', '；', '…'}
            self.all_punctuations = self.sentence_end_punctuations | self.comma_punctuations | self.korean_punctuations
        else:  # 其他语言
            self.all_punctuations = self.sentence_end_punctuations | self.comma_punctuations

    def load_json_data(self):
        """增强版：精确加载时间戳数据，确保日语单词级时间戳"""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except UnicodeDecodeError:
            with open(self.json_path, 'r', encoding='utf-16') as f:
                data = json.load(f)

        segments = []
        total_duration = 0

        # 计算总时长用于验证
        for segment in data.get('segments', []):
            total_duration += segment['end'] - segment['start']

        for segment in data.get('segments', []):
            if not segment.get('text', '').strip():
                continue

            # 日语处理：严格使用单词级时间戳
            if self.lang == 'ja' and 'words' in segment and segment['words']:
                words = segment.get('words', [])
                # 验证单词时间戳在段落范围内
                words = [w for w in words if w['start'] >= segment['start'] and w['end'] <= segment['end']]

                if words:
                    for word in words:
                        text = word.get('text', '').strip()
                        if not text:
                            continue
                        segments.append({
                            'text': text,
                            'start': word['start'],
                            'end': word['end'],
                            'is_word': True  # 标记为单词级数据
                        })
                else:
                    # 单词数据无效时回退到段落级
                    segments.append({
                        'text': segment['text'].strip(),
                        'start': segment['start'],
                        'end': segment['end'],
                        'is_word': False
                    })
            else:
                # 其他语言处理
                segments.append({
                    'text': segment['text'].strip(),
                    'start': segment['start'],
                    'end': segment['end'],
                    'is_word': False
                })

        # 时间戳验证
        if segments and total_duration > 0:
            first_start = segments[0]['start']
            last_end = segments[-1]['end']
            calculated_duration = last_end - first_start

            # 检测时间戳异常
            if abs(calculated_duration - total_duration) > total_duration * 0.1:
                print(f"警告：时间戳异常（计算时长:{calculated_duration:.2f}s, 实际时长:{total_duration:.2f}s）")
                # 重新校准时间戳
                return self.calibrate_timestamps(segments, total_duration)

        return segments

    def calibrate_timestamps(self, segments, total_duration):
        """时间戳校准：当日语单词级时间戳异常时使用"""
        calibrated = []
        current_start = segments[0]['start']

        # 计算平均单词时长
        word_count = sum(1 for seg in segments if 'is_word' in seg and seg['is_word'])
        if word_count == 0:
            return segments  # 无法校准

        avg_word_duration = total_duration / word_count

        for seg in segments:
            if seg.get('is_word', False):
                # 单词级数据使用校准后的时间
                seg['end'] = current_start + avg_word_duration
                calibrated.append(seg)
                current_start = seg['end']
            else:
                # 段落级数据保持原样
                calibrated.append(seg)
                current_start = seg['end']

        return calibrated

    def is_punctuation(self, char):
        """检查字符是否是标点符号"""
        return char in self.all_punctuations

    def is_sentence_ender(self, char):
        """检查字符是否是句子结束标点"""
        return char in self.sentence_end_punctuations

    def is_comma_punctuation(self, char):
        """检查字符是否是逗号类标点（可作为分割点）"""
        return char in self.comma_punctuations

    def find_optimal_split_point(self, text, current_length):
        """
        在文本中寻找最佳分割点（优先在标点处分割）
        """
        # 如果文本较短，不需要分割
        if len(text) <= self.max_chars:
            return len(text)

        # 1. 优先在句子结束标点处分割
        for i in range(min(len(text), self.max_chars), 0, -1):
            if i > 0 and self.is_sentence_ender(text[i - 1]):
                return i

        # 2. 其次在逗号类标点处分割
        for i in range(min(len(text), self.max_chars), 0, -1):
            if i > 0 and self.is_comma_punctuation(text[i - 1]):
                return i

        # 3. 对于英语，尝试在连词处分割
        if self.lang == 'en':
            # 英语连词列表
            conjunctions = [' and ', ' but ', ' or ', ' so ', ' yet ', ' for ', ' nor ']
            for conj in conjunctions:
                index = text.rfind(conj, 0, min(len(text), self.max_chars))
                if index > 0:
                    return index + len(conj) - 1

        # 4. 对于所有语言，尝试在语义边界处分割
        if self.lang in ['en', 'default']:
            # 尝试在介词前分割
            prepositions = [' in ', ' on ', ' at ', ' by ', ' with ', ' to ', ' from ']
            for prep in prepositions:
                index = text.rfind(prep, 0, min(len(text), self.max_chars))
                if index > 0:
                    return index

        # 5. 最后在合适的字符边界分割
        for i in range(min(len(text), self.max_chars), 0, -1):
            # 避免在特定字符后分割
            if i < len(text) and text[i] not in {'っ', 'ッ'}:
                return i

        # 没有找到合适的分割点，强制在最大长度处分割
        return self.max_chars

    def detect_and_handle_silence(self, segments):
        """精确静音处理：确保字幕不覆盖空白区域"""
        if not segments:
            return segments

        processed = []
        prev_end = segments[0]['start']  # 初始化为第一个段的开始时间

        for i, seg in enumerate(segments):
            start = seg['start']
            end = seg['end']
            text = seg['text']

            # 1. 检测静音间隙
            gap = start - prev_end

            # 2. 处理前段结束时间
            if i > 0 and gap > self.max_gap:
                # 缩短前一个字幕的持续时间
                prev_seg = processed[-1]
                new_end = prev_seg['start'] + max(
                    self.min_duration,
                    min(prev_seg['end'] - prev_seg['start'],  # 保持原时长或
                        prev_end + self.min_duration)  # 最小持续时间
                )
                processed[-1]['end'] = new_end

            # 3. 处理当前段开始时间
            if gap > self.max_gap:
                # 当前段开始时间不应早于前段结束时间+最大间隙
                start = max(start, prev_end + self.max_gap)

            # 4. 确保最小持续时间
            duration = end - start
            if duration < self.min_duration:
                end = start + self.min_duration

            # 5. 添加处理后的段
            processed.append({
                'text': text,
                'start': start,
                'end': end
            })

            prev_end = end

        return processed

    def ensure_punctuation_at_end(self, segments):
        """确保每行字幕以标点符号结尾（不随意添加标点）"""
        for i in range(len(segments)):
            text = segments[i]['text'].strip()
            if not text:
                continue

            # 检查是否以标点结尾
            if not self.is_sentence_ender(text[-1]) and not self.is_comma_punctuation(text[-1]):
                # 尝试添加适当的标点（仅当下一句有标点时）
                if i < len(segments) - 1:
                    next_text = segments[i + 1]['text'].strip()
                    if next_text and self.is_sentence_ender(next_text[0]):
                        # 如果下一句以标点开始，移动到当前句结尾
                        segments[i]['text'] = text + next_text[0]
                        segments[i + 1]['text'] = next_text[1:]
                # 否则不添加任何标点，保持原样

        return segments

    def split_long_segments(self, segments):
        """增强版：精确分割并保持时间同步"""
        processed = []
        current_text = []
        current_words = []  # 保存单词级数据
        current_start = None
        current_end = None
        char_count = 0

        for seg in segments:
            text = seg['text']
            start = seg['start']
            end = seg['end']
            is_word = seg.get('is_word', False)

            # 初始化当前段
            if current_start is None:
                current_start = start
                current_end = end
            # 日语处理：逐个单词处理
            if self.lang == 'ja' and is_word:
                current_words.append(seg)
                current_text.append(text)
                char_count += len(text)
                current_end = end

                # 检查是否超过长度限制
                if char_count > self.max_chars:
                    # 在最后一个完整单词处分隔
                    if len(current_words) > 1:
                        # 创建新段（排除最后一个单词）
                        split_index = len(current_words) - 1
                        split_segment = self.create_segment_from_words(
                            current_words[:split_index],
                            current_text[:split_index]
                        )
                        processed.append(split_segment)

                        # 开始新段（仅包含最后一个单词）
                        current_words = [current_words[-1]]
                        current_text = [current_text[-1]]
                        char_count = len(current_text[0])
                        current_start = current_words[0]['start']
                        current_end = current_words[0]['end']
                    else:
                        # 单个单词超过长度 - 强制分割
                        split_index = self.find_optimal_split_point(text, char_count)
                        first_part = text[:split_index]
                        second_part = text[split_index:]

                        # 平均分配时间
                        mid_time = (start + end) / 2

                        processed.append({
                            'text': first_part,
                            'start': start,
                            'end': mid_time
                        })

                        current_words = [{
                            'text': second_part,
                            'start': mid_time,
                            'end': end,
                            'is_word': True
                        }]
                        current_text = [second_part]
                        char_count = len(second_part)
                        current_start = mid_time
                        current_end = end
            # 检查是否需要分割
            else:
                if char_count + len(text) > self.max_chars:
                    # 找到最佳分割点
                    split_index = self.find_optimal_split_point(text, char_count)

                    # 分割当前文本
                    first_part = text[:split_index]
                    second_part = text[split_index:]

                    # 添加第一部分
                    current_text.append(first_part)
                    char_count += len(first_part)

                    # 确保最短持续时间
                    if current_end - current_start < self.min_duration:
                        current_end = current_start + self.min_duration

                    # 保存当前段
                    processed.append({
                        'text': ''.join(current_text).strip(),
                        'start': current_start,
                        'end': current_end
                    })

                    # 重置当前段，从第二部分开始
                    current_text = [second_part]
                    char_count = len(second_part)
                    current_start = start  # 使用原始开始时间
                    current_end = end
                else:
                    # 添加当前单词
                    current_text.append(text)
                    char_count += len(text)
                    current_end = end

                    # 检查是否需要分割（句子结束点）
                    if text and self.is_sentence_ender(text[-1]):
                        # 确保最短持续时间
                        if current_end - current_start < self.min_duration:
                            current_end = current_start + self.min_duration

                        processed.append({
                            'text': ''.join(current_text).strip(),
                            'start': current_start,
                            'end': current_end
                        })

                        # 重置当前段
                        current_text = []
                        current_start = None
                        current_end = None
                        char_count = 0

        # 添加最后一段
        if current_text:
            if self.lang == 'ja' and current_words:
                seg = self.create_segment_from_words(current_words, current_text)
                processed.append(seg)
            else:
                # 确保最小持续时间
                if current_end - current_start < self.min_duration:
                    current_end = current_start + self.min_duration
                processed.append({
                    'text': ''.join(current_text).strip(),
                    'start': current_start,
                    'end': current_end
                })

        return processed

    def create_segment_from_words(self, words, texts):
        """从单词列表创建精确时间戳的段落"""
        start = words[0]['start']
        end = words[-1]['end']
        text = ''.join(texts) if self.lang == 'ja' else ' '.join(texts)

        # 验证持续时间
        duration = end - start
        if duration < self.min_duration:
            end = start + self.min_duration

        return {
            'text': text,
            'start': start,
            'end': end
        }

    def merge_short_segments(self, segments):
        """增强合并：确保不跨越静音区"""
        if not segments:
            return []

        merged = []
        current = segments[0]

        for next_seg in segments[1:]:
            gap = next_seg['start'] - current['end']
            current_text = current['text'].strip()
            next_text = next_seg['text'].strip()

            # 关键改进：检查是否跨越静音区
            can_merge = (
                    gap <= self.max_gap and
                    len(current_text) + len(next_text) <= self.max_chars and
                    not self.is_sentence_ender(current_text[-1] if current_text else '')
            )

            # 日语特殊规则：不合并以结束标点结尾的段
            if self.lang == 'ja' and current_text and self.is_sentence_ender(current_text[-1]):
                can_merge = False

            # 合并并更新结束时间
            if can_merge:
                separator = '' if self.lang == 'ja' else ' '
                current['text'] = f"{current_text}{separator}{next_text}"
                current['end'] = next_seg['end']

                # 检查合并后持续时间是否合理
                duration = current['end'] - current['start']
                if duration > 5.0:  # 合并后最大持续时间
                    merged.append(current)
                    current = next_seg
            else:
                merged.append(current)
                current = next_seg

        merged.append(current)
        return merged

    def ensure_time_sync(self, segments):
        """严格时间同步验证"""
        if len(segments) < 2:
            return segments

        # 1. 修复重叠
        for i in range(1, len(segments)):
            prev = segments[i - 1]
            curr = segments[i]

            if prev['end'] > curr['start']:
                overlap = prev['end'] - curr['start']
                # 平均分配重叠时间
                correction = overlap / 2
                prev['end'] -= correction
                curr['start'] += correction

        # 2. 验证静音区
        prev_end = segments[0]['end']
        for i in range(1, len(segments)):
            curr = segments[i]
            gap = curr['start'] - prev_end

            if gap > self.max_gap:
                # 在长间隙前缩短前一个字幕
                segments[i - 1]['end'] = min(
                    segments[i - 1]['end'],
                    prev_end + self.min_duration
                )
                # 添加间隙指示
                if gap > 2.0:  # 只对显著间隙添加指示
                    curr['text'] = "[...] " + curr['text']

            prev_end = curr['end']

        return segments

    def convert_to_srt(self):
        """增强处理流程"""
        # 1. 加载原始JSON数据
        segments = self.load_json_data()
        if not segments:
            raise ValueError("JSON文件中未找到有效的字幕数据")

        print(f"初始分段数: {len(segments)}")

        # 2. 精确静音处理
        segments = self.detect_and_handle_silence(segments)
        print(f"静音处理后: {len(segments)}段")

        # 3. 分割过长的字幕段
        segments = self.split_long_segments(segments)
        print(f"分割长段后: {len(segments)}段")

        # 4. 合并过短的字幕段
        segments = self.merge_short_segments(segments)
        print(f"合并短段后: {len(segments)}段")

        # 5. 时间同步验证
        segments = self.ensure_time_sync(segments)

        # 6. 确保每行以标点结尾
        segments = self.ensure_punctuation_at_end(segments)

        # 6. 创建SRT对象
        subs = pysrt.SubRipFile()

        for i, seg in enumerate(segments, start=1):
            # 创建时间戳对象 - 修复方法
            start_seconds = seg['start']
            end_seconds = seg['end']

            # 将秒数转换为时、分、秒、毫秒
            start_td = timedelta(seconds=start_seconds)
            end_td = timedelta(seconds=end_seconds)

            # 计算各时间单位
            start_hours, remainder = divmod(start_td.seconds, 3600)
            start_minutes, start_seconds = divmod(remainder, 60)
            start_milliseconds = start_td.microseconds // 1000

            end_hours, remainder = divmod(end_td.seconds, 3600)
            end_minutes, end_seconds = divmod(remainder, 60)
            end_milliseconds = end_td.microseconds // 1000

            # 创建字幕项
            item = pysrt.SubRipItem(
                index=i,
                start=pysrt.SubRipTime(
                    hours=start_hours,
                    minutes=start_minutes,
                    seconds=start_seconds,
                    milliseconds=start_milliseconds
                ),
                end=pysrt.SubRipTime(
                    hours=end_hours,
                    minutes=end_minutes,
                    seconds=end_seconds,
                    milliseconds=end_milliseconds
                ),
                text=seg['text']
            )
            subs.append(item)

        # 7. 保存SRT文件
        subs.save(self.srt_path, encoding='utf-8')
        return self.srt_path

    def process(self):
        """处理JSON并生成SRT文件"""
        print(f"开始处理字幕文件: {self.json_path}")
        try:
            srt_path = self.convert_to_srt()
            print(f"字幕处理完成，已保存到: {srt_path}")
            return srt_path
        except Exception as e:
            print(f"字幕处理失败: {str(e)}")
            return None

    def get_formatter(self, srt_path):
        """获取语言专用格式化器"""
        if self.formatter_type == "japanese":
            return JapaneseSubtitleFormatter(srt_path)
        elif self.formatter_type == "chinese":
            return ChineseSubtitleFormatter(srt_path)
        elif self.formatter_type == "korean":
            return KoreanSubtitleFormatter(srt_path)
        else:  # 英语及其他语言
            return GeneralSubtitleFormatter(srt_path)


# 日语专用的字幕整理类

class JapaneseSubtitleFormatter:
    """日语专用字幕格式化器"""

    def __init__(self, srt_path):
        self.srt_path = srt_path
        self.subs = pysrt.open(srt_path, encoding='utf-8')

        # 日语专用标点
        self.japanese_punctuations = {'。', '、', '・', '「', '」', '『', '』', '【', '】', '（', '）', '！', '？', '…'}
        self.sentence_end_punctuations = {'。', '？', '！', '…'}

    def is_japanese_punctuation(self, char):
        return char in self.japanese_punctuations

    def is_sentence_ender(self, char):
        return char in self.sentence_end_punctuations

    def format_japanese_subtitles(self):
        """优化日语字幕格式"""
        new_subs = pysrt.SubRipFile()

        for i, sub in enumerate(self.subs, start=1):
            text = sub.text.strip()

            # 1. 移除多余空格（日语通常不使用空格）
            text = re.sub(r'\s+', '', text)

            # 2. 确保标点使用规范
            # 句号后不应有空格
            text = re.sub(r'。\s*', '。', text)
            # 逗号后不应有空格
            text = re.sub(r'、\s*', '、', text)

            # 3. 处理引号
            text = text.replace('「 ', '「').replace(' 」', '」')
            text = text.replace('『 ', '『').replace(' 』', '』')

            # 4. 确保每行以标点结束
            if text and not self.is_sentence_ender(text[-1]) and not self.is_japanese_punctuation(text[-1]):
                text += '。'

            # 5. 添加新字幕项
            new_sub = pysrt.SubRipItem(
                index=i,
                start=sub.start,
                end=sub.end,
                text=text
            )
            new_subs.append(new_sub)

        return new_subs

    def save_formatted_subtitles(self, output_path=None):
        """保存优化后的字幕"""
        formatted_subs = self.format_japanese_subtitles()
        output_path = output_path or self.srt_path.replace('.srt', '_formatted.srt')
        formatted_subs.save(output_path, encoding='utf-8')
        return output_path


class ChineseSubtitleFormatter:
    """中文专用字幕格式化器"""

    def __init__(self, srt_path):
        self.srt_path = srt_path
        self.subs = pysrt.open(srt_path, encoding='utf-8')

        # 中文专用标点
        self.chinese_punctuations = {'。', '，', '、', '；', '：', '？', '！', '「', '」', '『', '』', '（', '）', '【', '】', '…'}

    def format_chinese_subtitles(self):
        """优化中文字幕格式"""
        new_subs = pysrt.SubRipFile()

        for i, sub in enumerate(self.subs, start=1):
            text = sub.text.strip()

            # 1. 移除多余空格（中文通常不使用空格）
            text = re.sub(r'\s+', '', text)

            # 2. 确保标点使用规范
            text = re.sub(r'。\s*', '。', text)
            text = re.sub(r'，\s*', '，', text)

            # 3. 处理引号
            text = text.replace('「 ', '「').replace(' 」', '」')
            text = text.replace('『 ', '『').replace(' 』', '』')

            # 4. 确保每行以标点结束
            if text and text[-1] not in self.chinese_punctuations:
                text += '。'

            # 5. 添加新字幕项
            new_sub = pysrt.SubRipItem(
                index=i,
                start=sub.start,
                end=sub.end,
                text=text
            )
            new_subs.append(new_sub)

        return new_subs

    def save_formatted_subtitles(self, output_path=None):
        """保存优化后的字幕"""
        formatted_subs = self.format_chinese_subtitles()
        output_path = output_path or self.srt_path.replace('.srt', '_formatted.srt')
        formatted_subs.save(output_path, encoding='utf-8')
        return output_path


class KoreanSubtitleFormatter:
    """韩语专用字幕格式化器"""

    def __init__(self, srt_path):
        self.srt_path = srt_path
        self.subs = pysrt.open(srt_path, encoding='utf-8')

        # 韩语专用标点
        self.korean_punctuations = {'.', '?', '!', '。', '?', '!', ',', '，', '、', ';', '；', '…'}

    def format_korean_subtitles(self):
        """优化韩语字幕格式"""
        new_subs = pysrt.SubRipFile()

        for i, sub in enumerate(self.subs, start=1):
            text = sub.text.strip()

            # 1. 移除多余空格（韩语通常不使用空格）
            text = re.sub(r'\s+', '', text)

            # 2. 确保标点使用规范
            text = re.sub(r'。\s*', '。', text)
            text = re.sub(r'，\s*', '，', text)

            # 3. 处理引号
            text = text.replace('" ', '"').replace(' "', '"')

            # 4. 确保每行以标点结束
            if text and text[-1] not in self.korean_punctuations:
                text += '.'

            # 5. 添加新字幕项
            new_sub = pysrt.SubRipItem(
                index=i,
                start=sub.start,
                end=sub.end,
                text=text
            )
            new_subs.append(new_sub)

        return new_subs

    def save_formatted_subtitles(self, output_path=None):
        """保存优化后的字幕"""
        formatted_subs = self.format_korean_subtitles()
        output_path = output_path or self.srt_path.replace('.srt', '_formatted.srt')
        formatted_subs.save(output_path, encoding='utf-8')
        return output_path


class GeneralSubtitleFormatter:
    """通用字幕格式化器（适用于英语等西方语言）"""

    def __init__(self, srt_path):
        self.srt_path = srt_path
        self.subs = pysrt.open(srt_path, encoding='utf-8')

    def format_general_subtitles(self):
        """优化通用字幕格式"""
        new_subs = pysrt.SubRipFile()

        for i, sub in enumerate(self.subs, start=1):
            text = sub.text.strip()

            # 1. 规范空格使用
            # 移除多余空格但保留单词间空格
            text = re.sub(r'\s+', ' ', text)

            # 2. 确保标点使用规范
            # 逗号后加空格
            text = re.sub(r',(\w)', r', \1', text)
            # 句号后加空格
            text = re.sub(r'\.(\w)', r'. \1', text)

            # 3. 处理引号
            text = text.replace(' "', '"').replace('" ', '"')

            # 4. 确保每行以标点结束
            if text and text[-1] not in {'.', '?', '!'}:
                text += '.'

            # 5. 添加新字幕项
            new_sub = pysrt.SubRipItem(
                index=i,
                start=sub.start,
                end=sub.end,
                text=text
            )
            new_subs.append(new_sub)

        return new_subs

    def save_formatted_subtitles(self, output_path=None):
        """保存优化后的字幕"""
        formatted_subs = self.format_general_subtitles()
        output_path = output_path or self.srt_path.replace('.srt', '_formatted.srt')
        formatted_subs.save(output_path, encoding='utf-8')
        return output_path


# 使用示例 - 日语字幕处理（自定义参数）
if __name__ == "__main__":
    # 替换为您的实际文件路径
    json_path = r"D:\Github\20240708Move_video_2\source_file\ADN-703_(Vocals).json"

    # 检查JSON文件是否存在
    if not os.path.exists(json_path):
        print(f"错误: JSON文件不存在 - {json_path}")
        exit(1)

    # 创建转换器实例（自动检测语言）
    converter = JsonToSrtConverter(
        json_path=json_path,
        lang="ja"  # 自动检测语言
    )

    # 执行转换
    srt_file = converter.process()

    if srt_file and os.path.exists(srt_file):
        print(f"基本字幕已生成: {srt_file}")

        # 获取专用格式化器
        formatter = converter.get_formatter(srt_file)

        # 应用格式优化
        formatted_srt = formatter.save_formatted_subtitles()
        print(f"优化后的字幕: {formatted_srt}")
    else:
        print("字幕转换失败")