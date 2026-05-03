import json
import pysrt
import re
import os


def load_dictionary(file_path):
    with open(file_path, 'r', encoding='utf-8') as json_file:
        dictionary = json.load(json_file)
    return dictionary

# 定义一个函数，用于删除空行
def format_srt(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    formatted_lines = []
    i = 0
    while i < len(lines):
        if re.match(r'^\d+$', lines[i].strip()) and i + 1 < len(lines) and re.match(r'^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$', lines[i + 1].strip()):
            # 添加索引行和时间戳行
            formatted_lines.append(lines[i].strip())
            formatted_lines.append(lines[i + 1].strip())
            i += 2
            # 收集字幕文本行，跳过空行（如果有）
            if i < len(lines) and lines[i].strip() == '':
                i += 1
            while i < len(lines) and lines[i].strip():
                formatted_lines.append(lines[i].strip())
                i += 1
            # 添加空行以分隔块
            formatted_lines.append('')
        else:
            i += 1

    # 删除最后添加的空行（如果存在）
    if formatted_lines and formatted_lines[-1] == '':
        formatted_lines.pop()

    with open(output_file, 'w', encoding='utf-8') as f:
        for line in formatted_lines:
            f.write(line + '\n')

def process_text(text, dictionary):
    # words = re.findall(r'\b\w+\b', text)
    for key in dictionary.keys():
        if key in text:
            text = text.replace(key,dictionary[key])
            print(f"{key}-->{dictionary[key]}")
    return text.strip()

def process_srt(input_file, output_file, dictionary):
    subs = pysrt.open(input_file, encoding='utf-8')

    for sub in subs:
        # print("-----------")
        sub.text = process_text(sub.text.strip(), dictionary)

    subs.save(output_file, encoding='utf-8')


def main(input_file,output_file):

    current_dir = os.path.dirname(os.path.realpath(__file__))
    dictionary = load_dictionary(f'{current_dir}\dict_zh.json')

    re_file = f"{os.path.dirname(input_file)}\\{os.path.basename(input_file)[:-4]}_format.srt"
    format_srt(input_file, re_file)

    process_srt(re_file,output_file, dictionary)


if __name__ == "__main__":
    # 调用函数，传入字幕文件路径和输出文件路径
    input_file  = r"D:\Github\Move_video\source_file\12 Mods That Add New Bosses To Minecraft 1.20.2 - 1.12 (Forge & Fabric)-collation-ZH_CN.srt"
    output_file = r"D:\Github\Move_video\source_file\123.srt"
    result = "D:\Github\Move_video\source_file\We Spent 2 YEARS making a Minecraft RPG Modpack. Here's what we've made.-collation-ZH_CN-repalce.srt"
    format_srt(input_file, output_file)
    main(output_file,result)

