import os
import logging
import json
import tempfile
import shutil
import subprocess
from datetime import datetime
from SRT_Extract import SRT_Extractor
from separate_vocals import AudioSeparator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("video_subtitle_pipeline.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("VideoSubtitlePipeline")


class VideoSubtitlePipeline:
    def __init__(self, spleeter_model_config, temp_dir=None):
        """
        初始化视频字幕处理管道

        :param spleeter_model_config: Spleeter模型配置文件路径
        :param temp_dir: 临时文件目录（可选）
        """
        self.spleeter_model_config = spleeter_model_config
        self.temp_dir = temp_dir or os.path.join(os.getcwd(), "video_pipeline_temp")
        self.audio_separator = None

        # 确保临时目录存在
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"临时目录设置为: {self.temp_dir}")

    def initialize_components(self):
        """初始化音频分离组件"""
        try:
            logger.info("初始化音频分离器...")
            self.audio_separator = AudioSeparator(
                spleeter_model_config=self.spleeter_model_config
            )
            logger.info("音频分离器初始化完成")
            return True
        except Exception as e:
            logger.error(f"初始化失败: {str(e)}", exc_info=True)
            return False

    def get_media_duration(self, file_path):
        """
        获取媒体文件（视频或音频）的时长（秒）
        :param file_path: 文件路径
        :return: 时长（秒）或失败时返回None
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFprobe执行失败: {result.stderr.strip()}")
                return None

            duration = float(result.stdout.strip())
            logger.info(f"{os.path.basename(file_path)} 时长: {duration:.2f}秒")
            return duration
        except Exception as e:
            logger.error(f"获取媒体时长失败: {str(e)}", exc_info=True)
            return None

    def extract_audio_from_video(self, video_path, output_audio_path):
        """从视频中提取音频并验证时长一致性"""
        try:
            logger.info(f"从视频中提取音频: {video_path}")

            # 1. 获取视频原始音频时长
            video_duration = self.get_media_duration(video_path)
            if video_duration is None:
                logger.error("无法获取视频时长，跳过验证")

            # 2. 提取音频
            cmd = [
                'ffmpeg',
                '-i', video_path,  # 输入视频文件
                '-map', '0:a',  # 映射所有音频流
                '-c:a', 'pcm_s16le',  # 音频编码器：PCM 16位小端
                '-ar', '48000',  # 采样率：48kHz
                '-ac', '2',  # 声道数：立体声
                '-fflags', '+genpts',  # 生成缺失的PTS
                '-vsync', '0',  # 禁用视频同步
                '-async', '1',  # 强制音频重新采样
                '-y',  # 覆盖输出文件
                output_audio_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg提取音频失败: {result.stderr}")
                return False

            logger.info(f"音频提取成功: {output_audio_path}")

            # 3. 验证音频时长
            if video_duration is not None:
                audio_duration = self.get_media_duration(output_audio_path)
                if audio_duration is None:
                    logger.warning("无法获取提取音频的时长，跳过验证")
                else:
                    # 允许1秒内的差异（FFmpeg处理误差）
                    if abs(audio_duration - video_duration) > 1.0:
                        logger.error(f"音频时长不一致! 视频: {video_duration:.2f}秒, 音频: {audio_duration:.2f}秒")
                        return False
                    else:
                        logger.info("音频时长验证通过 (与视频一致)")
            return True
        except Exception as e:
            logger.error(f"提取音频失败: {str(e)}", exc_info=True)
            return False

    def split_audio(self, audio_path, segment_duration=600):
        """
        切分音频为多个片段（使用SRT_Extractor的改进方法）
        :param audio_path: 音频文件路径
        :param segment_duration: 每个片段的时长（秒）
        :return: 片段目录路径和片段列表
        """
        try:
            # 创建SRT_Extractor实例（不进行实际提取）
            extractor = SRT_Extractor(audio_path, output_format="json")

            # 获取音频时长
            duration = extractor.audio_duration
            if duration <= 0:
                logger.error("获取音频时长失败，使用FFprobe验证")
                duration = self.get_media_duration(audio_path) or 0

            logger.info(f"音频总时长: {duration:.2f}秒")

            # 使用改进的分段方法切分音频
            segment_files = extractor.split_large_audio(
                max_duration=segment_duration,
                min_silence_len=500,
                silence_thresh=-40
            )

            # 验证分段结果
            if not segment_files:
                logger.error("音频切分未生成任何片段")
                return []

            total_segments_duration = 0
            for segment in segment_files:
                seg_duration = self.get_media_duration(segment)
                if seg_duration:
                    total_segments_duration += seg_duration
                    logger.debug(f"片段 {os.path.basename(segment)} 时长: {seg_duration:.2f}秒")

            # 验证分段总时长
            if abs(total_segments_duration - duration) > 5.0:
                logger.warning(f"分段总时长不一致! 原始: {duration:.2f}秒, 分段: {total_segments_duration:.2f}秒")
            else:
                logger.info(f"分段总时长验证通过: {total_segments_duration:.2f}秒")

            logger.info(f"成功切分音频为 {len(segment_files)} 个片段")
            return segment_files
        except Exception as e:
            logger.error(f"音频切分失败: {str(e)}", exc_info=True)
            return []

    def process_audio_segment(self, segment_path, index, total_segments):
        """
        处理单个音频片段：分离人声 -> 生成字幕
        :return: 人声音频路径和JSON结果路径
        """
        try:
            logger.info(f"处理音频片段 [{index + 1}/{total_segments}]: {os.path.basename(segment_path)}")

            # 1. 分离人声
            vocals_dir = os.path.join(self.temp_dir, f"vocals_{index:03d}")
            os.makedirs(vocals_dir, exist_ok=True)

            vocals_path, _ = self.audio_separator.separate_segment(
                segment_path=segment_path,
                output_dir=vocals_dir
            )

            if not vocals_path or not os.path.exists(vocals_path):
                logger.error(f"人声分离失败: {segment_path}")
                return None, None

            # 2. 获取原始片段和人声片段时长
            original_duration = self.get_media_duration(segment_path)
            vocals_duration = self.get_media_duration(vocals_path)

            if original_duration and vocals_duration:
                # 允许0.5秒内的差异（Spleeter处理误差）
                if abs(original_duration - vocals_duration) > 0.5:
                    logger.warning(
                        f"人声片段时长不一致! 原始: {original_duration:.2f}秒, 人声: {vocals_duration:.2f}秒")

            # 3. 生成字幕JSON
            json_path = os.path.join(self.temp_dir, f"subtitle_{index:03d}.json")
            extractor = SRT_Extractor(vocals_path, output_format="json")

            # 直接处理（不分割，因为片段已经很小）
            extractor.extract_with_timestamped(model="medium", lang="ja")

            # 检查结果
            if os.path.exists(json_path):
                return vocals_path, json_path
            else:
                logger.error(f"字幕JSON生成失败: {segment_path}")
                return None, None
        except Exception as e:
            logger.error(f"处理音频片段失败: {str(e)}", exc_info=True)
            return None, None

    def merge_json_results(self, json_files, output_path):
        """合并多个JSON字幕结果"""
        try:
            # 读取所有JSON结果
            results = []
            total_duration = 0.0

            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # 计算每个分段的总时长
                    if data.get("segments"):
                        last_segment = data["segments"][-1]
                        segment_duration = last_segment["end"]
                        total_duration += segment_duration
                        logger.info(f"加载字幕结果: {os.path.basename(json_file)} (时长: {segment_duration:.2f}秒)")
                    else:
                        logger.warning(f"字幕结果无有效片段: {os.path.basename(json_file)}")
                        segment_duration = 0

                    results.append(data)
                except Exception as e:
                    logger.error(f"加载JSON失败 {json_file}: {str(e)}")

            if not results:
                logger.error("没有可合并的字幕结果")
                return False

            logger.info(f"将合并 {len(results)} 个分段，总时长: {total_duration:.2f}秒")

            # 创建虚拟提取器用于合并
            dummy_extractor = SRT_Extractor("dummy.wav", output_format="json")
            merged_result = dummy_extractor.merge_results(results)

            # 保存合并后的JSON
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(merged_result, f, ensure_ascii=False, indent=4)

            # 验证合并结果时长
            if merged_result.get("segments"):
                merged_duration = merged_result["segments"][-1]["end"]
                logger.info(f"合并后总时长: {merged_duration:.2f}秒")
                if abs(merged_duration - total_duration) > 1.0:
                    logger.warning(f"合并后时长不一致! 预期: {total_duration:.2f}秒, 实际: {merged_duration:.2f}秒")

            logger.info(f"合并字幕JSON保存到: {output_path}")
            return True
        except Exception as e:
            logger.error(f"合并JSON失败: {str(e)}", exc_info=True)
            return False

    def generate_final_srt(self, merged_json_path, output_srt_path):
        """从合并的JSON生成最终SRT字幕"""
        try:
            # 创建虚拟提取器
            extractor = SRT_Extractor("dummy.wav", output_format="srt")

            # 读取合并的JSON
            with open(merged_json_path, 'r', encoding='utf-8') as f:
                merged_data = json.load(f)

            # 生成SRT
            extractor._convert_to_srt(merged_data, output_srt_path)

            if os.path.exists(output_srt_path):
                # 验证SRT文件
                srt_size = os.path.getsize(output_srt_path)
                if srt_size < 1024:  # 小于1KB可能是空文件
                    logger.error(f"SRT文件过小 ({srt_size}字节)，可能生成失败")
                    return False

                logger.info(f"最终SRT字幕生成: {output_srt_path} ({srt_size / 1024:.1f}KB)")
                return True
            else:
                logger.error("SRT生成失败")
                return False
        except Exception as e:
            logger.error(f"生成SRT失败: {str(e)}", exc_info=True)
            return False

    def process_video(self, video_path, output_srt_path, segment_duration=600):
        """
        完整处理流程：
        1. 从视频提取音频
        2. 改进式切分音频
        3. 处理每个音频片段
        4. 合并结果
        5. 生成SRT

        :param video_path: 输入视频路径
        :param output_srt_path: 输出SRT路径
        :param segment_duration: 每个视频片段时长（秒）
        """
        logger.info(f"开始处理视频: {video_path}")

        # 1. 初始化组件
        if not self.initialize_components():
            return False

        # 2. 提取音频并验证时长
        audio_path = os.path.join(self.temp_dir, "full_audio.wav")
        if not self.extract_audio_from_video(video_path, audio_path):
            logger.error("音频提取失败")
            return False

        # 3. 改进式切分音频并验证
        segment_files = self.split_audio(audio_path, segment_duration)
        if not segment_files:
            logger.error("音频切分失败")
            return False

        # 4. 处理每个音频片段
        vocals_files = []
        json_files = []

        for i, segment in enumerate(segment_files):
            vocals_path, json_path = self.process_audio_segment(segment, i, len(segment_files))

            if vocals_path:
                vocals_files.append(vocals_path)
            if json_path:
                json_files.append(json_path)

        if not json_files:
            logger.error("没有生成任何字幕结果")
            return False

        logger.info(f"成功处理 {len(json_files)}/{len(segment_files)} 个音频片段")

        # 5. 合并JSON结果
        merged_json_path = os.path.join(self.temp_dir, "merged_subtitles.json")
        if not self.merge_json_results(json_files, merged_json_path):
            return False

        # 6. 生成最终SRT
        if not self.generate_final_srt(merged_json_path, output_srt_path):
            return False

        logger.info(f"处理完成! 字幕文件: {output_srt_path}")
        return True

    def cleanup(self):
        """清理临时资源"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"已清理临时目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"清理临时目录失败: {str(e)}")


if __name__ == '__main__':
    # 配置参数
    VIDEO_PATH = r"D:\Github\20240708Move_video_2\source_file\START-327.mp4"
    SPLEETER_MODEL = r"..\Model\spleeter_model\2stems_model.json"
    OUTPUT_SRT = r"D:\Github\20240708Move_video_2\source_file\START-327.srt"

    # 创建处理管道
    pipeline = VideoSubtitlePipeline(
        spleeter_model_config=SPLEETER_MODEL,
        temp_dir=r"D:\Github\20240708Move_video_2\source_file\temp"
    )

    try:
        # 处理视频并生成字幕
        success = pipeline.process_video(
            video_path=VIDEO_PATH,
            output_srt_path=OUTPUT_SRT,
            segment_duration=300  # 5分钟片段
        )

        if success:
            logger.info("处理成功完成!")
        else:
            logger.error("处理失败")
    except Exception as e:
        logger.error(f"处理过程中出错: {str(e)}", exc_info=True)
    finally:
        # 清理临时文件
        pipeline.cleanup()