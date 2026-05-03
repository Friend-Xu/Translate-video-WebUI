"""
视频合并器 — VideoMerger

提供 ffmpeg concat 和 moviepy 两种视频段合并策略。
ffmpeg 方案使用 concat demuxer（stream copy，不重编码，速度极快），
moviepy 方案使用 concatenate_videoclips（慢但兼容性好）。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MergerConfig:
    """合并器配置"""
    strategy: str = "ffmpeg"
    """合并策略: "ffmpeg" | "moviepy"  """

    video_encoder: str = "libx264"
    """视频编码器（moviepy 策略或 ffmpeg 重编码时使用）"""

    audio_encoder: str = "aac"
    """音频编码器"""

    concat_use_stream_copy: bool = True
    """ffmpeg 策略是否使用 stream copy（不重编码，最快）。
    若各视频段编码参数不完全一致，设 False 回退到重编码。"""


class VideoMerger:
    """视频段合并器。

    策略模式：可选择 ffmpeg concat 或 moviepy concatenate。
    默认 ffmpeg concat demuxer（最快，不重编码）。
    """

    def __init__(
        self,
        config: MergerConfig,
        ffmpeg_exe: Optional[str] = None,
    ):
        """
        Args:
            config: 合并器配置
            ffmpeg_exe: ffmpeg 可执行文件路径（None 则自动查找）
        """
        self.config = config
        self._ffmpeg = ffmpeg_exe

    def _get_ffmpeg(self) -> str:
        if self._ffmpeg:
            return self._ffmpeg
        from pipeline.utils import get_ffmpeg_exe
        exe = get_ffmpeg_exe()
        self._ffmpeg = exe
        return exe

    def _collect_segments(self, segment_dir: str) -> List[str]:
        """收集并排序视频段文件。

        文件名格式: TTS_START_END.mp4，按 START 升序排列。
        """
        if not os.path.isdir(segment_dir):
            return []
        files = [
            f for f in os.listdir(segment_dir)
            if f.endswith(".mp4") and f.startswith("TTS_")
        ]
        files.sort(key=lambda x: int(x.split("_")[1]))
        return [os.path.join(segment_dir, f) for f in files]

    def merge(self, segment_dir: str, output_path: str) -> Optional[str]:
        """合并视频段。

        Args:
            segment_dir: 视频段目录（含 TTS_*.mp4 文件）
            output_path: 最终输出视频路径

        Returns:
            成功返回 output_path，失败返回 None
        """
        segments = self._collect_segments(segment_dir)
        if not segments:
            print("[VideoMerger] 没有找到 TTS_*.mp4 视频段文件")
            return None

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if len(segments) == 1:
            # 只有一个段，直接复制
            import shutil
            shutil.copy2(segments[0], output_path)
            print(f"[VideoMerger] 单段复制到 {output_path}")
            return output_path

        print(f"[VideoMerger] 合并 {len(segments)} 个视频段 → {output_path}")

        if self.config.strategy == "ffmpeg":
            return self._ffmpeg_merge(segments, output_path)
        elif self.config.strategy == "moviepy":
            return self._moviepy_merge(segments, output_path)
        else:
            raise ValueError(f"不支持的合并策略: {self.config.strategy}")

    # ── ffmpeg concat demuxer ──────────────────────────

    def _ffmpeg_merge(self, segments: List[str], output_path: str) -> Optional[str]:
        """使用 ffmpeg concat demuxer 合并。

        生成 manifest.txt，然后:
        `ffmpeg -f concat -safe 0 -i manifest.txt [-c copy] output.mp4`

        使用 stream copy 时不重编码，速度最快。
        """
        ffmpeg = self._get_ffmpeg()
        seg_dir = os.path.dirname(segments[0])

        # 生成 concat 分清单
        manifest = os.path.join(seg_dir, "concat_manifest.txt")
        with open(manifest, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(f"file '{os.path.basename(seg)}'\n")

        # 构建命令
        cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", manifest]
        if self.config.concat_use_stream_copy:
            cmd.extend(["-c", "copy"])
        else:
            cmd.extend(["-c:v", self.config.video_encoder, "-c:a", self.config.audio_encoder])
        cmd.append(output_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            print(f"[VideoMerger] ffmpeg 不可用: {ffmpeg}")
            # 清理 manifest
            try:
                os.remove(manifest)
            except OSError:
                pass
            return None

        # 清理 manifest
        try:
            os.remove(manifest)
        except OSError:
            pass

        if result.returncode != 0:
            print(f"[VideoMerger] ffmpeg concat 失败 (returncode={result.returncode})")
            # 截取最后几行 stderr 作为错误摘要
            err_lines = result.stderr.strip().split("\n")[-5:]
            for line in err_lines:
                if line.strip():
                    print(f"  {line.strip()}")
            return None

        print(f"[VideoMerger] ffmpeg concat 完成: {output_path}")
        return output_path

    # ── moviepy concatenate ────────────────────────────

    def _moviepy_merge(self, segments: List[str], output_path: str) -> Optional[str]:
        """使用 moviepy concatenate_videoclips 合并。

        一次性加载所有片段并合并，兼容性好但速度较慢。
        """
        try:
            from moviepy import VideoFileClip, concatenate_videoclips
        except ImportError:
            print("[VideoMerger] moviepy 不可用，无法使用 moviepy 策略")
            return None

        clips = []
        try:
            for seg in segments:
                clip = VideoFileClip(seg)
                clips.append(clip)

            final = concatenate_videoclips(clips, method="chain")
            final.write_videofile(
                output_path,
                codec=self.config.video_encoder,
                audio_codec=self.config.audio_encoder,
                logger=None,
            )
            final.close()
            print(f"[VideoMerger] moviepy concat 完成: {output_path}")
            return output_path

        except Exception as e:
            print(f"[VideoMerger] moviepy 合并失败: {e}")
            return None

        finally:
            for c in clips:
                try:
                    c.close()
                except Exception:
                    pass
