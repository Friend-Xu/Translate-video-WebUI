from moviepy.editor import VideoFileClip,AudioFileClip
import numpy as np
import os
from moviepy.editor import VideoFileClip


class SilentAudioGenerator:
    def __init__(self, video_path):
        self.video = VideoFileClip(video_path)
        self.duration = self.video.duration
        self._get_audio_params()

    def _get_audio_params(self):
        if self.video.audio:
            self.sample_rate = self.video.audio.fps
            self.n_channels = self.video.audio.reader.nchannels
        else:
            self.sample_rate = 48000  # 专业视频常用采样率
            self.n_channels = 2
    def generate_oringin_voice(self,output_Vocal_path):
        if not os.path.isfile(output_Vocal_path):
            # 读取视频并获取参数
            video = self.video
            duration = video.duration  # 精确到秒的小数
            # 获取原音频参数（如果存在）
            if video.audio:
                print("使用源音频参数")
                fps = video.audio.fps  # 采样率（例如 44100）
                n_channels = video.audio.reader.nchannels  # 声道数
                print(f"采样率:{fps}\n声道数:{n_channels}")
            else:
                print("使用默认音频参数")
                fps = 48000  # 默认采样率（专业视频常用）
                n_channels = 2  # 默认立体声

            # 修正关键：正确的 make_frame 函数
            self.video.audio.write_audiofile(output_Vocal_path,
                                             fps = fps,  # 采样率（例如 44100）
                                             # verbose=False,
                                            # n_channels = n_channels,# 声道数
                                             )
        else:
            print("存在源音频")
    def generate_None_voice(self, oringin_file,output_path):
        from pydub import AudioSegment
        if not os.path.isfile(oringin_file):
            raise "请输入正确音频路径"
        else:
            if not os.path.isfile(output_path):
                origin_audio = AudioSegment.from_file(oringin_file)
                oringin_audio_duration_milliseconds=len(origin_audio)
                # 显式继承原音频参数
                sample_rate = origin_audio.frame_rate  # 采样率（例如 44100）
                channels = origin_audio.channels  # 声道数（1=单声道，2=立体声）
                sample_width = origin_audio.sample_width  # 采样位宽（例如 2=16-bit）
                # 生成参数完全一致的静音
                silence = AudioSegment.silent(
                    duration=oringin_audio_duration_milliseconds,
                    frame_rate=sample_rate
                ).set_channels(channels).set_sample_width(sample_width)
                # 导出时强制指定参数（关键步骤！）
                silence.export(
                    output_path,
                    format="wav",  # 优先使用无损格式
                    bitrate=f"{origin_audio.frame_rate * origin_audio.sample_width * 8}k",
                    parameters=["-ar", str(sample_rate), "-ac", str(channels)]
                )
                print(f"原视频：{AudioFileClip(output_path).duration}\n空白音频：{AudioFileClip(output_path).duration}")
            else:
                if AudioFileClip(output_path).duration!=AudioFileClip(oringin_file).duration:
                    print(f"原视频：{AudioFileClip(oringin_file).duration}\n空白音频：{AudioFileClip(output_path).duration}")
                    raise "生成的音频时长与原音频不相等！"
if __name__ == "__main__":
    mp4video = r"D:\Github\20240708Move_video_2\source_file\Learn Python GUI Development for Desktop – PySide6 and Qt Tutorial.mp4"
    # 使用示例
    video_instrumental_path = f"{os.path.dirname(mp4video)}\\1_{os.path.basename(mp4video)[:-4]}_(Instrumental).wav"
    video_Vocal_path = f"{os.path.dirname(mp4video)}\\1_{os.path.basename(mp4video)[:-4]}_(Vocals).wav"
    generator = SilentAudioGenerator(mp4video)
    generator.generate_oringin_voice(video_Vocal_path)
    # generator.generate_None_voice(video_Vocal_path,video_instrumental_path)