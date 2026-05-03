import re

import pysrt
class  extracted_subtitles():

    def __init__(self,input_file_path,output_file_path):
        self.file_path = input_file_path
        self.output_path = output_file_path
    def read_srt(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return content

    def extract_subtitles(self,content):
        # 匹配字幕内容
        pattern = re.compile(r'\d+\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n', re.DOTALL)
        matches = pattern.findall(content)

        subtitles = []
        for index,match in enumerate(matches,start=1):
            start_time, end_time, subtitle = match
            # 自动换行
            subtitle = subtitle.replace('\n', ' ')
            subtitles.append(f"{index}【{subtitle}】")  # 在每行字幕前后加上【】
            # subtitles.append(subtitle)

        return subtitles

    def write_subtitles_to_file(self,subtitles):

        with open(self.output_path, 'w', encoding='utf-8') as file:
            for subtitle in subtitles:
                file.write(subtitle + '\n')

        for i in range(0, len(subtitles), 50):
            chunk = subtitles[i:i + 50]
            file_number = i // 50 + 1
            output_path = f"{self.output_path}_{file_number}.txt"
            with open(output_path, 'w', encoding='utf-8') as file:
                for subtitle in chunk:
                    file.write(subtitle + '\n')
            print(f"字幕内容已提取并写入 {output_path}")

    def extracted_txt(self):
        # 读取srt文件内容
        srt_content = self.read_srt()

        # 提取字幕内容
        subtitles = self.extract_subtitles(srt_content)

        # 将提取的字幕内容写入文件
        self.write_subtitles_to_file(subtitles)
class replace_subtitles():
    def __init__(self,srt_file_path,txt_file_path,output_file_path):
        self.srt_file_path = srt_file_path
        self.txt_file_path = txt_file_path
        self.output_file_path = output_file_path


    def read_file(self,file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        return content

    def read_translations(self,txt_content):#单行译文
        translations = {}
        for line in txt_content.strip().split('\n'):
            match = re.match(r'(\d+)【(.*?)】', line)
            if match:
                index, translation = match.groups()
                translations[int(index)] = translation
        return translations
    def read_translations_(self,txt_content):#中英对照译文
        translations = {}
        # 正则表达式匹配数字和【】内的内容，允许跨行匹配
        pattern = re.compile(r'(\d+)\s*【(.*?)】(.*?)【(.*?)】', re.DOTALL)

        # 使用finditer查找所有匹配项
        matches = pattern.finditer(txt_content)

        for match in matches:
            index, original, _, translation = match.groups()
            translations[int(index)] = (original.strip(), translation.strip())
            # print((original.strip(), translation.strip()))
        return translations

    def replace_subtitles(self, translations):
        import difflib
        en_subtitles = pysrt.open(self.srt_file_path, encoding='utf-8')

        for index, subtitle in enumerate(en_subtitles,start=1):
            # 去除两端空白字符，并替换多个空格为单个空格
            text1 = " ".join(translations[index][0].split())
            text2 = " ".join(subtitle.text.split())
            # print(text2,"\n",text1)
            # 使用正则表达式分割文本，确保标点符号和单词一起被分割出来
            words_and_punctuations1 = re.findall(r'\w+|[^\w\s]', text1)
            words_and_punctuations2 = re.findall(r'\w+|[^\w\s]', text2)
            # 比较两个列表是否相同
            if  words_and_punctuations1 == words_and_punctuations2:

                subtitle.text = translations[index][1]
            else:
                # 查找第一个不同的位置
                diff_index = next(
                    (i for i, (w1, w2) in enumerate(zip(words_and_punctuations1, words_and_punctuations2)) if w1 != w2),
                    None)
                if diff_index is not None:
                    print(
                        f"第一个不同的位置在索引 {diff_index}：\n你为什么要将{index}段的: {words_and_punctuations2[diff_index]}输出为: {words_and_punctuations1[diff_index]}，请重新翻译整篇文档")
                # print('\033[33m',f"error：索引 {index} 的翻译内容与英文字幕不对齐",'\033[0m')
                # 输出不同的地方
                print(f"你在这里{index}【{translations[index]}】\n原文【{subtitle.text}】开始出错了，请不要篡改原文，请重新翻译整篇文档")
                # exit(f"error：索引 {index} 的翻译内容与英文字幕不对齐\nIndex:{index}\nZH:{translations[index]}\nEN:{subtitle.text}")
                exit("结束")
        return en_subtitles

    def repalce(self):
        # 读取文件内容

        txt_content = self.read_file(self.txt_file_path)

        # 提取TXT文件中的翻译内容
        translations = self.read_translations_(txt_content)

        # 替换字幕内容
        srt_content = self.replace_subtitles(translations)

        # 写入新的SRT文件
        srt_content.save(self.output_file_path, encoding='utf-8')

        print(f'字幕内容已替换并写入 {self.output_file_path}')

if __name__ == "__main__":
    # 示例文件路径
    input_file_path = 'D:\Github\Move_video\source_file\Mojang Is Now Banning Minecraft Mods_-collation.srt'
    output_file_path = 'extracted_subtitles.txt'

    srt_ins = extracted_subtitles(input_file_path,output_file_path)

    # 读取srt文件内容
    srt_content = srt_ins.read_srt()

    # 提取字幕内容
    subtitles = srt_ins.extract_subtitles(srt_content)

    # 将提取的字幕内容写入文件
    srt_ins.write_subtitles_to_file(subtitles)

    print(f'字幕内容已提取并写入 {output_file_path}')

    srt_file_path = r"D:\Github\Move_video\source_file\Mojang Is Now Banning Minecraft Mods_-collation.srt"
    txt_file_path = r"D:\Github\Move_video\source_file\2.txt"
    output_file_path = r"D:\Github\Move_video\source_file\Mojang Is Now Banning Minecraft Mods_-collation-ZH_CN.srt"

    replace_ins = replace_subtitles(srt_file_path,txt_file_path,output_file_path)

