import os
from pipeline.openvoice_cli.api import ToneColorConverter
import pipeline.openvoice_cli.se_extractor as se_extractor

def load_openvoice_model(version = "v2", device='cuda:0'):
    try:
        if version == "v2":
            checkpoints_dir = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}\Model\openvoice_v2"
        else:
            checkpoints_dir = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}\Model\openvoice_v1"
        # checkpoints_dir = r"D:\Github\20240708Move_video_2\openvoice_cli\checkpoints"
        ckpt_converter = os.path.join(checkpoints_dir, 'converter')
        tone_color_converter = ToneColorConverter(os.path.join(ckpt_converter, 'config.json'), device=device)
        tone_color_converter.load_ckpt(os.path.join(ckpt_converter, 'checkpoint.pth'))
        return tone_color_converter
    except Exception as e:
        print(f'\033[33m', e, '\033[0m')
def VAD_audio(color_path,output_path= r"..\speakers\Color_audio.WAV"):

    from speakers import Extra_Vocal
    Extra_Vocal.extra_vocal(color_path,output_path, vad_duration=8)
    return output_path

def convert_color_audio(audio_file,output_dir,ref_file,output_format=".wav"):
    tone_color_converter = load_openvoice_model()
    #克隆对象
    color_audio = VAD_audio(ref_file)
    if not os.path.isfile(audio_file):
        exit("文件不存在")
    target_se, _ = se_extractor.get_se(color_audio, tone_color_converter, vad=True)
    source_se, _ = se_extractor.get_se(audio_file, tone_color_converter, vad=True)
    #获取不带文件后缀的文件名字
    filename_without_extension = os.path.splitext(os.path.basename(audio_file))[0]

    output_filename = f"{filename_without_extension}_tuned{output_format}"
    output_file = os.path.join(output_dir, output_filename)
    # 运行色调颜色转换器
    tone_color_converter.convert(
        audio_src_path=audio_file,
        src_se=source_se,
        tgt_se=target_se,
        output_path=output_file,
        # message = "药药"
    )
    return output_file

if __name__ == "__main__":
    ref_file = r"D:\Github\20240708Move_video_2\speakers\中国纪录片-周涛\周涛.WAV"
    audio_file = r"D:\Github\20240708Move_video_2\source_file\1_9月1日 (4)_(Vocals).wav"
    output_dir = r"D:\Github\20240708Move_video_2\source_file"
    convert_color_audio(audio_file,output_dir,ref_file)