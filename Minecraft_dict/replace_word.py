import json
import pysrt

def load_dictionary(file_path):
    with open(file_path, 'r', encoding='utf-8') as json_file:
        dictionary = json.load(json_file)
    return dictionary


def process_line(line, dictionary):
    processed_words = []
    # 去除标点符号
    line = line.strip('.,!?;:')
    # 在字典中查找最长匹配的字段
    max_match = ''
    for key in dictionary.keys():
        if key in line and len(key) > len(max_match):
            max_match = key
    # 如果找到匹配的字段，则替换为对应的值，否则保持原样
    if max_match:
        processed_word = dictionary[max_match]
    else:
        processed_word = line
    processed_words.append(processed_word)

    processed_line = ' '.join(processed_words)

    return processed_line


def process_srt(input_file, output_file, dictionary):
    subs = pysrt.open(input_file, encoding='utf-8')
    for sub in subs:
        sub.text = process_line(sub.text, dictionary)
    subs.save(output_file, encoding='utf-8')



def main():
    dictionary = load_dictionary('dict.json')
    process_srt('Making Minecraft As Satisfying As Possible With Mods-collation.srt', 'output.srt', dictionary)


if __name__ == "__main__":
    main()
