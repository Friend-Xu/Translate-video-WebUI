import re
import os
def convert_txt_to_html(input_file, output_file):
    # 打开输入的txt文件
    with open(input_file, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # 开始生成HTML内容
    html_content = '<html>\n<head>\n<title>Converted HTML</title>\n<style>\n'
    html_content += '  .highlight { font-weight: bold; color: red; }\n'
    html_content += '</style>\n</head>\n<body>\n'

    # 正则表达式匹配URL
    url_pattern = re.compile(r'https?://[^\s]+')

    for line in lines:
        # 查找所有URL并保留
        urls = url_pattern.findall(line)
        for i, url in enumerate(urls):
            line = line.replace(url, f'URL_PLACEHOLDER_{i}')

        # 将冒号替换为全角冒号
        line = line.replace(':', '：').replace('：', '：')

        # 处理全角和半角冒号分割
        parts = re.split(r'(?<!URL_PLACEHOLDER_\d)[:：]', line)
        processed_parts = []

        for part in parts:
            if 'URL_PLACEHOLDER_' in part:
                processed_parts.append(part)
            else:
                processed_parts.append(f'<span class="highlight">{part}</span>')

        processed_text = '：'.join(processed_parts)

        # 将URL占位符替换回URL，并生成可点击的链接
        for i, url in enumerate(urls):
            processed_text = processed_text.replace(f'URL_PLACEHOLDER_{i}', f'<a href="{url}" target="_blank">{url}</a>')

        # 生成HTML段落
        html_content += f'<p>{processed_text}</p>\n'

    # 结束生成HTML内容
    html_content += '</body>\n</html>'

    # 将HTML内容写入输出的html文件
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write(html_content)

if __name__ == '__main__':
    # 输入和输出文件路径
    input_file = r'D:\Github\20240708Move_video_2\source_file\模组链接.txt'
    output_file = f"{os.path.splitext(input_file)[0]}.html"

    # 调用函数进行转换
    convert_txt_to_html(input_file, output_file)

    print(f"HTML 文件已创建于{output_file}")