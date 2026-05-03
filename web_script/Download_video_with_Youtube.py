import re
import os
# from pytube import YouTube
import requests

def pytubefix_get_video(url):
    from pytubefix import YouTube
    youtube = YouTube(url, proxies={'https': '127.0.0.1:7890'})
    video_title = youtube.title
    # video_title = ""
    # stream = youtube.streams.first()
    video_description = youtube.description
    print(video_description)
    video_url = url
    # stream = youtube.streams.filter(adaptive=True, file_extension="mp4")
    # audioStream = stream.order_by('abr').desc().first()
    # audioStream.download(filename=f'.\source_file\{video_title}.wav')
    # videoStream = stream.order_by('resolution').desc().first()
    # video_description = youtube.description
    # videoStream.download(filename=f'.\source_file\{video_title}.mp4', max_retries=10)
    #获取字幕
    # caption = youtube.captions.get_by_language_code('en')
    # if caption:
    #     caption.save_captions("source_file\captions.txt")
    #视频封面
    thumbnail_url = youtube.thumbnail_url
    print(thumbnail_url)
    author = youtube.author
    # author = ""
    thumbnail_path = r'../source_file/thumbnail.jpg'
    try:
        response = requests.get(thumbnail_url, proxies={'https': '127.0.0.1:7890'})
        with open(thumbnail_path, 'wb') as file:
            file.write(response.content)
    except Exception as e:
        print("下载图片时出错:", e)

    # 下载视频
    # video.download()
    return video_title,video_description,  video_url,thumbnail_path ,author#
def pytube_get_video(url):
    from pytube import YouTube
    youtube = YouTube(url, proxies={'https': '127.0.0.1:7890'})
    video_title = youtube.title
    video_url = url
    video_description = youtube.description
    print(video_description)
    # stream = youtube.streams.filter(adaptive=True, file_extension="mp4")
    # audioStream = stream.order_by('abr').desc().first()
    # audioStream.download(filename=f'.\source_file\{video_title}.wav')
    # videoStream = stream.order_by('resolution').desc().first()

    # videoStream.download(filename=f'.\source_file\{video_title}.mp4', max_retries=10)
    # video_description = youtube.description
    # 视频封面
    thumbnail_url = youtube.thumbnail_url
    print(thumbnail_url)
    author = youtube.author
    # author = ""
    try:
        response = requests.get(thumbnail_url,proxies={'https': '127.0.0.1:7890'})
        with open(r'../source_file/thumbnail.jpg', 'wb') as file:
            file.write(response.content)
    except Exception as e:
        print("下载图片时出错:", e)
    return video_title, video_description, video_url, thumbnail_url, author  #
def remove_urls_and_empty_lines(file_path,output_file):
    # 正则表达式，用于匹配 URL
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\$\$,]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )

    # 打开并读取文件内容
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # 移除每行中的 URL 并过滤空行
    filtered_lines = [
        url_pattern.sub('', line) for line in lines if line.strip()
    ]
    filtered_lines = [
        line for line in filtered_lines if line.strip()
    ]
    # 将处理后的内容保存到新文件
    with open(output_file, 'w', encoding='utf-8') as file:
        file.writelines(filtered_lines)

if __name__ == '__main__':
    url = "https://youtu.be/BWSt0QiYga4?si=KWFfwsCM-R8VEQcS"
    description_path = "../source_file/模组链接.txt"

    if os.path.isfile(description_path):
        os.remove(description_path)

    del_http_path = r"../source_file/mods.txt"
    if os.path.isfile(del_http_path):
        os.remove(del_http_path)

    # title,description, video_url ,thumbnail_url ,author= get_video_info(url) #
    title,description, video_url ,thumbnail_path ,author=pytubefix_get_video(url) #
    with open(description_path,"a+",encoding="utf-8") as f:
        f.write(description)
        f.write(f"\n原视频 Youtube {author}：{video_url}")

    print(f'视频标题: {title}')
    # print(f'视频简介: {description}')
    # print(f'视频链接: {video_url}')
    # print("封面链接:"+thumbnail_url)
    print(f"\n原视频 Youtube {author}：{video_url}")
    # print(f"视频封面:{thumbnail_url}")
    remove_urls_and_empty_lines(description_path,del_http_path)
    from SwinIR.predict import Predictor
    pre = Predictor()
    pre.setup()
    pre.predict(image=os.path.abspath(thumbnail_path))
