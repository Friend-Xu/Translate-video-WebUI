import os
from tools.generaate_NoneVoice import SilentAudioGenerator
from SRT.SRT_Extract import SRT_Extra
from VAD_script.whisper_timestamped_VAD import VAD_segment
import subprocess
import time
from tqdm import tqdm
    # 初始化历史管理器
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.webm'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'}


def whisper_timestamped_extra(audio_path,target_dir,model="medium.en", lang="en",output_format="json"):
    from get_whisper_srt import get_write_srt, get_write_srt_timestamped
    json_path = f"{os.path.splitext(audio_path)[0]}.json"
    srt_path=f"{os.path.splitext(audio_path)[0]}.srt"
    if os.path.exists(json_path):
        print(json_path,"exist")
        get_write_srt_timestamped(json_path, srt_path)
        return 0
    model_dir = r"D:\Github\20240708Move_video_2\Model"

    print('提取视频字幕，等待Whisper运算结束...')
    whisper_timestamped_cmd = ["whisper_timestamped", f"{audio_path}",
                               "--model_dir", f"{model_dir}",
                               "--model", model,
                               "--device", "cuda",
                               "--language", lang,
                               "--output_dir", f"{target_dir}",  # os.path.dirname()
                               "--output_format", f"{output_format}",
                               # "--word_timestamps","True",
                               "--vad", "True",
                               "--compute_confidence", "False",
                               "--accurate"
                               # "--max_line_width", "42",
                               # "--max_line_count", "1"
                               ]
    subprocess.run(whisper_timestamped_cmd)
    print("提取完成")
    time.sleep(0.5)


    if output_format == 'srt':
        prev_srt = f"{os.path.join(os.path.dirname(audio_path), os.path.basename(audio_path))}.srt"
        os.rename(prev_srt, srt_path)
    elif output_format == "json":
        prev_json = f"{os.path.join(target_dir, os.path.basename(audio_path))}.words.json"
        os.rename(prev_json, json_path)

        # json_path = f"{os.path.splitext(self.video)[0]}.json"
        # from get_whisper_srt import get_write_srt
        # get_write_srt(prev_json, json_path)
    else:
        print('视频字幕已存在，开始下一步')
    get_write_srt_timestamped(json_path,srt_path )

def cut(audio_path):
    '''分割超大音频文件'''
    vad = VAD_segment(audio_path)
    VAD_list = vad.segment_worker(audio=audio_path, split_minute=13)
    print(VAD_list)
    vad.Thread_cut_worker(audio_path,VAD_list, max_workers=5)
def enumerate_dir_file(target_dir,file_format="audio")->list[str]:
    '''
    遍历文件夹所有文件
    file_format == audio or video
    "subdir"    : 返回一级子文件夹列表
    '''
    # 获取所有文件路径（带绝对路径）
    if file_format == "audio":
        files_list = [
            os.path.join(target_dir, f)
            for f in os.listdir(target_dir)
            if os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS
        ]
        return files_list
    elif file_format == "video":
        files_list = [
            os.path.join(target_dir, f)
            for f in os.listdir(target_dir)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
        ]
        return files_list
    elif file_format == "srt":
        files_list = [
            os.path.join(target_dir, f)
            for f in os.listdir(target_dir)
            if os.path.splitext(f)[1].lower() in {".srt"}
        ]
        return files_list
    # 处理子文件夹请求
    elif file_format == "subdir":
        subdirs = [
            os.path.join(target_dir, name)
            for name in os.listdir(target_dir)
            if os.path.isdir(os.path.join(target_dir, name))
        ]
        return subdirs
    else:
        raise ValueError("Invalid file format. Use 'audio', 'video' or 'srt'")
def srt(target_dir):
    '''遍历文件夹提取字幕'''
    """处理指定文件夹下的所有视频文件"""
    if not os.path.exists(target_dir):
        raise FileNotFoundError(f"文件夹不存在: {target_dir}")
    file_list = enumerate_dir_file(target_dir,file_format="audio")

    print(f"发现 {len(file_list)} 个待处理视频文件\n{file_list}")
    for path in file_list:
        # se = SRT_Extra(audio_path, path, output_format="json")
        whisper_timestamped_extra(path,target_dir, output_format="json")


if __name__ == "__main__":
    video_path = r"D:\Github\20240708Move_video_2\source_file\Learn Python GUI Development for Desktop – PySide6 and Qt Tutorial.mp4"
    audio_path = f"{os.path.dirname(video_path)}\\{os.path.basename(video_path)[:-4]}.wav"
    audio_name = os.path.basename(video_path)[:-4]
    VAD_file_dir = r"D:\Github\20240708Move_video_2\source_file\splitVideo"
    '''生成视频原音频'''
    if not os.path.isfile(audio_path):
        sil = SilentAudioGenerator(video_path)
        sil.generate_oringin_voice(audio_path)
        print("生成成功")

    # file_list = enumerate_dir_file(VAD_file_dir,file_format="audio")
    # for path in file_list:
    #     cut(path)
    for dir in tqdm(enumerate_dir_file(VAD_file_dir,file_format="subdir")):
        srt(dir)


