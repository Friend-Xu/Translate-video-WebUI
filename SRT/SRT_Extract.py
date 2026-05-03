import math
import shutil
import re
from datetime import timedelta
from typing import Optional, List, Tuple
import torch
import subprocess
import os
import time
import json

import sys
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("srt_extractor.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SRT_Extractor")

'''
whisper_timestamped: (choose from 'af', 'am', 'ar', 'as', 'az', 'ba', 'be', 'bg', 
'bn', 'bo', 'br', 'bs', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'es', 
'et', 'eu', 'fa', 'fi', 'fo', 'fr', 'gl', 'gu', 'ha', 'haw', 'he', 'hi', 'hr', 
'ht', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'jw', 'ka', 'kk', 'km', 'kn', 'ko',
'la', 'lb', 'ln', 'lo', 'lt', 'lv', 'mg', 'mi', 'mk', 'ml', 'mn', 'mr',
'ms', 'mt', 'my', 'ne', 'nl', 'nn', 'no', 'oc', 'pa', 'pl', 'ps', 'pt',
'ro', 'ru', 'sa', 'sd', 'si', 'sk', 'sl', 'sn', 'so', 'sq', 'sr', 'su', 
'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk', 'tl', 'tr', 'tt', 'uk', 'ur',
'uz', 'vi', 'yi', 'yo', 'yue', 'zh', 'Afrikaans', 'Albanian', 'Amharic', 
'Arabic', 'Armenian', 'Assamese', 'Azerbaijani', 'Bashkir', 'Basque', 'Belarusian', 
'Bengali', 'Bosnian', 'Breton', 'Bulgarian', 'Burmese', 'Cantonese', 'Castilian', 
'Catalan', 'Chinese', 'Croatian', 'Czech', 'Danish', 'Dutch', 'English', 'Estonian',
'Faroese', 'Finnish', 'Flemish', 'French', 'Galician', 'Georgian', 'German', 'Greek',
'Gujarati', 'Haitian', 'Haitian Creole', 'Hausa', 'Hawaiian', 'Hebrew', 'Hindi', 'Hungarian',
'Icelandic', 'Indonesian', 'Italian', 'Japanese', 'Javanese', 'Kannada', 'Kazakh', 
'Khmer', 'Korean', 'Lao', 'Latin', 'Latvian', 'Letzeburgesch', 'Lingala', 
'Lithuanian', 'Luxembourgish', 'Macedonian', 'Malagasy', 'Malay', 'Malayalam',
'Maltese', 'Mandarin', 'Maori', 'Marathi', 'Moldavian', 'Moldovan', 'Mongolian', 
'Myanmar', 'Nepali', 'Norwegian', 'Nynorsk', 'Occitan', 'Panjabi', 'Pashto', 
'Persian', 'Polish', 'Portuguese', 'Punjabi', 'Pushto', 'Romanian', 'Russian', 
'Sanskrit', 'Serbian', 'Shona', 'Sindhi', 'Sinhala', 'Sinhalese', 'Slovak', 
'Slovenian', 'Somali', 'Spanish', 'Sundanese', 'Swahili', 'Swedish', 'Tagalog', 
'Tajik', 'Tamil', 'Tatar', 'Telugu', 'Thai', 'Tibetan', 'Turkish', 'Turkmen', 
'Ukrainian', 'Urdu', 'Uzbek', 'Valencian', 'Vietnamese', 'Welsh', 'Yiddish', 'Yoruba')'''


class SRT_Extractor():
    def __init__(self, audio_path: str,lang='en', output_format='srt'):
        """
        audio_path: 音频文件绝对路径
        output_format: 输出格式 (srt/json)
        """
        self.audio_path = audio_path
        self.output_format = output_format
        self.base_name = os.path.splitext(audio_path)[0]
        # 新增：存储音频时长
        self.audio_duration = self._get_audio_duration()
        # 确保输出文件与音频文件同名
        self.srt_path = f"{self.base_name}.srt"
        self.json_path = f"{self.base_name}.json"
        self.lang = lang
        # 确保输出目录存在
        output_dir = os.path.dirname(self.audio_path)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"创建输出目录: {output_dir}")

    # 新增方法：使用moviepy获取音频时长
    def _get_audio_duration(self):
        """使用moviepy获取音频文件的时长（秒）"""
        try:
            # 尝试导入moviepy
            from moviepy.editor import AudioFileClip

            # 使用moviepy获取时长
            with AudioFileClip(self.audio_path) as audio:
                return audio.duration
        except ImportError:
            logger.warning("moviepy未安装，将尝试使用pydub获取时长")
            return self._get_audio_duration_with_pydub()
        except Exception as e:
            logger.error(f"获取音频时长失败: {str(e)}", exc_info=True)
            return 0
        # 新增方法：使用pydub获取音频时长

    def _get_audio_duration_with_pydub(self):
        """使用pydub获取音频时长（秒）"""
        try:
            # 尝试导入pydub
            from pydub import AudioSegment

            # 使用pydub获取时长
            audio = AudioSegment.from_file(self.audio_path)
            return len(audio) / 1000.0  # 毫秒转秒
        except ImportError:
            logger.warning("pydub未安装，将尝试使用FFmpeg获取时长")
            return self._estimate_duration_with_ffmpeg()
        except Exception as e:
            logger.error(f"使用pydub获取时长失败: {str(e)}", exc_info=True)
            return 0
        # 新增方法：使用FFmpeg估算时长

    def _estimate_duration_with_ffmpeg(self):
        """使用FFmpeg估算音频时长（秒）"""
        try:
            # 检查FFmpeg是否可用
            if not shutil.which("ffmpeg"):
                logger.warning("FFmpeg未安装，无法获取准确时长")
                return 0

            # 构建FFmpeg命令获取时长
            command = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                self.audio_path
            ]

            # 执行命令并捕获输出
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()

            if process.returncode != 0:
                logger.error(f"FFmpeg执行失败: {stderr.strip()}")
                return 0

            # 解析输出并转换为浮点数
            return float(stdout.strip())
        except Exception as e:
            logger.error(f"FFmpeg时长估算失败: {str(e)}", exc_info=True)
            return 0
    def _format_json(self, json_path):
        """格式化JSON文件 - 使用更安全的编码处理"""
        try:
            logger.info(f"尝试格式化JSON文件: {json_path}")
            # 使用二进制读写避免编码问题
            with open(json_path, 'rb') as f:
                raw_data = f.read()

            # 尝试不同编码
            try:
                data = json.loads(raw_data.decode('utf-8'))
            except UnicodeDecodeError:
                try:
                    data = json.loads(raw_data.decode('utf-16'))
                except:
                    data = json.loads(raw_data.decode('latin-1'))

            # 使用UTF-8编码写回
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            logger.info(f"JSON文件格式化成功: {json_path}")
        except Exception as e:
            logger.error(f"JSON格式化失败: {str(e)}", exc_info=True)

    def _should_regenerate(self, check_path: Optional[str] = None):
        """检查是否需要重新生成文件
        
        Args:
            check_path: 自定义检查路径，传入时优先检查此路径而非默认路径
        """
        if check_path:
            return not os.path.exists(check_path) or os.path.getsize(check_path) == 0
        if self.output_format == "srt":
            return not os.path.exists(self.srt_path) or os.path.getsize(self.srt_path) == 0
        elif self.output_format == "json":
            return not os.path.exists(self.json_path) or os.path.getsize(self.json_path) == 0
        return True

    def _convert_to_srt(self, result, srt_path):
        """使用Json_Convert_Srt的转换方法"""
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(srt_path)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            # 处理不同输入类型
            if isinstance(result, str) and os.path.exists(result):
                # 如果传入的是文件路径，直接转换
                from Json_Convert_Srt import convert_json_to_srt
                srt_content = convert_json_to_srt(result)
                with open(srt_path, 'w', encoding='utf-8') as f:
                    f.write(srt_content)
                logger.info(f"成功生成SRT文件: {srt_path}")

            elif isinstance(result, dict):
                # 如果传入的是字典，先保存为临时JSON文件再转换
                temp_json_path = f"{self.base_name}_temp.json"
                with open(temp_json_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False)

                from Json_Convert_Srt import convert_json_to_srt
                srt_content = convert_json_to_srt(temp_json_path)
                with open(srt_path, 'w', encoding='utf-8') as f:
                    f.write(srt_content)

                # 删除临时文件
                if os.path.exists(temp_json_path):
                    os.remove(temp_json_path)

                logger.info(f"成功生成SRT文件: {srt_path}")
            else:
                logger.error(f"无法识别的结果类型: {type(result)}")
        except Exception as e:
            logger.error(f"SRT转换失败: {str(e)}", exc_info=True)

    def _handle_output_files(self):
        """处理生成的输出文件 - 确保JSON文件与音频文件同名"""
        # 获取输出目录
        output_dir = os.path.dirname(self.audio_path)

        # 查找所有可能的输出文件
        for file in os.listdir(output_dir):
            file_path = os.path.join(output_dir, file)

            # 跳过目录
            if os.path.isdir(file_path):
                continue

            # 确保只处理与当前音频文件相关的文件
            base_name = os.path.basename(self.base_name)
            if not file.startswith(base_name):
                continue

            try:
                # 处理JSON文件
                if file.endswith(".words.json") and self.output_format == "json":
                    if file_path != self.json_path:
                        # 确保目标目录存在
                        os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
                        # 如果目标文件已存在，删除它
                        if os.path.exists(self.json_path):
                            os.remove(self.json_path)
                        os.rename(file_path, self.json_path)
                        logger.info(f"重命名文件: {file} -> {os.path.basename(self.json_path)}")

                # 处理普通JSON文件
                elif file.endswith(".json") and self.output_format == "json":
                    if file_path != self.json_path:
                        # 确保目标目录存在
                        os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
                        # 如果目标文件已存在，删除它
                        if os.path.exists(self.json_path):
                            os.remove(self.json_path)
                        os.rename(file_path, self.json_path)
                        logger.info(f"重命名文件: {file} -> {os.path.basename(self.json_path)}")

                # 处理SRT文件
                elif file.endswith(".srt") and self.output_format == "srt":
                    if file_path != self.srt_path:
                        # 确保目标目录存在
                        os.makedirs(os.path.dirname(self.srt_path), exist_ok=True)
                        # 如果目标文件已存在，删除它
                        if os.path.exists(self.srt_path):
                            os.remove(self.srt_path)
                        os.rename(file_path, self.srt_path)
                        logger.info(f"重命名文件: {file} -> {os.path.basename(self.srt_path)}")
            except Exception as e:
                logger.error(f"文件重命名失败: {str(e)}", exc_info=True)

    def _get_optimized_threads(self):
        """根据CPU核心数优化线程设置"""
        cpu_count = os.cpu_count() or 4
        # 对于大型文件，使用更多线程但不超过CPU核心数
        return min(cpu_count, 8)  # 最多使用8个线程

    def _run_whisper(self, command, max_retries=3):
        """执行Whisper命令 - 增强错误处理、编码支持和重试机制"""
        for attempt in range(max_retries):
            try:
                logger.info(f'开始提取字幕... (尝试 {attempt + 1}/{max_retries})')
                logger.info(f"执行命令: {' '.join(command)}")

                # 设置UTF-8环境变量
                env = os.environ.copy()
                env['PYTHONUTF8'] = '1'
                env['PYTHONIOENCODING'] = 'utf-8'

                start_time = time.time()

                # 使用Popen以便实时输出日志
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    env=env,
                    bufsize=1,  # 行缓冲
                    universal_newlines=True
                )

                # 实时读取输出
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        logger.debug(output.strip())

                # 等待进程完成
                return_code = process.wait()

                # 记录命令输出
                logger.info(f"命令执行完成，状态码: {return_code}")

                # 记录错误输出
                stderr_output = process.stderr.read()
                if stderr_output:
                    logger.warning(f"命令错误输出:\n{stderr_output}")

                logger.info(f"字幕提取完成, 耗时: {time.time() - start_time:.1f}秒")

                # 处理可能的输出文件 - 确保JSON与音频文件同名
                self._handle_output_files()
                return return_code == 0
            except Exception as e:
                logger.error(f"未知错误: {str(e)}", exc_info=True)
                if attempt == max_retries - 1:
                    return False
                wait_time = (attempt + 1) * 10
                logger.info(f"等待{wait_time}秒后重试...")
                time.sleep(wait_time)
        return False

    def extract_with_timestamped(self, model="medium.en", lang="en",
                                 parallel_workers=None):
        """使用whisper-timestamped提取带时间戳的字幕 - 优化大型文件处理"""
        if not self._should_regenerate():
            logger.info("字幕文件已存在，跳过提取")
            return

        # 优化线程设置
        if parallel_workers is None:
            parallel_workers = self._get_optimized_threads()
            logger.info(f"自动设置并行线程数: {parallel_workers}")

        model_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "Model"
        )

        # 确保模型目录存在
        if not os.path.exists(model_dir):
            logger.warning(f"模型目录不存在: {model_dir}")
            model_dir = ""

        # 构建基本命令 - 仅使用支持参数
        command = [
            "whisper_timestamped",
            self.audio_path,
            "--model", model,
            "--device", "cuda" if torch.cuda.is_available() else "cpu",
            "--language", lang,
            "--output_dir", os.path.dirname(self.audio_path),
            "--output_format", self.output_format,
            "--vad", "True",
            "--accurate",
            "--fp16", "True" if torch.cuda.is_available() else "False",  # GPU加速
            "--threads", str(parallel_workers)  # CPU并行处理
        ]

        # 添加模型目录参数（如果存在）
        if model_dir and os.path.exists(model_dir):
            command.extend(["--model_dir", model_dir])

        # 添加重试机制
        if self._run_whisper(command, max_retries=3):
            # 如果是JSON格式，进行格式化和SRT转换
            if self.output_format == "json":
                if os.path.exists(self.json_path):
                    self._format_json(self.json_path)

                    # 读取JSON结果并转换为SRT
                    try:
                        with open(self.json_path, 'r', encoding='utf-8') as f:
                            result_data = json.load(f)
                        self._convert_to_srt(result_data, self.srt_path)
                    except Exception as e:
                        logger.error(f"JSON读取或转换失败: {str(e)}", exc_info=True)
                else:
                    logger.error(f"JSON文件未生成: {self.json_path}")
            elif self.output_format == "srt":
                if os.path.exists(self.srt_path):
                    logger.info(f"SRT文件已生成: {self.srt_path}")
                else:
                    logger.error(f"SRT文件未生成: {self.srt_path}")

    def extract_with_openai(self, model="medium.en", lang="en"):
        """使用OpenAI的whisper库提取字幕 - 增强错误处理"""
        if not self._should_regenerate():
            logger.info("字幕文件已存在，跳过提取")
            return

        try:
            import whisper
            logger.info('加载Whisper模型...')
            model = whisper.load_model(model)
            logger.info('开始识别音频...')
            result = model.transcribe(
                self.audio_path,
                language=lang,
                word_timestamps=True,
                vad_filter=True
            )

            # 直接保存JSON结果 - 确保与音频文件同名
            if self.output_format == "json":
                try:
                    with open(self.json_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False)
                    logger.info(f"JSON文件已保存: {self.json_path}")
                    self._format_json(self.json_path)
                except Exception as e:
                    logger.error(f"JSON保存失败: {str(e)}", exc_info=True)

            # 生成SRT文件 - 确保与音频文件同名
            try:
                self._convert_to_srt(result, self.srt_path)
                logger.info(f"SRT文件已生成: {self.srt_path}")
            except Exception as e:
                logger.error(f"SRT生成失败: {str(e)}", exc_info=True)

            logger.info("字幕提取完成")
        except ImportError:
            logger.error("错误: 请先安装openai-whisper: pip install openai-whisper")
        except Exception as e:
            logger.error(f"识别失败: {str(e)}", exc_info=True)

    def _get_device(self, preferred_device: Optional[str] = None) -> str:
        """自动检测可用的计算设备"""
        if preferred_device and preferred_device != "auto":
            return preferred_device
        try:
            import torch
            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0)
                logger.info(f"检测到 GPU: {device_name}")
                return "cuda"
            else:
                logger.info("未检测到 GPU，使用 CPU")
                return "cpu"
        except Exception:
            logger.warning("设备检测失败，默认使用 CPU")
            return "cpu"

    def _get_compute_type(self, device: str, preferred_type: Optional[str] = None) -> str:
        """根据设备自动选择计算精度"""
        if preferred_type and preferred_type != "auto":
            return preferred_type
        if device == "cuda":
            return "float16"
        return "int8"

    def _get_model_paths(self) -> dict:
        """获取项目本地模型缓存路径（全部在项目目录内，不依赖系统缓存）"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return {
            # whisper 模型使用 flat 目录（local_dir），不走 HF cache 结构
            "whisper": os.path.join(project_root, "models", "whisper"),
            # 对齐/其他 HF 模型使用 HF 缓存结构，通过 HF_HOME 指向项目内
            "alignment": os.path.join(project_root, "models", "alignment"),
        }

    def extract_with_whisperx(
        self,
        video_path: Optional[str] = None,
        model: str = "small",
        language: Optional[str] = None,
        device: str = "auto",
        compute_type: str = "auto",
        batch_size: int = 4,
        use_vad: bool = True,
        use_separation: bool = True,
        vocal_path_override: Optional[str] = None,
        vad_segments: Optional[List[Tuple[float, float]]] = None,
        vad_threshold: Optional[float] = None,
        output_json: Optional[str] = None,
        output_srt: Optional[str] = None,
        keep_temp: bool = False,
    ):
        """
        使用 whisperX 进行转录 + wav2vec2 强制对齐
        
        流程: 人声分离 → VAD 分段 → whisperX 转录 → wav2vec2 对齐 → 时间轴还原 → 输出
        
        Args:
            video_path: 原始视频路径（用于人声分离）
            model: whisper 模型 (tiny/base/small/medium)
            language: 语言代码 (en/ja/zh 等)，None 则自动检测
            device: 计算设备 (auto/cpu/cuda)
            compute_type: 计算精度 (auto/int8/float16/float32)
            batch_size: 转录批次大小
            use_vad: 是否使用 VAD 分段（推荐长视频启用）
            use_separation: 是否进行人声分离
            vad_segments: 外部提供的 VAD 段 [(start, end), ...]
            output_json: JSON 输出路径（默认与音频同名）
            output_srt: SRT 输出路径（默认与音频同名）
            keep_temp: 是否保留临时文件
        """
        import gc
        import tempfile
        import subprocess
        from typing import List, Tuple, Optional

        # ========== HuggingFace 环境配置 ==========
        # 1. 镜像：适配中国大陆网络环境
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            logger.info("设置 HF_ENDPOINT=https://hf-mirror.com (适配中国大陆网络)")
        if not os.environ.get("HF_HUB_DISABLE_SYMLINKS_WARNING"):
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        # 2. 模型缓存定位到项目目录，不依赖系统缓存
        #    迁移项目时所有模型随项目一起移动
        models_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.environ.get("HF_HOME"):
            hf_home = os.path.join(models_root, "models", "hf_cache")
            os.environ["HF_HOME"] = hf_home
            os.makedirs(hf_home, exist_ok=True)
            logger.info(f"设置 HF_HOME={hf_home} (模型缓存定位到项目内部)")
        # 同样约束 transformers 缓存
        if not os.environ.get("TRANSFORMERS_CACHE"):
            os.environ["TRANSFORMERS_CACHE"] = os.environ["HF_HOME"]
        # Demucs / Silero VAD 等 torch hub 模型也放到项目本地
        if not os.environ.get("TORCH_HOME"):
            os.environ["TORCH_HOME"] = os.path.join(models_root, "models")

        # 自动检测设备和计算精度
        actual_device = self._get_device(device)
        actual_compute = self._get_compute_type(actual_device, compute_type)
        logger.info(f"使用设备: {actual_device}, 计算精度: {actual_compute}")

        # 设置输出路径
        out_json = output_json or self.json_path
        out_srt = output_srt or self.srt_path

        # 检查是否需要重新生成（优先检查自定义输出路径）
        primary_output = out_json if self.output_format == "json" else out_srt
        if not self._should_regenerate(check_path=primary_output):
            logger.info("字幕文件已存在，跳过提取")
            return

        # 0. 确保 ffmpeg 在 PATH（whisperX 内部需要）
        try:
            import imageio_ffmpeg
            ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
            if ffmpeg_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        except ImportError:
            pass

        # 模型缓存路径
        model_paths = self._get_model_paths()
        os.makedirs(model_paths["whisper"], exist_ok=True)
        os.makedirs(model_paths["alignment"], exist_ok=True)

        # ── 视频时长缺陷检测（通用诊断，无论是否分离都执行）──
        # 检测 C2 缺陷（CD > ADD），日志记录诊断结果
        # 下游 VAD_Segmenter 读取音频时会获得已对齐的时长
        # 注意：不在此处修复，修复在 VocalSeparator._prepare_audio() 或手动调用 ensure_audio_duration()
        if video_path and os.path.exists(video_path):
            try:
                from MediaValidator import MediaValidator
                _validator = MediaValidator()
                _diag = _validator.diagnose(video_path)
                if _diag.status == "defect":
                    logger.warning(
                        f"视频缺陷检测: {_diag.defect_type} - {_diag.defect_name}, "
                        f"详情: {_diag.details}"
                    )
                    logger.info("音频提取时将自动 aresample 修正 (ensure_audio_duration)")
                else:
                    logger.info(f"视频无时长缺陷: {_diag.details}")
            except ImportError:
                logger.warning("MediaValidator 不可用, 跳过时长检测")
            except Exception as e:
                logger.warning(f"视频检测失败 (不影响流程): {e}")

        # 1. 人声分离（可选）
        # ── 双轨策略 ──
        # vocal_path: Demucs 分离后的人声（用于 VAD 分段 + 转录，提高识别准确率）
        # self.audio_path: 原始音频（用于 wav2vec2 对齐，保证时间轴正确）
        # 允许外部传入 vocal_path_override，跳过 Demucs 直接使用已有分离结果
        vocal_path = self.audio_path
        if vocal_path_override and os.path.exists(vocal_path_override):
            vocal_path = vocal_path_override
            logger.info(f"使用外部指定人声: {vocal_path_override}")
        elif use_separation and video_path and os.path.exists(video_path):
            try:
                from VocalSeparator import VocalSeparator
                sep = VocalSeparator(video_path, verbose=True)
                vocal_path, _ = sep.separate(force=False)
                logger.info(f"使用分离后人声: {vocal_path}")
            except Exception as e:
                logger.warning(f"人声分离失败，使用原始音频: {e}")
                vocal_path = self.audio_path

        # 2. VAD 分段（在人声上做，语音检测更准）
        segments_to_process = []
        if vad_segments is not None:
            segments_to_process = vad_segments
            logger.info(f"使用外部提供的 VAD 段: {len(segments_to_process)} 段")
        elif use_vad:
            try:
                from VAD_Segmenter import VAD_Segmenter
                if vad_threshold is not None:
                    vad = VAD_Segmenter(vocal_path, threshold=vad_threshold)
                    logger.info(f"VAD 阈值: {vad_threshold}")
                else:
                    vad = VAD_Segmenter(vocal_path)
                segments_to_process = vad.get_segments(force=False)
                logger.info(f"VAD 检测到 {len(segments_to_process)} 个语音段")
            except Exception as e:
                logger.warning(f"VAD 失败，使用整段音频: {e}")
                segments_to_process = []
        
        if not segments_to_process:
            # 无 VAD 段，使用整段音频
            import soundfile as sf
            info = sf.info(vocal_path)
            segments_to_process = [(0.0, info.duration)]
            logger.info(f"无 VAD 分段，使用整段音频 ({info.duration:.0f}s)")

        # 3. 加载 whisperX 模型（只加载一次）
        logger.info(f"加载 whisperX 模型: {model} (device={actual_device}, compute={actual_compute})")
        t0 = time.time()
        import whisperx
        try:
            whisper_model = whisperx.load_model(
                model, device=actual_device, compute_type=actual_compute,
                download_root=model_paths["whisper"],
                asr_options={"word_timestamps": False},
            )
            logger.info(f"  模型加载耗时: {time.time()-t0:.1f}s")
        except Exception as e:
            logger.error(f"whisperX 模型加载失败: {e}")
            raise RuntimeError(f"无法加载 whisperX 模型 '{model}'，请检查网络连接或手动下载到 {model_paths['whisper']}") from e

        # 4. 检测语言（如果未指定）
        if language is None:
            logger.info("自动检测语言...")
            try:
                # 用第一段前30s检测
                detect_dur = min(30.0, segments_to_process[0][1] - segments_to_process[0][0])
                detect_audio = self._load_audio_segment(vocal_path, segments_to_process[0][0], 
                                                          segments_to_process[0][0] + detect_dur)
                detect_result = whisper_model.transcribe(detect_audio, batch_size=batch_size)
                language = detect_result.get("language", "en")
                logger.info(f"  检测到语言: {language}")
                del detect_audio
                gc.collect()
            except Exception as e:
                logger.warning(f"语言检测失败，默认使用英语: {e}")
                language = "en"

        # 5. 加载对齐模型（只加载一次）
        logger.info(f"加载 wav2vec2 对齐模型 (lang={language})")
        t0 = time.time()
        try:
            align_model, align_metadata = whisperx.load_align_model(
                language_code=language, device=actual_device,
                model_dir=model_paths["alignment"],
            )
            logger.info(f"  对齐模型加载耗时: {time.time()-t0:.1f}s")
        except Exception as e:
            logger.error(f"对齐模型加载失败: {e}")
            raise RuntimeError(f"无法加载 wav2vec2 对齐模型 (lang={language})，请检查网络连接或手动下载到 {model_paths['alignment']}") from e

        # 6. 逐段处理
        # ── 双轨策略 ──
        # 转录和 VAD：用 Demucs 分离后的人声（干净，识别准确率更高）
        # 对齐：用原始音频（两者采样级一致，选哪个都一样）
        logger.info("转录使用人声分离音频，对齐使用原始音频")
        
        all_segments = []
        total_segments = len(segments_to_process)
        
        for idx, (seg_start, seg_end) in enumerate(segments_to_process, 1):
            seg_duration = seg_end - seg_start
            logger.info(f"[{idx}/{total_segments}] 处理段 {seg_start:.1f}s-{seg_end:.1f}s ({seg_duration:.1f}s)")
            
            t0 = time.time()
            
            # 加载音频段
            # 转录用分离后人声（干净 → 高识别率）
            audio_vocal = self._load_audio_segment(vocal_path, seg_start, seg_end)
            
            # 转录（在人声上做，背景音不影响）
            result = whisper_model.transcribe(audio_vocal, batch_size=batch_size, language=language)
            
            # 对齐
            if result.get("segments"):
                try:
                    # 对齐用原始音频（时间轴与视频完全一致）
                    audio_align = self._load_audio_segment(self.audio_path, seg_start, seg_end)
                    result_aligned = whisperx.align(
                        result["segments"], align_model, align_metadata,
                        audio_align, device=actual_device, return_char_alignments=False,
                    )
                    del audio_align
                except torch.cuda.OutOfMemoryError as e:
                    logger.error(f"GPU 显存不足，对齐失败: {e}")
                    # fallback: 尝试 CPU 对齐
                    try:
                        logger.warning("尝试在 CPU 上重试对齐...")
                        if 'audio_align' not in locals():
                            audio_align = self._load_audio_segment(self.audio_path, seg_start, seg_end)
                        result_aligned = whisperx.align(
                            result["segments"], align_model, align_metadata,
                            audio_align, device="cpu", return_char_alignments=False,
                        )
                        del audio_align
                    except Exception as cpu_e:
                        logger.warning(f"CPU 对齐也失败，使用原始时间戳: {cpu_e}")
                        result_aligned = {"segments": result["segments"]}
                except Exception as e:
                    logger.warning(f"对齐失败，使用原始时间戳: {e}")
                    result_aligned = {"segments": result["segments"]}
                
                # 时间轴偏移：还原到原始视频时间
                for seg in result_aligned.get("segments", []):
                    seg["start"] += seg_start
                    seg["end"] += seg_start
                    if "words" in seg:
                        for w in seg["words"]:
                            w["start"] += seg_start
                            w["end"] += seg_start
                
                all_segments.extend(result_aligned.get("segments", []))
                logger.info(f"  转录+对齐: {len(result_aligned.get('segments', []))} 段, "
                          f"耗时 {time.time()-t0:.1f}s")
            else:
                logger.info(f"  该段无语音")
            
            # 清理内存
            del audio_vocal
            gc.collect()

        # 7. 清理模型
        del whisper_model
        del align_model
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

        # 8. 排序并去重
        all_segments.sort(key=lambda x: x.get("start", 0))
        
        # 去重：重叠区域的重复词（由于 VAD 段 1s 重叠可能导致）
        cleaned_segments = self._deduplicate_segments(all_segments)
        
        # 8.5 时间轴修正：VFR 视频的音频解码时长可能不等于容器时长，
        # 将音频时间戳映射回视频时间轴
        if video_path and os.path.exists(video_path):
            video_dur = self._get_media_duration(video_path)
            audio_dur = self._get_media_duration(vocal_path)
            if video_dur and audio_dur and abs(video_dur - audio_dur) > 0.5:
                ratio = video_dur / audio_dur
                logger.warning(
                    f"音频解码时长({audio_dur:.2f}s) 与视频容器时长({video_dur:.2f}s) "
                    f"相差 {abs(video_dur - audio_dur):.2f}s，"
                    f"按比例 {ratio:.6f} 修正时间戳"
                )
                for seg in cleaned_segments:
                    seg["start"] *= ratio
                    seg["end"] *= ratio
                    if "words" in seg:
                        for w in seg["words"]:
                            w["start"] *= ratio
                            w["end"] *= ratio
        
        # 9. 构建最终结果
        final_result = {
            "segments": cleaned_segments,
            "language": language,
            "text": " ".join(seg.get("text", "").strip() for seg in cleaned_segments),
        }
        
        # 10. 保存 JSON（SRT 统一由 Json_Convert_Srt 基于词级时间戳重分组生成）
        logger.info(f"保存 JSON: {out_json}")
        os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"whisperX 提取完成: {len(cleaned_segments)} 段字幕")
        return final_result

    def _get_media_duration(self, path: str) -> Optional[float]:
        """用 ffmpeg 获取媒体文件容器时长（秒）"""
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            r = subprocess.run([ffmpeg_exe, "-i", path],
                               capture_output=True, text=True)
            for line in r.stderr.split("\n"):
                if "Duration:" in line:
                    d = line.split(",")[0].replace("Duration:", "").strip()
                    h, m, s = d.split(":")
                    return int(h) * 3600 + int(m) * 60 + float(s)
        except Exception as e:
            logger.warning(f"获取时长失败 {path}: {e}")
        return None

    @staticmethod
    def _load_audio_segment(wav_path: str, start_s: float, end_s: float, target_sr: int = 16000):
        """加载音频片段并转为 whisperX 可用的 numpy 数组"""
        import torchaudio
        import numpy as np
        
        info = torchaudio.info(wav_path)
        sr = info.sample_rate
        start_sample = int(start_s * sr)
        num_samples = int((end_s - start_s) * sr)
        
        wav, sr_loaded = torchaudio.load(
            wav_path, frame_offset=start_sample, num_frames=num_samples,
        )
        
        # 重采样
        if sr_loaded != target_sr:
            wav = torchaudio.functional.resample(wav, sr_loaded, target_sr)
        
        # 单声道
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0)
        else:
            wav = wav.squeeze(0)
        
        return wav.numpy().astype(np.float32)

    @staticmethod
    def _deduplicate_segments(segments):
        """去重：移除重叠区域的重复词"""
        if not segments:
            return segments
        
        seen_words = set()
        cleaned = []
        
        for seg in segments:
            words = seg.get("words", [])
            unique_words = []
            for w in words:
                # 用 (start, end, word) 作为唯一键
                key = (round(w.get("start", 0), 3), round(w.get("end", 0), 3), w.get("word", ""))
                if key not in seen_words:
                    seen_words.add(key)
                    unique_words.append(w)
            
            if unique_words:
                new_seg = seg.copy()
                new_seg["words"] = unique_words
                new_seg["start"] = unique_words[0]["start"]
                new_seg["end"] = unique_words[-1]["end"]
                cleaned.append(new_seg)
        
        return cleaned

    def _convert_whisperx_to_srt(self, segments, srt_path):
        """将 whisperX 对齐结果转为 SRT 文件"""
        os.makedirs(os.path.dirname(srt_path) or ".", exist_ok=True)
        
        def fmt_time(s):
            h, r = divmod(int(s), 3600)
            m, r = divmod(r, 60)
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")
        
        lines = []
        for i, seg in enumerate(segments, 1):
            words = seg.get("words", [])
            if words:
                start = words[0]["start"]
                end = words[-1]["end"]
            else:
                start, end = seg.get("start", 0), seg.get("end", 0)
            
            text = seg.get("text", "").strip()
            lines.append(f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n")
        
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        logger.info(f"SRT 已保存: {srt_path} ({len(segments)} 段)")

    # ======== 大型文件处理优化 ========
    def split_large_audio(self, max_duration=1800, min_silence_len=500, silence_thresh=-40):
        """改进版音频分割 - 避免切割单词，保持均匀分段"""
        try:
            from pydub import AudioSegment
            from pydub.silence import detect_nonsilent
        except ImportError:
            logger.error("请先安装pydub: pip install pydub")
            return [self.audio_path]

        try:
            audio = AudioSegment.from_file(self.audio_path)
            total_duration = len(audio) / 1000  # 毫秒转秒
            segments = []

            if total_duration <= max_duration:
                return [self.audio_path]

            # 计算分段数量和理想切割点
            num_segments = math.ceil(total_duration / max_duration)
            ideal_cut_points = [i * (total_duration / num_segments) * 1000 for i in range(1, num_segments)]

            # 获取语音活动区域
            speech_ranges = detect_nonsilent(
                audio,
                min_silence_len=min_silence_len,
                silence_thresh=silence_thresh
            )

            # 转换静音检测结果为静音区间
            silence_ranges = []
            prev_end = 0
            for start, end in speech_ranges:
                if start > prev_end:
                    silence_ranges.append((prev_end, start))
                prev_end = end
            if prev_end < len(audio):
                silence_ranges.append((prev_end, len(audio)))

            # 寻找最佳切割点（在静音区域内）
            actual_cut_points = []
            for point in ideal_cut_points:
                best_cut = point
                best_score = float('inf')  # 初始化为最大值

                # 在理想切割点附近寻找最佳静音位置
                search_start = max(0, point - 5000)  # 向前搜索5秒
                search_end = min(len(audio), point + 5000)  # 向后搜索5秒

                for silence_start, silence_end in silence_ranges:
                    # 确保静音区间在搜索范围内
                    if silence_end < search_start or silence_start > search_end:
                        continue

                    # 计算静音区间中点的分数（距离理想点的偏移）
                    silence_mid = (silence_start + silence_end) / 2
                    distance = abs(silence_mid - point)

                    # 优先选择长静音段
                    silence_length = silence_end - silence_start
                    score = distance / (silence_length + 1)  # 长度越大分数越小

                    if score < best_score:
                        best_score = score
                        best_cut = silence_mid

                actual_cut_points.append(int(best_cut))

            # 分割音频
            output_dir = os.path.join(os.path.dirname(self.audio_path), "chunks")
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.basename(self.audio_path).rsplit('.', 1)[0]

            start_point = 0
            for i, cut_point in enumerate(actual_cut_points):
                # 确保切割点在合理范围内
                cut_point = max(start_point + 1000, min(cut_point, len(audio) - 1000))

                segment = audio[start_point:cut_point]
                segment_path = os.path.join(output_dir, f"{base_name}_part{i + 1}.wav")
                segment.export(segment_path, format="wav")
                segments.append(segment_path)
                logger.info(f"创建音频分段: {segment_path} ({len(segment) / 1000:.1f}秒)")
                start_point = cut_point

            # 添加最后一段
            last_segment = audio[start_point:]
            last_segment_path = os.path.join(output_dir, f"{base_name}_part{len(actual_cut_points) + 1}.wav")
            last_segment.export(last_segment_path, format="wav")
            segments.append(last_segment_path)
            logger.info(f"创建音频分段: {last_segment_path} ({len(last_segment) / 1000:.1f}秒)")

            return segments
        except Exception as e:
            logger.error(f"音频分割失败: {str(e)}", exc_info=True)
            return [self.audio_path]

    def process_large_audio(self, model="medium.en", lang="ja", max_chunk_duration=1800):
        """处理大型音频文件的优化方法"""
        # 检查音频时长
        if self.audio_duration <= max_chunk_duration:
            logger.info(f"音频时长适中({self.audio_duration:.1f}秒)，直接处理")
            return self.extract_with_timestamped(model, lang)

        # 同时记录文件大小作为参考
        file_size = os.path.getsize(self.audio_path) / (1024 * 1024)  # MB
        logger.info(f"检测到大型音频文件: 时长={self.audio_duration:.1f}秒, 大小={file_size:.1f}MB")
        logger.info("进行分割处理...")

        # 分割音频文件
        segments = self.split_large_audio(max_duration=max_chunk_duration)
        results = []
        segment_results = []

        for segment_path in segments:
            logger.info(f"处理分段: {segment_path}")
            segment_base = os.path.splitext(segment_path)[0]
            segment_json = f"{segment_base}.json"

            # 检查分段结果是否已存在
            if os.path.exists(segment_json) and os.path.getsize(segment_json) > 0:
                logger.info(f"使用现有分段结果: {segment_json}")
                try:
                    with open(segment_json, 'r', encoding='utf-8') as f:
                        result_data = json.load(f)
                    results.append(result_data)
                    continue
                except:
                    logger.warning(f"分段结果加载失败，将重新处理: {segment_json}")

            # 处理分段
            segment_extractor = SRT_Extractor(segment_path, "json")
            segment_extractor.extract_with_timestamped(model, lang)

            # 收集结果
            if os.path.exists(segment_json):
                try:
                    with open(segment_json, 'r', encoding='utf-8') as f:
                        result_data = json.load(f)
                    results.append(result_data)
                    segment_results.append(segment_json)
                    logger.info(f"成功加载分段结果: {segment_json}")
                except Exception as e:
                    logger.error(f"加载分段结果失败: {str(e)}")
            else:
                logger.error(f"分段结果文件不存在: {segment_json}")

        # 合并结果
        if results:
            logger.info("合并所有分段结果...")
            merged_result = self.merge_results(results)

            # 保存最终结果 - 确保与原始音频同名
            if self.output_format == "json":
                try:
                    with open(self.json_path, 'w', encoding='utf-8') as f:
                        json.dump(merged_result, f, ensure_ascii=False)
                    self._format_json(self.json_path)
                    logger.info(f"最终JSON结果已保存: {self.json_path}")
                except Exception as e:
                    logger.error(f"保存最终JSON失败: {str(e)}")

            # 生成SRT - 确保与原始音频同名
            try:
                self._convert_to_srt(merged_result, self.srt_path)
                logger.info(f"最终SRT文件已生成: {self.srt_path}")
            except Exception as e:
                logger.error(f"生成最终SRT失败: {str(e)}")
        else:
            logger.error("没有可合并的结果")
            return False

        # 清理临时文件
        self._cleanup_temp_files(segments, segment_results)
        return True

    def _cleanup_temp_files(self, audio_segments, json_files):
        """清理临时文件"""
        for segment_path in audio_segments:
            try:
                if segment_path != self.audio_path:  # 不删除原始文件
                    if os.path.exists(segment_path):
                        os.remove(segment_path)
                        logger.info(f"删除临时音频文件: {segment_path}")
            except Exception as e:
                logger.warning(f"删除临时音频文件失败: {str(e)}")

        for json_path in json_files:
            try:
                if os.path.exists(json_path):
                    os.remove(json_path)
                    logger.info(f"删除临时JSON文件: {json_path}")
            except Exception as e:
                logger.warning(f"删除临时JSON文件失败: {str(e)}")

    def merge_results(self, results):
        """合并多个结果文件 - 修复时间戳累加问题"""
        if not results:
            return {"text": "", "segments": []}

        merged = {
            "text": "",
            "segments": [],
            "language": results[0].get("language", "en"),
            "model": results[0].get("model", "medium")
        }

        current_offset = 0.0  # 当前时间偏移量
        segment_counter = 1  # 片段计数器

        for i, result in enumerate(results):
            if "segments" not in result or not result["segments"]:
                logger.warning(f"结果 {i + 1}/{len(results)} 缺少有效的 segments 数据")
                continue

            # 计算当前分段的持续时间
            segment_duration = result["segments"][-1]["end"] if result["segments"] else 0
            logger.info(
                f"处理分段 {i + 1}/{len(results)}: {len(result['segments'])} 个片段, 时长: {segment_duration:.2f}秒")

            # 处理当前分段的所有片段
            for segment in result["segments"]:
                # 创建新的片段副本
                new_segment = segment.copy()

                # 应用时间偏移
                new_segment["start"] += current_offset
                new_segment["end"] += current_offset

                # 调整单词时间戳
                if "words" in new_segment:
                    for word in new_segment["words"]:
                        word["start"] += current_offset
                        word["end"] += current_offset

                # 添加到合并结果
                merged["segments"].append(new_segment)

            # 更新文本
            if "text" in result:
                merged["text"] += result["text"] + " "

            # 更新偏移量为当前分段的持续时间
            current_offset += segment_duration

        # 按开始时间排序确保正确顺序
        merged["segments"].sort(key=lambda x: x["start"])

        # 重新编号所有片段
        for i, seg in enumerate(merged["segments"]):
            seg["id"] = i + 1

        # 计算总时长
        total_duration = merged["segments"][-1]["end"] if merged["segments"] else 0
        logger.info(f"合并完成: 总片段数: {len(merged['segments'])}, 总时长: {total_duration:.2f}秒")

        return merged


def merge_json_files(audio_path, output_dir=None):
    """
    合并由分割生成的多个JSON文件
    :param audio_path: 原始音频文件路径（用于确定基础文件名）
    :param output_dir: 输出目录（默认为音频文件所在目录）
    """
    # 设置输出目录
    if output_dir is None:
        output_dir = os.path.dirname(audio_path)

    # 获取基础文件名
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    chunks_dir = os.path.join(output_dir, "chunks")

    # 收集所有分段的JSON文件
    json_files = []
    i = 1
    while True:
        json_path = os.path.join(chunks_dir, f"{base_name}_part{i}.json")
        if not os.path.exists(json_path):
            break
        json_files.append(json_path)
        i += 1

    if not json_files:
        print(f"未找到分段JSON文件: {chunks_dir}/{base_name}_part*.json")
        return

    print(f"找到 {len(json_files)} 个分段文件")

    # 读取所有JSON内容
    results = []
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            results.append(data)
            print(f"已加载: {os.path.basename(json_file)}")
        except Exception as e:
            print(f"加载 {json_file} 失败: {str(e)}")

    if not results:
        print("无有效JSON数据可合并")
        return

    # 初始化提取器并合并结果
    extractor = SRT_Extractor(audio_path, output_format="json")
    merged_result = extractor.merge_results(results)

    # 保存合并后的JSON文件
    merged_json_path = os.path.join(output_dir, f"{base_name}.json")
    with open(merged_json_path, 'w', encoding='utf-8') as f:
        json.dump(merged_result, f, ensure_ascii=False, indent=4)

    print(f"合并后的JSON已保存至: {merged_json_path}")

    # 可选：生成SRT文件
    srt_path = os.path.join(output_dir, f"{base_name}.srt")
    extractor._convert_to_srt(merged_result, srt_path)
    print(f"已生成SRT文件: {srt_path}")


# 使用示例
if __name__ == '__main__':
    # 音频文件路径
    video_Vocal_path = r"D:\Github\20240708Move_video_2\source_file\ADN-703_(Vocals).wav"

    # 检查音频文件是否存在
    if not os.path.exists(video_Vocal_path):
        logger.error(f"音频文件不存在: {video_Vocal_path}")
        sys.exit(1)

    logger.info(f"开始处理音频文件: {video_Vocal_path}")
    extra_srt = SRT_Extractor(video_Vocal_path, output_format="json")

    # 获取音频时长作为参考
    duration = extra_srt.audio_duration
    file_size = os.path.getsize(video_Vocal_path) / (1024 * 1024)  # MB
    logger.info(f"音频信息: 时长={duration:.1f}秒, 大小={file_size:.1f}MB")

    # 使用时长判断处理方式
    if duration > 1800:  # 超过30分钟（1800秒）视为大型文件
        logger.info(f"检测到大型音频文件（时长超过30分钟），使用分段处理")
        extra_srt.process_large_audio(
            model="medium",
            lang="ja",
            max_chunk_duration=5*60  # 20分钟分段
        )
    else:
        logger.info(f"音频时长适中，直接处理")
        # 使用标准方法
        extra_srt.extract_with_timestamped(
            model="medium",
            lang="ja"
        )