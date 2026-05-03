
import subprocess

def mix_video_audio(input_video, input_audio, output_video):
    # 构建ffmpeg命令
    command = [
        'ffmpeg',
        '-i', input_video,  # 输入视频文件
        '-i', input_audio,  # 输入音频文件
        '-c:v', 'copy',  # 复制视频流
        '-c:a', 'aac',  # 编码音频为aac格式
        '-strict', 'experimental',
        '-map', '0:v:0',  # 映射第一个视频流
        '-map', '1:a:0',  # 映射第一个音频流
        output_video  # 输出文件
    ]

    # 使用subprocess运行ffmpeg命令
    try:
        subprocess.run(command, check=True)
        print("视频音频设置成功！")
    except subprocess.CalledProcessError as e:
        print(f"发生错误: {e}")


if __name__ == "__main__":
    # 定义输入和输出文件路径
    input_video = r"D:\Github\20240708Move_video_2\source_file\videoplayback.mp4"
    input_audio = r"D:\Github\20240708Move_video_2\source_file\videoplayback.m4a"
    output_video =r"D:\Github\20240708Move_video_2\source_file\Dawncraft Echoes of Legends 100 Days All Bosses Full Movie.mp4"

    mix_video_audio(input_video, input_audio, output_video)
