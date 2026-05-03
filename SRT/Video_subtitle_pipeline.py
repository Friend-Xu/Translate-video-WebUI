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
    def __init__(self, spleeter_model_config, lang="en", temp_dir=None):
        """
        初始化视频字幕处理管道

        :param spleeter_model_config: Spleeter模型配置文件路径
        :param temp_dir: 临时文件目录（可选）
        """
        self.spleeter_model_config = spleeter_model_config
        self.temp_dir = temp_dir or os.path.join(os.getcwd(), "video_pipeline_temp")
        self.audio_separator = None
        self.lang=lang
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
            logger.debug(f"获取媒体时长: {file_path}")

            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",  # 使用JSON格式输出
                file_path
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=300,
                    encoding='utf-8',  # 指定编码
                    errors='replace'  # 替换无法解码的字符
                )
            except subprocess.TimeoutExpired:
                logger.error("FFprobe执行超时（5分钟），文件可能过大")
                return None

            if result.returncode != 0:
                logger.error(f"FFprobe执行失败: {result.stderr.strip()}")
                return None

            # 解析JSON输出
            try:
                probe_data = json.loads(result.stdout)
                duration = float(probe_data["format"]["duration"])
                logger.info(f"{os.path.basename(file_path)} 时长: {duration:.2f}秒")
                return duration
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"解析JSON输出失败: {str(e)}")

                # 尝试回退到原始文本解析方法
                try:
                    output = result.stdout.strip()
                    if output:
                        # 尝试提取所有数值并取最后一个
                        numbers = [float(x) for x in output.split() if x.replace('.', '', 1).isdigit()]
                        if numbers:
                            return numbers[-1]
                except Exception as fallback_e:
                    logger.error(f"回退解析也失败: {str(fallback_e)}")

                return None
        except Exception as e:
            logger.error(f"获取媒体时长失败: {str(e)}", exc_info=True)
            return None

    def split_video_with_audio_cutpoints(self, video_path, cut_points):
        """
        使用音频切割点切分视频
        :param video_path: 输入视频路径
        :param cut_points: 切割点列表（秒）
        :return: 视频片段列表
        """
        try:
            # 创建视频片段目录
            segments_dir = os.path.join(self.temp_dir, "video_segments")
            os.makedirs(segments_dir, exist_ok=True)

            # 将切割点转换为FFmpeg格式
            cut_points_str = ",".join([str(cp) for cp in cut_points])

            logger.info(f"使用切割点切分视频: {cut_points_str}")
            output_pattern = os.path.join(segments_dir, "segment_%03d.mp4")

            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-c", "copy",  # 复制流，不重新编码
                "-f", "segment",
                "-segment_times", cut_points_str,
                "-reset_timestamps", "1",  # 每个片段从0开始
                "-map", "0",  # 包含所有流
                output_pattern
            ]

            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    encoding='utf-8',  # 指定编码
                                    errors='replace'  # 替换无法解码的字符
                                    )
            if result.returncode != 0:
                logger.error(f"视频切分失败: {result.stderr}")
                return []

            # 获取生成的片段
            segment_files = sorted([
                os.path.join(segments_dir, f)
                for f in os.listdir(segments_dir)
                if f.startswith("segment_") and f.endswith(".mp4")
            ])

            # 获取每个片段的持续时间
            segment_durations = []
            for seg in segment_files:
                duration = self.get_media_duration(seg)
                if duration is None:
                    logger.error(f"无法获取片段 {seg} 的时长")
                    return [], []
                segment_durations.append(duration)

            logger.info(f"成功切分视频为 {len(segment_files)} 个片段")
            return segment_files, segment_durations
        except Exception as e:
            logger.error(f"视频切分失败: {str(e)}", exc_info=True)
            return [], []

    def check_ffmpeg_available(self):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def extract_audio_from_video(self, video_path, output_audio_path):
        """从视频中提取音频并验证时长一致性"""
        try:
            logger.info(f"从视频中提取音频: {video_path}")
            # 1. 检查FFmpeg可用性
            if not self.check_ffmpeg_available():
                return False
            # 2. 验证输入文件存在
            if not os.path.exists(video_path):
                logger.error(f"视频文件不存在: {video_path}")
                return False
            # 3. 确保输出目录存在
            os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

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
            try:
                # 使用明确的编码设置
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',  # 指定UTF-8编码
                    errors='replace',  # 替换无法解码的字符
                    timeout=600  # 增加超时时间（10分钟）
                )
                if result.returncode != 0:
                    logger.error(f"FFmpeg提取音频失败: {result.stderr}")
                    return False

                logger.info(f"音频提取成功: {output_audio_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg执行失败: {e.stderr.strip()}")
                return False
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

    def find_optimal_cut_points(self, audio_path, segment_duration=600):
        """
        使用改进的音频切分方法找到最佳切割点
        :param audio_path: 音频文件路径
        :param segment_duration: 目标片段时长（秒）
        :return: 切割点列表（秒）
        """
        try:
            # 创建SRT_Extractor实例
            extractor = SRT_Extractor(audio_path, output_format="json")

            # 获取音频时长
            duration = extractor.audio_duration
            if duration <= 0:
                logger.error("获取音频时长失败，使用FFprobe验证")
                duration = self.get_media_duration(audio_path) or 0

            logger.info(f"音频总时长: {duration:.2f}秒")

            # 计算需要的分段数量
            num_segments = max(1, round(duration / segment_duration))
            ideal_cut_points = [i * segment_duration for i in range(1, num_segments)]

            logger.info(f"目标切割点: {ideal_cut_points}")

            # 使用pydub检测静音区域
            try:
                from pydub import AudioSegment
                from pydub.silence import detect_nonsilent
            except ImportError:
                logger.error("请安装pydub: pip install pydub")
                return ideal_cut_points

            # 加载音频
            audio = AudioSegment.from_file(audio_path)

            # 检测语音活动区域
            speech_ranges = detect_nonsilent(
                audio,
                min_silence_len=500,  # 最小静音长度（毫秒）
                silence_thresh=-40  # 静音阈值（dB）
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
                point_ms = point * 1000  # 转换为毫秒
                best_cut = point_ms
                best_score = float('inf')  # 初始化为最大值

                # 在理想切割点附近寻找最佳静音位置
                search_start = max(0, point_ms - 5000)  # 向前搜索5秒
                search_end = min(len(audio), point_ms + 5000)  # 向后搜索5秒

                for silence_start, silence_end in silence_ranges:
                    # 确保静音区间在搜索范围内
                    if silence_end < search_start or silence_start > search_end:
                        continue

                    # 计算静音区间中点的分数（距离理想点的偏移）
                    silence_mid = (silence_start + silence_end) / 2
                    distance = abs(silence_mid - point_ms)

                    # 优先选择长静音段
                    silence_length = silence_end - silence_start
                    score = distance / (silence_length + 1)  # 长度越大分数越小

                    if score < best_score:
                        best_score = score
                        best_cut = silence_mid

                actual_cut_points.append(best_cut / 1000)  # 转换回秒

            logger.info(f"优化后的切割点: {actual_cut_points}")
            return actual_cut_points
        except Exception as e:
            logger.error(f"寻找切割点失败: {str(e)}", exc_info=True)
            return []

    def process_video_segment(self, segment_path, index, total_segments):
        """
        处理单个视频片段：提取音频 -> 分离人声 -> 生成字幕
        :return: 字幕JSON文件路径
        """
        try:
            logger.info(f"处理视频片段 [{index + 1}/{total_segments}]: {os.path.basename(segment_path)}")

            # 1. 提取片段音频
            audio_path = os.path.join(self.temp_dir, f"segment_{index:03d}.wav")
            if not self.extract_audio_from_video(segment_path, audio_path):
                return None

            # 2. 分离人声
            vocals_dir = os.path.join(self.temp_dir, f"vocals_{index:03d}")
            os.makedirs(vocals_dir, exist_ok=True)

            vocals_path, _ = self.audio_separator.separate_segment(
                segment_path=audio_path,
                output_dir=vocals_dir
            )

            if not vocals_path or not os.path.exists(vocals_path):
                logger.error(f"人声分离失败: {segment_path}")
                return None

            # 3. 生成字幕JSON - 修复路径问题
            vocals_base = os.path.splitext(os.path.basename(vocals_path))[0]
            expected_json = os.path.join(vocals_dir, f"{vocals_base}.json")

            extractor = SRT_Extractor(vocals_path,lang=self.lang, output_format="json")

            # 直接处理（不分割，因为片段已经很小）
            extractor.extract_with_timestamped(model="medium", lang=self.lang)

            # 检查实际生成的文件路径
            if os.path.exists(expected_json):
                # 复制到主临时目录
                json_path = os.path.join(self.temp_dir, f"subtitle_{index:03d}.json")
                shutil.copyfile(expected_json, json_path)
                logger.info(f"字幕JSON生成成功: {json_path}")
                return json_path
            else:
                # 检查可能的其他位置
                possible_files = [
                    os.path.join(vocals_dir, f"{vocals_base}.words.json"),
                    os.path.join(vocals_dir, "output.json"),
                    os.path.join(vocals_dir, "result.json")
                ]

                for file_path in possible_files:
                    if os.path.exists(file_path):
                        json_path = os.path.join(self.temp_dir, f"subtitle_{index:03d}.json")
                        shutil.copyfile(file_path, json_path)
                        logger.warning(f"找到备选字幕文件并复制: {file_path} -> {json_path}")
                        return json_path

                logger.error(f"字幕JSON生成失败，未找到任何文件。可能位置: {vocals_dir}")
                return None

        except Exception as e:
            logger.error(f"处理视频片段失败: {str(e)}", exc_info=True)
            return None

    def merge_json_results(self, json_files, segment_durations, output_path):
        """合并多个JSON字幕结果，考虑每个片段的实际持续时间"""
        try:
            # 读取所有JSON结果
            results = []
            total_video_duration = sum(segment_durations)  # 视频总时长

            for i, json_file in enumerate(json_files):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    results.append((data, segment_durations[i]))
                except Exception as e:
                    logger.error(f"加载JSON失败 {json_file}: {str(e)}")
                    # 添加空数据占位符
                    results.append(({"segments": []}, segment_durations[i]))

            if not results:
                logger.error("没有可合并的字幕结果")
                return False

            logger.info(f"将合并 {len(results)} 个分段，视频总时长: {total_video_duration:.2f}秒")

            # 创建合并后的结果结构
            merged_result = {
                "text": "",
                "segments": [],
                "language": "ja"  # 假设所有片段都是日语
            }

            # 累计偏移时间（前面所有片段的持续时间总和）
            time_offset = 0.0

            for i, (data, duration) in enumerate(results):
                segments = data.get("segments", [])
                last_segment_end = segments[-1]["end"] if segments else 0

                # 计算实际时间差（片段时长 - 最后一个字幕结束时间）
                time_gap = max(0, duration - last_segment_end)
                logger.debug(
                    f"片段 {i}: 字幕时长 {last_segment_end:.2f}s, 视频时长 {duration:.2f}s, 静音间隙 {time_gap:.2f}s")

                # 调整当前片段的时间戳
                for segment in segments:
                    adjusted_segment = segment.copy()
                    adjusted_segment["start"] += time_offset
                    adjusted_segment["end"] += time_offset
                    merged_result["segments"].append(adjusted_segment)

                    # 合并文本
                    merged_result["text"] += segment["text"] + " "

                # 更新偏移量：加上整个片段的持续时间（包括静音部分）
                time_offset += duration

            # 保存合并后的JSON
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(merged_result, f, ensure_ascii=False, indent=4)

            # 验证合并结果时长
            if merged_result["segments"]:
                merged_duration = merged_result["segments"][-1]["end"]
                logger.info(f"合并后总时长: {merged_duration:.2f}秒")
                if abs(merged_duration - total_video_duration) > 1.0:
                    logger.warning(
                        f"字幕与视频总时长不一致! 字幕: {merged_duration:.2f}秒, 视频: {total_video_duration:.2f}秒")
                else:
                    logger.info("字幕与视频时长匹配良好")

            logger.info(f"合并字幕JSON保存到: {output_path}")
            return True
        except Exception as e:
            logger.error(f"合并JSON失败: {str(e)}", exc_info=True)
            return False

    def generate_final_srt(self, merged_json_path, output_srt_path, min_duration=0.7):
        """直接从合并的JSON生成最终SRT字幕，确保最小持续时间"""
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_srt_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
                logger.info(f"创建输出目录: {output_dir}")

            # 读取合并的JSON
            if not os.path.exists(merged_json_path):
                logger.error(f"合并的JSON文件不存在: {merged_json_path}")
                return False

            with open(merged_json_path, 'r', encoding='utf-8') as f:
                merged_data = json.load(f)

            # 准备SRT内容
            srt_content = []
            segments = merged_data.get("segments", [])

            if not segments:
                logger.error("合并的JSON中没有字幕片段")
                return False

            # 过滤和调整字幕片段
            filtered_segments = []
            current_text = ""
            current_start = 0
            current_end = 0

            for segment in segments:
                start = segment["start"]
                end = segment["end"]
                text = segment["text"].strip()

                # 计算持续时间
                duration = end - start

                # 如果持续时间太短，合并到当前片段
                if duration < min_duration:
                    if not current_text:
                        # 开始新的合并片段
                        current_start = start
                        current_text = text
                    else:
                        # 继续合并到当前片段
                        current_text += " " + text
                    current_end = end
                else:
                    # 如果有待合并的片段，先处理
                    if current_text:
                        # 确保合并后的片段满足最小持续时间
                        if current_end - current_start < min_duration:
                            current_end = current_start + min_duration

                        filtered_segments.append({
                            "start": current_start,
                            "end": current_end,
                            "text": current_text
                        })
                        current_text = ""

                    # 添加当前满足条件的片段
                    filtered_segments.append({
                        "start": start,
                        "end": end,
                        "text": text
                    })

            # 处理最后一个合并片段
            if current_text:
                if current_end - current_start < min_duration:
                    current_end = current_start + min_duration
                filtered_segments.append({
                    "start": current_start,
                    "end": current_end,
                    "text": current_text
                })

            logger.info(f"原始字幕片段: {len(segments)}，过滤后片段: {len(filtered_segments)}")

            if not filtered_segments:
                logger.error("没有满足最小持续时间的字幕片段")
                return False

            # 生成SRT内容
            for i, segment in enumerate(filtered_segments, start=1):
                start_time = self.format_time(segment["start"])
                end_time = self.format_time(segment["end"])
                text = segment["text"]

                srt_content.append(f"{i}")
                srt_content.append(f"{start_time} --> {end_time}")
                srt_content.append(text)
                srt_content.append("")  # 空行分隔

            # 写入SRT文件
            with open(output_srt_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(srt_content))

            # 验证文件
            if os.path.exists(output_srt_path):
                srt_size = os.path.getsize(output_srt_path)
                if srt_size < 1024:
                    logger.warning(f"SRT文件过小 ({srt_size}字节)，但可能有效")
                logger.info(f"SRT生成成功: {output_srt_path} ({srt_size / 1024:.1f}KB)")
                return True

            logger.error("SRT文件写入失败")
            return False

        except Exception as e:
            logger.error(f"生成SRT失败: {str(e)}", exc_info=True)
            return False
    def format_time(self, seconds):
        """将秒数格式化为SRT时间格式 (HH:MM:SS,mmm)"""
        try:
            # 处理负值（虽然不应该出现）
            if seconds < 0:
                seconds = 0
                logger.warning("检测到负时间值，已重置为0")

            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            seconds_remain = seconds % 60
            milliseconds = int((seconds_remain - int(seconds_remain)) * 1000)

            # 确保毫秒在0-999范围内
            milliseconds = max(0, min(999, milliseconds))

            return f"{hours:02d}:{minutes:02d}:{int(seconds_remain):02d},{milliseconds:03d}"
        except Exception as e:
            logger.error(f"时间格式化失败: {seconds}秒, 错误: {str(e)}")
            return "00:00:00,000"  # 默认值
    def process_video(self, video_path, output_srt_path, segment_duration=600):
        """
        完整处理流程（视频切分版）：
        1. 提取视频音频
        2. 找到最佳切割点
        3. 切分视频
        4. 处理每个视频片段
        5. 合并结果
        6. 生成SRT

        :param video_path: 输入视频路径
        :param output_srt_path: 输出SRT路径
        :param segment_duration: 每个视频片段时长（秒）
        """
        logger.info(f"开始处理视频: {video_path}")

        # 1. 初始化组件
        if not self.initialize_components():
            return False

        # 1.5 视频时长缺陷检测 (通用, 所有视频适用)
        try:
            from MediaValidator import MediaValidator
            validator = MediaValidator()
            result = validator.diagnose(video_path)
            if result.status == "defect":
                logger.info(
                    f"视频缺陷检测: {result.defect_type} - {result.defect_name}, "
                    f"详细: {result.details}"
                )
                logger.info("音频提取时将自动 aresample 修正 (ensure_audio_duration)")
            else:
                logger.info(f"视频无时长缺陷: {result.details}")
        except ImportError:
            logger.warning("MediaValidator 不可用, 跳过时长检测")
        except Exception as e:
            logger.warning(f"视频检测失败 (不影响流程): {e}")

        # 2. 提取音频用于寻找切割点
        audio_path = os.path.join(self.temp_dir, "full_audio.wav")
        if not self.extract_audio_from_video(video_path, audio_path):
            logger.error("音频提取失败")
            return False

        # 3. 找到最佳切割点
        cut_points = self.find_optimal_cut_points(audio_path, segment_duration)
        if not cut_points:
            logger.error("无法找到切割点，使用默认分段")
            video_duration = self.get_media_duration(video_path) or 0
            num_segments = max(1, int(video_duration / segment_duration))
            cut_points = [i * segment_duration for i in range(1, num_segments)]

        logger.info(f"最终切割点: {cut_points}")

        # 4. 使用切割点切分视频
        segment_files, segment_durations = self.split_video_with_audio_cutpoints(video_path, cut_points)
        if not segment_files:
            logger.error("视频切分失败")
            return False

        # 5. 处理每个视频片段 - 分批处理
        json_files = []
        processed_durations = []
        batch_size = 1  # 每次只处理一个片段

        for i, segment in enumerate(segment_files):
            logger.info(f"处理片段 {i + 1}/{len(segment_files)}")

            # 清除前一个片段的GPU缓存
            if i > 0:
                self.clear_gpu_cache()

            json_path = self.process_video_segment(segment, i, len(segment_files))
            if json_path:
                json_files.append(json_path)
                processed_durations.append(segment_durations[i])

            # 显式释放资源
            self.release_resources()

        if not json_files:
            logger.error("没有生成任何字幕结果")
            return False

        logger.info(f"成功处理 {len(json_files)}/{len(segment_files)} 个视频片段")

        # 6. 合并JSON结果
        merged_json_path = os.path.join(self.temp_dir, "merged_subtitles.json")
        if not self.merge_json_results(json_files, processed_durations, merged_json_path):
            return False
        video_json_path = os.path.splitext(video_path)[0]+".json"
        # 复制合并的JSON到视频同名文件
        try:
            shutil.copyfile(merged_json_path, video_json_path)
            logger.info(f"保存合并的JSON文件为: {video_json_path}")
        except Exception as e:
            logger.error(f"保存JSON文件失败: {str(e)}")
            return False
        # 7. 生成最终SRT
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

    def clear_gpu_cache(self):
        """清除GPU缓存以释放显存"""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("已清除GPU缓存")
        except ImportError:
            pass

    def release_resources(self):
        """释放GPU资源"""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.debug("释放GPU资源")
        except ImportError:
            pass
if __name__ == '__main__':
    # 配置参数
    VIDEO_PATH = r"D:\Github\20240708Move_video_2\source_file\Learn Python GUI Development for Desktop – PySide6 and Qt Tutorial.mp4"
    SPLEETER_MODEL = r"..\Model\spleeter_model\2stems_model.json"
    OUTPUT_SRT = r"D:\Github\20240708Move_video_2\source_file\Learn Python GUI Development for Desktop – PySide6 and Qt Tutorial.srt"

    # 创建处理管道
    pipeline = VideoSubtitlePipeline(
        spleeter_model_config=SPLEETER_MODEL,
        lang="en",
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