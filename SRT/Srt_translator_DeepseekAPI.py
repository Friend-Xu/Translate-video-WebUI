import pysrt
import requests
import re
import time
import json
import os
import subprocess
import sys
from tqdm import tqdm


class SRTTranslator:
    def __init__(self, api_key, input_file, output_file):
        self.api_key = api_key
        self.input_file = input_file
        self.output_file = output_file
        self.subs = None
        self.source_lang = None
        self.groups = []
        self.translation_stats = {
            "total_groups": 0,
            "success_groups": 0,
            "fail_groups": 0,
            "line_mismatches": 0
        }

        # 检查并安装必要的库
        self.install_dependencies()

    def install_dependencies(self):
        """安装必要的依赖库"""
        try:
            import pysrt
            import tqdm
        except ImportError:
            print("检测到未安装必要的库，正在尝试安装...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "pysrt", "tqdm"])
                print("依赖库安装成功!")
            except Exception as e:
                print(f"安装依赖库失败: {str(e)}")
                sys.exit(1)

    def load_srt(self):
        """加载SRT文件"""
        print(f"正在读取 SRT 文件: {self.input_file}")
        try:
            self.subs = pysrt.open(self.input_file, encoding='utf-8')
            if not self.subs:
                raise ValueError("未找到任何字幕条目")

            print(f"找到 {len(self.subs)} 条字幕")

            # 打印样本字幕
            print("\n样本字幕:")
            for i, sub in enumerate(self.subs[:5]):
                print(f"[{sub.index}] {sub.start} --> {sub.end}")
                print(sub.text)
                print()

            return True
        except Exception as e:
            print(f"读取 SRT 文件失败: {str(e)}")
            return False

    def detect_language(self, sample_size=20):
        """检测字幕源语言"""
        if not self.subs:
            return False

        jp_chars = r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]'  # 平假名/片假名/汉字
        en_chars = r'[a-zA-Z]'

        # 获取样本字幕
        sample_texts = [sub.text for sub in self.subs[:min(sample_size, len(self.subs))]]

        jp_count = sum(1 for text in sample_texts if re.search(jp_chars, text))
        en_count = sum(1 for text in sample_texts if re.search(en_chars, text))

        if jp_count > en_count * 2:  # 日语特征更明显
            self.source_lang = 'ja'
        elif en_count > jp_count * 2:  # 英语特征更明显
            self.source_lang = 'en'
        else:
            # 混合语言时，选择占比更高的
            total_jp = sum(len(re.findall(jp_chars, text)) for text in sample_texts)
            total_en = sum(len(re.findall(en_chars, text)) for text in sample_texts)
            self.source_lang = 'ja' if total_jp > total_en else 'en'

        lang_name = "日语" if self.source_lang == 'ja' else "英语"
        print(f"检测到源语言: {lang_name}")
        return True

    def group_subtitles(self, max_group_length=800):
        """将字幕分组以保持上下文连贯性"""
        if not self.subs:
            return False

        # 计算平均字幕长度
        total_length = sum(len(sub.text) for sub in self.subs)
        avg_length = total_length / len(self.subs) if len(self.subs) > 0 else 0

        # 动态确定组大小 - 确保每组不超过5条
        group_size = max(1, min(5, int(max_group_length / avg_length))) if avg_length > 0 else 3

        self.groups = []
        current_group = []
        current_length = 0

        # 备份原始文本（用于错误恢复）
        for sub in self.subs:
            sub.original_text = sub.text

        for sub in self.subs:
            text_length = len(sub.text)

            # 如果当前字幕过长，单独成组
            if text_length > max_group_length * 0.7:
                if current_group:
                    self.groups.append(current_group)
                    current_group = []
                    current_length = 0
                self.groups.append([sub])
                continue

            # 如果添加新字幕后会超长，则创建新组
            if current_length + text_length > max_group_length:
                self.groups.append(current_group)
                current_group = []
                current_length = 0

            current_group.append(sub)
            current_length += text_length

            # 达到组大小限制时创建新组
            if len(current_group) >= group_size:
                self.groups.append(current_group)
                current_group = []
                current_length = 0

        if current_group:
            self.groups.append(current_group)

        if self.groups:
            avg_group_size = len(self.groups[0])
        else:
            avg_group_size = 0

        self.translation_stats["total_groups"] = len(self.groups)
        print(f"字幕已分为 {len(self.groups)} 组进行翻译 (平均每组 {avg_group_size} 条)")
        return True

    def translate_text(self, text, max_retries=3):
        """调用 DeepSeek API 翻译文本"""
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 根据源语言设置系统提示 - 重点强调行数保持
        if self.source_lang == 'ja':
            system_prompt = (
                "你是一位专业的日语字幕翻译。请严格按以下要求操作：\n"
                "1. 将日语字幕逐行翻译成简体中文，保持口语化风格和上下文连贯性\n"
                "2. 严格保持原始文本的行数结构，输出行数必须与输入完全一致\n"
                "3. 每条字幕独立一行，不要合并行\n"
                "4. 不要添加任何额外说明、标号或特殊符号\n"
                "5. 输出格式：每行对应一条独立字幕，保持原始换行符\n"
                "6. 如果原始有多行，翻译后也保持相同的行数\n"
                "重要：必须保持行数完全一致！"
            )
        elif self.source_lang == 'en':
            system_prompt = (
                "You are a professional English subtitle translator. Follow these instructions strictly:\n"
                "1. Translate English subtitles line by line into Simplified Chinese, keeping colloquial style and contextual coherence\n"
                "2. Strictly preserve the original line structure - output must have exactly the same number of lines as input\n"
                "3. Each subtitle must be on a separate line - DO NOT merge lines\n"
                "4. Do not add any extra explanations, numbers or special characters\n"
                "5. Output format: One subtitle per line, preserve original line breaks\n"
                "6. If original has multiple lines, translation must have the same number of lines\n"
                "IMPORTANT: MUST PRESERVE EXACT LINE COUNT!"
            )
        else:
            system_prompt = (
                f"请将以下{self.source_lang}字幕翻译成简体中文，严格按以下要求操作：\n"
                "1. 逐行翻译，保持口语化风格和上下文连贯性\n"
                "2. 严格保持原始文本的行数结构，输出行数必须与输入完全一致\n"
                "3. 每条字幕独立一行，不要合并行\n"
                "4. 不要添加任何额外说明、标号或特殊符号\n"
                "5. 输出格式：每行对应一条独立字幕，保持原始换行符\n"
                "6. 如果原始有多行，翻译后也保持相同的行数\n"
                "重要：必须保持行数完全一致！"
            )

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.1,  # 降低随机性以保持一致性
            "max_tokens": 4000,
            "top_p": 0.9
        }

        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                response.raise_for_status()
                result = response.json()

                # 提取翻译结果
                translated = result['choices'][0]['message']['content'].strip()

                # 清理API可能添加的额外内容
                translated = re.sub(r'^["\']|["\']$', '', translated)  # 移除首尾引号
                translated = re.sub(r'^\d+[.:]\s*', '', translated, flags=re.MULTILINE)  # 移除行首编号
                translated = re.sub(r'^[【\[\(].*?[】\]\)]\s*', '', translated, flags=re.MULTILINE)  # 移除括号内的额外说明

                return translated

            except (requests.exceptions.RequestException, KeyError, json.JSONDecodeError) as e:
                print(f"翻译请求失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = min(30, 2 ** attempt)  # 指数退避但不超过30秒
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"重试失败，保留原文")
                    return text  # 失败时返回原文

        return text

    def translate_group(self, group):
        """翻译一组字幕 - 确保行数匹配"""
        # 合并组内所有文本，保留原始行结构
        combined_text = "\n".join([sub.text for sub in group])
        print("\n",combined_text)
        # 发送翻译请求
        translated_text = self.translate_text(combined_text)
        print(F"翻译为：\n{translated_text}",)
        # 分割翻译结果
        translated_lines = [line.strip() for line in translated_text.split('\n') if line.strip()]

        # 完美匹配：逐行分配
        if len(translated_lines) == len(group):
            for i, sub in enumerate(group):
                sub.text = translated_lines[i]
            return True

        # 尝试修复行数不匹配问题
        print(f"警告: 翻译行数不匹配 ({len(translated_lines)} vs {len(group)})，尝试修复...")
        self.translation_stats["line_mismatches"] += 1

        # 方法1: 尝试按句子分割
        if len(translated_lines) < len(group):
            # 如果返回的行数少于组内字幕数
            combined_translation = " ".join(translated_lines)
            # 尝试按句子分割点分割
            sentences = re.split(r'(?<=[.!?。！？]) +', combined_translation)

            if len(sentences) >= len(group):
                for i, sub in enumerate(group):
                    sub.text = sentences[i] if i < len(sentences) else combined_translation
                print("修复成功: 通过句子分割匹配行数")
                return True

        # 方法2: 尝试按原始行长度比例分配
        total_orig_length = sum(len(sub.original_text) for sub in group)
        if total_orig_length > 0:
            current_pos = 0
            for i, sub in enumerate(group):
                # 计算该字幕应占的比例
                proportion = len(sub.original_text) / total_orig_length
                # 计算在翻译文本中应占的字符数
                target_length = int(len(translated_text) * proportion)
                # 确保不超过文本长度
                end_pos = min(current_pos + max(target_length, 10), len(translated_text))

                # 查找最近的句子结束点
                sentence_end = end_pos
                while sentence_end < len(translated_text) and translated_text[sentence_end] not in '.!?。！？':
                    sentence_end += 1

                if sentence_end < len(translated_text):
                    end_pos = sentence_end + 1

                # 分配文本
                sub.text = translated_text[current_pos:end_pos].strip()
                current_pos = end_pos

            if current_pos >= len(translated_text) * 0.9:  # 确保大部分文本被分配
                print("修复成功: 按比例分配文本")
                return True

        # 方法3: 使用原始文本作为最后手段
        print("无法修复行数不匹配，使用原始文本")
        for sub in group:
            sub.text = sub.original_text
        return False

    def translate_all(self):
        """执行整个翻译流程"""
        if not self.subs or not self.groups:
            print("错误: 请先加载并分组字幕")
            return False

        self.translation_stats["success_groups"] = 0
        self.translation_stats["fail_groups"] = 0

        with tqdm(total=len(self.groups), desc="翻译进度") as pbar:
            for i, group in enumerate(self.groups):
                try:
                    success = self.translate_group(group)
                    if success:
                        self.translation_stats["success_groups"] += 1
                    else:
                        self.translation_stats["fail_groups"] += 1
                except Exception as e:
                    print(f"\n组 {i + 1}/{len(self.groups)} 翻译失败: {str(e)}")
                    # 恢复原始文本
                    for sub in group:
                        sub.text = sub.original_text
                    self.translation_stats["fail_groups"] += 1
                    # 暂停一下避免连续失败
                    time.sleep(5)

                pbar.update(1)

                # 每5组暂停一下避免速率限制
                if (i + 1) % 5 == 0:
                    time.sleep(1)

        total_subs = len(self.subs)
        success_subs = sum(1 for sub in self.subs if sub.text != sub.original_text)
        fail_subs = total_subs - success_subs

        print(f"\n翻译统计:")
        print(f"- 字幕组: 共 {self.translation_stats['total_groups']} 组, "
              f"成功 {self.translation_stats['success_groups']} 组, "
              f"失败 {self.translation_stats['fail_groups']} 组")
        print(f"- 行数不匹配: {self.translation_stats['line_mismatches']} 次")
        print(f"- 字幕条: 共 {total_subs} 条, "
              f"成功翻译 {success_subs} 条, "
              f"失败 {fail_subs} 条")

        return True

    def save_translated(self):
        """保存翻译后的SRT文件"""
        if not self.subs:
            print("错误: 没有可保存的字幕")
            return False

        try:
            self.subs.save(self.output_file, encoding='utf-8')
            print(f"翻译完成! 结果已保存至: {self.output_file}")
            return True
        except Exception as e:
            print(f"保存翻译结果失败: {str(e)}")
            return False

    def run(self):
        """执行整个翻译流程"""
        if not self.load_srt():
            return False

        if not self.detect_language():
            return False

        if not self.group_subtitles():
            return False

        if not self.translate_all():
            return False

        if not self.save_translated():
            return False

        # 显示失败组的位置
        failed_groups = []
        for i, group in enumerate(self.groups):
            if any(sub.text == sub.original_text for sub in group):
                failed_groups.append(i + 1)

        if failed_groups:
            print("\n警告: 部分字幕组翻译失败，请检查以下组号:")
            print(", ".join(map(str, failed_groups)))

        return True


if __name__ == "__main__":
    # 配置参数
    API_KEY = "sk-a507b74c68fb4de8a9fdc778af54cdd8"  # 替换为您的DeepSeek API密钥
    INPUT_FILE = r"D:\Github\20240708Move_video_2\source_file\START-327.srt"  # 输入SRT文件路径
    OUTPUT_FILE = "translated.srt"  # 输出SRT文件路径

    # 创建并运行翻译器
    translator = SRTTranslator(API_KEY, INPUT_FILE, OUTPUT_FILE)
    if translator.run():
        print("字幕翻译流程完成!")
    else:
        print("字幕翻译过程中出现错误")