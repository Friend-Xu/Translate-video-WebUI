import os
import torch
from openvoice_cli import se_extractor
from openvoice_cli.api import ToneColorConverter


'''
初始化
在此示例中，我们将使用 OpenVoiceV2 中的检查点。
OpenVoiceV2 的训练更具侵略性
auamentations，因此在某些情况下表现出更好的鲁棒性
'''
ckpt_converter = r'D:\Github\20240708Move_video_2\openvoice_cli\checkpoints_v2/converter'
device = "cuda:0" if torch.cuda.is_available() else "cpu"
output_dir = 'outputs_v2'

tone_color_converter = ToneColorConverter(f'{ckpt_converter}/config.json', device=device)
tone_color_converter.load_ckpt(f'{ckpt_converter}/checkpoint.pth')

os.makedirs(output_dir, exist_ok=True)

'''
获取色调颜色嵌入
我们只提取目标扬声器的音调颜色嵌入。
源色调颜色嵌入可以直接从 checkpoints_v2/ses 文件夹中加载。
'''

reference_speaker = r'D:\Github\20240708Move_video_2\speakers\Color_audio.WAV' # 这是你想要克隆的声音
target_se, audio_name = se_extractor.get_se(reference_speaker, tone_color_converter, vad=False)
'''
使用 MeloTTS 作为基础扬声器
中文、日文、韩文。在以下示例中，
我们将使用 MeloTTS 中的模型作为基础扬声器 MeloTTs 是 @vy$heal 的一种高素质多语言文本转语音 ibrany，
支持英语的语言（美洲语、英国语、印度语、澳大利亚语、默认语、西班牙语、法语）
'''

from melo.api import TTS

texts = {
    'EN_NEWEST': "Did you ever hear a folk tale about a giant turtle?",  # The newest English base speaker model
    'EN': "Did you ever hear a folk tale about a giant turtle?",
    'ES': "El resplandor del sol acaricia las olas, pintando el cielo con una paleta deslumbrante.",
    'FR': "La lueur dorée du soleil caresse les vagues, peignant le ciel d'une palette éblouissante.",
    'ZH': "在这次vacation中，我们计划去Paris欣赏埃菲尔铁塔和卢浮宫的美景。",
    'JP': "彼は毎朝ジョギングをして体を健康に保っています。",
    'KR': "안녕하세요! 오늘은 날씨가 정말 좋네요.",
}

src_path = f'{output_dir}/tmp.wav'

# Speed is adjustable
speed = 1.0

for language, text in texts.items():
    model = TTS(language=language, device=device)
    speaker_ids = model.hps.data.spk2id

    for speaker_key in speaker_ids.keys():
        speaker_id = speaker_ids[speaker_key]
        speaker_key = speaker_key.lower().replace('_', '-')

        source_se = torch.load(f'checkpoints_v2/base_speakers/ses/{speaker_key}.pth', map_location=device)
        model.tts_to_file(text, speaker_id, src_path, speed=speed)
        save_path = f'{output_dir}/output_v2_{speaker_key}.wav'

        # Run the tone color converter
        encode_message = "@MyShell"
        tone_color_converter.convert(
            audio_src_path=src_path,
            src_se=source_se,
            tgt_se=target_se,
            output_path=save_path,
            message=encode_message)