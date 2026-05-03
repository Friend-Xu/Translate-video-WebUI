import requests
from bs4 import BeautifulSoup

'''
提取网页中的链接以及跳转按钮文本
'''
def get_all_links(url):
    # 创建会话对象
    session = requests.Session()

    # 设置请求头，模拟浏览器
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 发送HTTP请求
    response = session.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to retrieve the webpage: {response.status_code}")
        return []

    # 解析HTML内容
    soup = BeautifulSoup(response.content, 'html.parser')

    # 查找所有<a>标签
    links = soup.find_all('a')

    # 提取href属性中的链接和文本内容
    links_texts = [(link.get_text(strip=True), link.get('href')) for link in links if link.get('href')]

    return links_texts

def save_to_txt(links_texts, filename):
    with open(filename, 'w', encoding='utf-8') as file:
        for text, link in links_texts:
            file.write(f"{text}：{link}\n")
# 示例调用
url = 'https://mc-mod.gg/50-rpg-mods-ep-1'
all_links_texts = get_all_links(url)

# 将结果保存到txt文件
filename = 'output_links.txt'
save_to_txt(all_links_texts, filename)

print(f"链接和文本已保存到v{filename}")
