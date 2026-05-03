from typing import Optional

import whisper
from whisper.utils import get_writer

video = r'D:\Github\Spark-Translate\source_file\I Built an Illegal Minecraft Base.mp4'
model = whisper.load_model(r'D:\Github\Spark-Translate\Model\whisper_models\medium_en.pt')
srt_path = f"source_file/demo.srt"
output_dir = '/'.join(srt_path.split('/')[0:-1])
# with open(r'D:\Github\Spark-Translate\Test_Py_File\fe.txt', 'w+', encoding='utf-8') as f:
#     for i in result.keys():
#         f.write(f"{i}\n{result[i]}\n")

output_format = 'srt'
result = model.transcribe(video, fp16=True, language='en')
writer = get_writer(output_format, output_dir)
writer(result, srt_path, options={'max_words_per_line': 1000})
