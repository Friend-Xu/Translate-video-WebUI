import json
# 读取JSON文件
with open('dict.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
# 创建一个空字符串，用于存储最终要写入txt文件的内容
txt_content = ""
# 遍历字典，格式化键值对，并添加到txt_content中
for key, value in data.items():
    txt_content += f"{key}|||{value}\n"
# 写入到TXT文件
with open('output.txt', 'w', encoding='utf-8') as f:
    f.write(txt_content)
