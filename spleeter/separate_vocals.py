import os
import subprocess
import sys
import tempfile
import shutil
import logging
import json
from spleeter.separator import Separator

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('AudioSeparator')


class AudioSeparator:
    def __init__(self, spleeter_model_config, max_segment_duration=540):
        """
        初始化音频分离器

        :param spleeter_model_config: Spleeter模型配置文件路径
        :param max_segment_duration: 最大片段时长（秒），默认540秒(9分钟)
        """
        self.spleeter_model_config = spleeter_model_config
        self.max_segment_duration = max_segment_duration

        # 加载原始配置文件
        with open(spleeter_model_config, 'r') as f:
            self.original_config = json.load(f)

        # 创建修改后的临时配置
        self.modified_config = self.original_config.copy()
        self.modified_config['sample_rate'] = 48000  # 强制48kHz输出
        self.modified_config['channel_count'] = 2  # 强制立体声输出

        # 创建临时配置文件
        self.temp_config_path = self.create_temp_config()

        # 使用临时配置文件初始化分离器
        self.separator = Separator(self.temp_config_path)
        logger.info("音频分离器初始化完成（采样率: 48kHz, 声道: 立体声）")

    def __del__(self):
        """析构函数，清理临时配置文件"""
        if hasattr(self, 'temp_config_path') and self.temp_config_path != self.spleeter_model_config:
            try:
                os.unlink(self.temp_config_path)
                logger.info(f"已清理临时配置文件: {self.temp_config_path}")
            except Exception as e:
                logger.error(f"清理临时配置文件失败: {str(e)}")

    def create_temp_config(self):
        """创建临时配置文件"""
        try:
            # 创建临时文件
            temp_fd, temp_path = tempfile.mkstemp(suffix='.json')
            with os.fdopen(temp_fd, 'w') as temp_file:
                json.dump(self.modified_config, temp_file)
            logger.info(f"创建临时配置文件: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"创建临时配置文件失败: {str(e)}")
            # 出错时回退使用原始配置
            return self.spleeter_model_config

    def extract_audio(self, video_path, temp_dir):
        """
        从视频中提取音频到临时文件 (自动检测并修正时长偏差)

        :param video_path: 视频文件路径
        :param temp_dir: 临时文件目录
        :return: 临时音频文件路径
        """
        try:
            temp_audio_path = os.path.join(temp_dir, f"temp_audio_{os.path.basename(video_path)}.wav")
            logger.info(f"提取音频: {video_path} -> {temp_audio_path}")

            # 使用共享工具 ensure_audio_duration (自动 aresample 修正)
            # 避免直接 ffmpeg，统一走 MediaValidator 的修正逻辑
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SRT"))
            from MediaValidator import ensure_audio_duration
            result = ensure_audio_duration(video_path, temp_audio_path, sr=48000, ch=2)

            if not os.path.isfile(result):
                raise RuntimeError(f"提取音频失败: {result}")

            logger.info(f"成功提取音频: {result}")
            return temp_audio_path
        except Exception as e:
            logger.error(f"提取音频失败: {str(e)}")
            raise

    def split_audio(self, audio_path, temp_dir):
        """
        将长音频分割成小片段

        :param audio_path: 音频文件路径
        :param temp_dir: 临时文件目录
        :return: 临时目录路径，包含所有分割后的音频片段
        """
        try:
            segment_dir = os.path.join(temp_dir, "segments")
            os.makedirs(segment_dir, exist_ok=True)
            output_pattern = os.path.join(segment_dir, "segment_%03d.wav")
            logger.info(f"分割音频: {audio_path} -> {segment_dir}")

            # 修复并优化FFmpeg分割参数
            cmd = [
                "ffmpeg",
                "-i", audio_path,
                "-f", "segment",
                "-segment_time", str(self.max_segment_duration),
                "-c:a", "pcm_s16le",
                "-ac", "2",
                "-ar", "48000",
                "-fflags", "+genpts",
                # 移除有问题的参数
                "-avoid_negative_ts", "make_zero",   # 移除
                "-reset_timestamps", "1",            # 移除
                # "-segment_time_delta", "0.1",  # 添加：允许时间误差
                "-max_muxing_queue_size", "9999",
                output_pattern
            ]

            logger.debug(f"分割命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"分割音频失败: {result.stderr}")
                raise RuntimeError(f"FFmpeg错误: {result.stderr}")

            # 获取实际生成的片段数量
            segment_files = [f for f in os.listdir(segment_dir) if f.endswith(".wav")]
            logger.info(f"成功分割音频为 {len(segment_files)} 个片段")
            return segment_dir
        except Exception as e:
            logger.error(f"分割音频失败: {str(e)}")
            raise

    def separate_segment(self, segment_path, output_dir):
        """
        分离单个音频片段的人声和伴奏

        :param segment_path: 音频片段路径
        :param output_dir: 输出目录
        :return: 包含人声和伴奏路径的元组 (vocals_path, accompaniment_path)
        """
        try:
            logger.info(f"分离音频片段: {segment_path}")

            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)

            # 分离音频
            self.separator.separate_to_file(
                segment_path,
                output_dir,
                filename_format="{instrument}.wav",  # 使用固定扩展名
                duration=self.max_segment_duration
            )

            vocals_path = os.path.join(output_dir, "vocals.wav")
            accompaniment_path = os.path.join(output_dir, "accompaniment.wav")

            # 检查文件是否存在
            if not os.path.exists(vocals_path) or not os.path.exists(accompaniment_path):
                raise RuntimeError(f"分离失败: {segment_path} - 输出文件未找到")

            return vocals_path, accompaniment_path
        except Exception as e:
            logger.error(f"分离音频片段失败: {str(e)}")
            raise

    def concatenate_audio(self, audio_files, output_path):
        """
        合并多个音频文件

        :param audio_files: 音频文件路径列表
        :param output_path: 合并后的输出路径
        """
        list_path = None
        try:
            # 创建临时文件列表
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as list_file:
                list_path = list_file.name
                for file in audio_files:
                    # 使用绝对路径并确保路径格式正确
                    abs_path = os.path.abspath(file).replace('\\', '/')
                    list_file.write(f"file '{abs_path}'\n")

            logger.info(f"合并 {len(audio_files)} 个音频文件到 {output_path}")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # 优化后的FFmpeg合并参数
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", list_path,
                "-c:a", "pcm_s16le",
                # 移除问题参数
                # "-fflags", "+genpts",         # 移除
                # "-max_muxing_queue_size", "9999",  # 移除
                '-async', '1',                # 移除
                "-loglevel", "warning",
                output_path
            ]

            # 捕获FFmpeg输出以便调试
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"合并音频失败: {result.stderr}")
                raise RuntimeError(f"FFmpeg错误: {result.stderr}")

            logger.info(f"成功创建: {output_path}")
            return True
        except Exception as e:
            logger.error(f"合并音频失败: {str(e)}")
            return False
        finally:
            if list_path and os.path.exists(list_path):
                try:
                    os.unlink(list_path)
                except Exception:
                    pass

    def separate_audio(self, audio_path, output_vocals, output_accompaniment, temp_dir):
        """
        分离长音频的人声和伴奏

        :param audio_path: 输入音频文件路径
        :param output_vocals: 输出人声文件路径
        :param output_accompaniment: 输出伴奏文件路径
        :param temp_dir: 临时文件目录
        """
        segments_dir = None
        separation_dir = None

        try:
            # 1. 分割音频
            segments_dir = self.split_audio(audio_path, temp_dir)
            segment_files = sorted([
                os.path.join(segments_dir, f)
                for f in os.listdir(segments_dir)
                if f.endswith(".wav")
            ])
            # 获取总时长
            cmd = ["ffprobe", "-i", audio_path, "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"]
            total_duration = float(subprocess.check_output(cmd).decode().strip())
            logger.info(f"原始音频总时长: {total_duration:.2f}秒")

            logger.info(f"找到 {len(segment_files)} 个音频片段")

            # 2. 创建分离输出目录
            separation_dir = os.path.join(temp_dir, "separated")
            os.makedirs(separation_dir, exist_ok=True)
            logger.info(f"分离输出目录: {separation_dir}")

            vocals_segments = []
            accompaniment_segments = []

            # 3. 处理每个片段
            for i, segment in enumerate(segment_files):
                logger.info(f"处理片段 {i + 1}/{len(segment_files)}: {os.path.basename(segment)}")
                cmd = ["ffprobe", "-i", segment, "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"]
                seg_duration = float(subprocess.check_output(cmd).decode().strip())
                logger.info(f"片段 {i + 1} 时长: {seg_duration:.2f}秒")
                # 为每个片段创建单独的输出目录
                segment_output_dir = os.path.join(separation_dir, f"segment_{i:03d}")
                os.makedirs(segment_output_dir, exist_ok=True)

                try:
                    vocals, accompaniment = self.separate_segment(segment, segment_output_dir)
                    vocals_segments.append(vocals)
                    accompaniment_segments.append(accompaniment)
                except Exception as e:
                    logger.error(f"处理片段失败: {segment} - {str(e)}")
                    # 跳过失败的片段
                    continue

            if not vocals_segments or not accompaniment_segments:
                raise RuntimeError("所有片段处理失败，无法继续合并")

            logger.info(f"预期总时长: {total_duration:.2f}秒, 实际将合并 {len(vocals_segments)} 个片段")
            # 4. 合并结果
            logger.info("合并人声片段...")
            if not self.concatenate_audio(vocals_segments, output_vocals):
                raise RuntimeError("人声合并失败")

            logger.info("合并伴奏片段...")
            if not self.concatenate_audio(accompaniment_segments, output_accompaniment):
                raise RuntimeError("伴奏合并失败")

            logger.info(f"人声文件已保存到: {output_vocals}")
            logger.info(f"伴奏文件已保存到: {output_accompaniment}")

            return True
        except Exception as e:
            logger.error(f"音频分离失败: {str(e)}")
            return False
        finally:
            # 5. 清理临时文件
            if segments_dir and os.path.exists(segments_dir):
                shutil.rmtree(segments_dir, ignore_errors=True)
            if separation_dir and os.path.exists(separation_dir):
                shutil.rmtree(separation_dir, ignore_errors=True)

    def separate_video(self, video_path, output_vocals, output_accompaniment):
        """
        从视频中分离人声和伴奏

        :param video_path: 输入视频文件路径
        :param output_vocals: 输出人声文件路径
        :param output_accompaniment: 输出伴奏文件路径
        """
        audio_path = None
        # 在视频所在目录创建temp文件夹
        video_dir = os.path.dirname(video_path)
        temp_dir = os.path.join(video_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        logger.info(f"创建临时目录: {temp_dir}")

        try:
            # 1. 提取音频
            audio_path = self.extract_audio(video_path, temp_dir)
            logger.info(f"成功提取音频: {audio_path}")

            # 2. 分离音频
            success = self.separate_audio(audio_path, output_vocals, output_accompaniment, temp_dir)

            if success:
                logger.info("分离成功完成!")
            else:
                logger.error("分离过程中出现错误")

            return success
        except Exception as e:
            logger.error(f"视频分离失败: {str(e)}")
            return False
        finally:
            # 3. 清理临时音频文件
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except Exception:
                    pass
            # 保留temp目录，不清除，以便用户查看中间文件


if __name__ == '__main__':
    video = r"D:\Github\20240708Move_video_2\source_file\START-327.mp4"
    spleeter_model = r"..\Model\spleeter_model\2stems_model.json"
    output_vocals = f"{os.path.dirname(video)}\\{os.path.basename(video)[:-4]}_(Vocals).wav"
    output_accompaniment = f"{os.path.dirname(video)}\\{os.path.basename(video)[:-4]}_(Instrumental).wav"

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_vocals), exist_ok=True)
    os.makedirs(os.path.dirname(output_accompaniment), exist_ok=True)

    try:
        logger.info("开始音频分离处理...")
        separator = AudioSeparator(spleeter_model_config=spleeter_model,max_segment_duration=5*60)

        # 处理视频文件
        success = separator.separate_video(
            video_path=video,
            output_vocals=output_vocals,
            output_accompaniment=output_accompaniment
        )

        if success:
            logger.info("处理成功完成!")
        else:
            logger.error("处理过程中出现错误")
    except Exception as e:
        logger.error(f"程序运行出错: {str(e)}")