import pysrt
import re
def merge_subtitles(sub1, sub2):
    # 合并两个字幕的文本和时间
    merged_sub = pysrt.Subtitle()
    merged_sub.start = min(sub1.start, sub2.start)
    merged_sub.end = max(sub1.end, sub2.end)
    merged_sub.text = sub1.text + ' ' + sub2.text
    return merged_sub
def process_srt_file(input_file, output_file):
    subs = pysrt.open(input_file)
    new_subs = []
    sub_index = 0
    current_sub = subs[sub_index]
    current_text = current_sub.text.strip()
    if subs[sub_index+1]:
        next_text = subs[sub_index].text.strip()
        # 检查当前字幕和下一个字幕的末尾是否包含逗号或句号-
        if not current_text.endswith('.') or not current_text.endswith(','):
            if not next_text.startswith('.') or not next_text.startswith(','):
                ...
        #     current_sub.text += ' ' + sub.text
        # else:
        #     new_subs.append(current_sub)
        #     current_sub = sub

    new_subs.append(current_sub)

    # Save processed subtitles to a new SRT file
    pysrt.SubRipFile(new_subs).save(output_file, encoding='utf-8')

if __name__ == "__main__":
    input_file = "英文What Does it Actually Feel Like to be Shot.srt"
    output_file = "processed_srt.srt"

    process_srt_file(input_file, output_file)
