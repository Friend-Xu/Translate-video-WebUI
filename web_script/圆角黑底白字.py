import re
import os

def convert_txt_to_html(input_file, output_file):
    # Open the input txt file
    with open(input_file, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # 开始生成 HTML 内容
    html_content = """
                    <html>
                    <head>
                    <title>模组链接 搬运工药药</title>
                    <style>
                        body { font-family: Arial, sans-serif; }
                        .highlight { 
                            display: inline-block; 
                            background: #000; 
                            color: #fff;
                            border-radius: 10px; 
                            padding: 5px 10px; 
                        }
                        a {
                            display: inline-block; 
                            border: 2px solid transparent; 
                            border-radius: 10px; 
                            padding: 2px 6px; 
                            text-decoration: none;
                            color: blue;
                            transition: border-color 0.5s ease-in-out;
                        }
                        a:hover {
                            border-color: #00f;
                        }
                    </style>
                    </head>
                    <body>
                    """

    # 用于匹配 URL 的正则表达式
    url_pattern = re.compile(r'https?://[^\s]+')

    for line in lines:
        # 如果该行为空，请添加一个简单的换行符
        if line.strip() == '':
            html_content += '<br>\n'
            continue

        # 查找所有 URL 并保留它们
        urls = url_pattern.findall(line)
        for i, url in enumerate(urls):
            line = line.replace(url, f'URL_PLACEHOLDER_{i}')

        # 将冒号替换为全角冒号
        line = line.replace(':', '：').replace('：', '：')

        # 按 URL 占位符分割文本，并保留占位符
        parts = re.split(r'(URL_PLACEHOLDER_\d+)', line)
        processed_parts = []

        for part in parts:
            if re.match(r'URL_PLACEHOLDER_\d+', part):
                processed_parts.append(part)
            else:
                # 处理非 URL 部分
                sub_parts = re.split(r'[:：]', part)
                highlighted_sub_parts = [f'<span class="highlight">{sub_part}</span>' for sub_part in sub_parts if sub_part]
                processed_parts.append('：'.join(highlighted_sub_parts))

        # 将 URL 占位符替换回 URL 并生成可点击的链接
        for i, url in enumerate(urls):
            # 去掉 URL 后面的冒号
            processed_parts = [part.replace(f'URL_PLACEHOLDER_{i}', f'<a href="{url.rstrip("：")}" target="_blank">{url.rstrip("：")}</a>') for part in processed_parts]

        # 生成 HTML 段落，并移除可能存在的空 highlight 标签
        processed_text = "</a>".join(processed_parts).replace('</a><span class="highlight">1', '')

        html_content += f'<p>{processed_text}</p>\n'

    # 结束生成 HTML 内容
    html_content += '</body>\n</html>'

    # 将 HTML 内容写入输出 HTML 文件
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write(html_content)

if __name__ == '__main__':
    # Input and output file paths
    input_file = r'D:\Github\20240708Move_video_2\web_script\output_links.txt'
    output_file = f"{os.path.splitext(input_file)[0]}.html"

    # 调用函数进行转换
    convert_txt_to_html(input_file, output_file)

    print(f"HTML file created at {output_file}")
