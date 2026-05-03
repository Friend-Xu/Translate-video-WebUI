from moviepy.editor import AudioFileClip, VideoFileClip
import numpy as np
from whisper_timestamped.transcribe import get_audio_tensor, get_vad_segments

class VAD_SRT():
    def __init__(self,audio_path):
        self.audio_path = audio_path
    def moviepy_cut_video(self,input_path, output_path, start_time, end_time):
        with VideoFileClip(input_path) as video:
            new_video = video.subclip(start_time, end_time)
            new_video.write_videofile(output_path, codec="libx264")

    def audio_segments(self, target_dir, silence_threshold=10):
        SAMPLE_RATE = 16000  # 采样率
        audio_dur = AudioFileClip(self.audio_path).duration / 60
        print("正在进行VAD检测...")
        audio_vad = get_audio_tensor(audio_path)
        segments = get_vad_segments(
            audio_vad,
            output_sample=True,
            min_speech_duration=0.1,
            min_silence_duration=1,
            method="silero",
        )

        segments = [(seg["start"], seg["end"]) for seg in segments]
        segments = [(float(s) / SAMPLE_RATE, float(e) / SAMPLE_RATE) for s, e in segments]
        print("VAD检测结果：", segments)

        result_list = []
        start = 0
        for i in range(1,len(segments)-1):
            prev_end = segments[i-1][1]
            current_start = segments[i][0]
            silence_duration = current_start - prev_end
            if silence_duration >= silence_threshold:
                result_list.append((start,prev_end))
                start = current_start

        if segments[-1][1] not in result_list:
            result_list.append((start,segments[-1][1]))

        print("分界点", result_list)
        print(f"输出到：{target_dir}")

        # for i in range(0, len(result_list) - 1, 2):
        #     start_time = result_list[i]
        #     end_time = result_list[i + 1]
        #     output_file = f"{target_dir}\\temp_{start_time}_{end_time}.mp4"
        #     self.moviepy_cut_video(video, output_file, start_time, end_time)
    def split_video_vad(self,*args):
        ...
# 调用函数进行视频分割
audio_path = r"/source_file/1_50  Vanilla Mods That Enhance Minecraft Experience [Forge]_(Vocals).wav"
cut_clip = VAD_SRT(audio_path)

cut_clip.audio_segments("output_directory")
