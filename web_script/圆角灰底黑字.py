import re

import re
import os

def convert_txt_to_html(input_file, output_file):
    # Open the input txt file
    with open(input_file, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # Start generating HTML content
    html_content = '''
<html>
<head>
<title>模组链接 搬运工药药</title>
<style>
    body { font-family: Arial, sans-serif; }
    .highlight { 
        display: inline-block; 
        background: #f0f0f0; 
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
'''

    # 用于匹配 URL 的正则表达式
    url_pattern = re.compile(r'https?://[^\s]+')

    for line in lines:
        # Find all URLs and keep them
        urls = url_pattern.findall(line)
        for i, url in enumerate(urls):
            line = line.replace(url, f'URL_PLACEHOLDER_{i}')

        # Replace colons with full-width colons
        line = line.replace(':', '：').replace('：', '：')

        # Split by full-width and half-width colons
        parts = re.split(r'(?<!URL_PLACEHOLDER_\d)[:：]', line)
        processed_parts = []

        for part in parts:
            if 'URL_PLACEHOLDER_' in part:
                processed_parts.append(part)
            else:
                processed_parts.append(f'<span class="highlight">{part}</span>')

        processed_text = '：'.join(processed_parts)

        # Replace URL placeholders back to URLs and generate clickable links
        for i, url in enumerate(urls):
            processed_text = processed_text.replace(f'URL_PLACEHOLDER_{i}', f'<a href="{url}" target="_blank">{url}</a>')

        # Generate HTML paragraph
        html_content += f'<p>{processed_text}</p>\n'

    # End generating HTML content
    html_content += '</body>\n</html>'

    # Write HTML content to the output HTML file
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write(html_content)

if __name__ == '__main__':
    # Input and output file paths
    input_file = r'D:\Github\20240708Move_video_2\source_file\模组链接.txt'
    output_file = f"{os.path.splitext(input_file)[0]}.html"

    # Call the function to convert
    convert_txt_to_html(input_file, output_file)

    print(f"HTML file created at {output_file}")


# 示例用法：
# convert_to_html(r'D:\Github\20240708Move_video_2\web_script\output_links.txt', r'D:\Github\20240708Move_video_2\web_script\output_links.html')
