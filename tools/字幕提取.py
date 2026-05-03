
import subprocess,time,os


def whisper_timestamped_extra(self,model = "medium.en",lang = "en"):
    # srt_path = ""
    model_dir = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}\Model"

    print('提取视频字幕，等待Whisper运算结束...')
    whisper_timestamped_cmd = ["whisper_timestamped",f"{self.video_Vocal_path}",
                    "--model_dir",f"{model_dir}",
                   "--model",model,
                    "--device","cuda",
                    "--language",lang,
                    "--output_dir",f"{os.path.dirname(self.video)}",#os.path.dirname()
                    "--output_format",f"{self.output_format}",
                   # "--word_timestamps","True",
                   "--vad","True",
                   "--compute_confidence","False",
                    "--accurate"
                   # "--max_line_width", "42",
                   # "--max_line_count", "1"
    ]
    subprocess.run(whisper_timestamped_cmd)
    print("提取完成")
    time.sleep(0.5)

    # if self.output_format == 'srt':
    #     prev_srt = f"{os.path.join(os.path.dirname(self.video), os.path.basename(self.video_Vocal_path))}.srt"
    #     os.rename(prev_srt, self.srt_path)
    # elif self.output_format == "json":
    #     prev_json = f"{os.path.join(os.path.dirname(self.video), os.path.basename(self.video_Vocal_path))}.words.json"
    #     os.rename(prev_json, self.json_path)
    #
    # else:
    #     print('视频字幕已存在，开始下一步')


def whisper_extra(audio,model="medium.en",lang = "en",output_format="srt"):
    model_dir = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}\Model\whisper"
    # json_path = f"{os.path.dirname(self.video)}\\1_{os.path.basename(self.video)[:-4]}_(Vocals).json"
    # if not os.path.isfile(json_path):
    print('提取视频字幕，等待Whisper运算结束...')
    # self.output_format = "json"
    whisper_cmd = ["whisper", f"{audio}",
                   "--model_dir", f"{model_dir}",
                   "--model", f"{model}",
                   "--device", "cuda",
                   "--language", lang,
                   "--output_dir", f"{os.path.dirname(audio)}",
                   "--output_format", f"{output_format}",
                   "--word_timestamps", "True",
                   # "--max_line_width", "42",
                   # "--max_line_count", "1"
                   ]
    subprocess.run(whisper_cmd)
    # if output_format == 'srt':
    #     prev_srt = f"{os.path.dirname(audio)}\\1_{os.path.basename(audio)[:-4]}_(Vocals).srt"
    #     os.rename(prev_srt, srt_path)

if __name__ == "__main__":
    audio = r"D:\Github\20240708Move_video_2\source_file\1_9月1日 (4)_(Vocals).wav"
    whisper_extra(audio)