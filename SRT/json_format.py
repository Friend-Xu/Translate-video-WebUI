import json

# 读取JSON文件
with open(r'/source_file/1_TOP 10 Best Minecraft Gun Mods (1.20.4 - 1.12.2)_(Vocals).json',
          'r', encoding='utf-8') as file:
    data = json.load(file)

# 将JSON数据格式化
formatted_json = json.dumps(data, indent=4, ensure_ascii=False)

# 将格式化后的JSON写回文件
with open(r'D:\Github\20240708Move_video_2\source_file\formatted_data.json', 'w', encoding='utf-8') as file:
    file.write(formatted_json)

print("JSON文件已格式化并保存为formatted_data.json")
