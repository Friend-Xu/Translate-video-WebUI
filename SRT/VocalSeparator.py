"""
VocalSeparator.py — Demucs 人声分离封装（Python API 版）

依据「字幕提取优化方案 v1.0」Phase 1 规格实现。
- 封装 demucs (htdemucs) 人声分离，使用 Python API 而非 CLI 子进程
- 用 torchaudio 加载音频，完全绕过 ffprobe 依赖
- 支持视频/音频输入
- 缓存检测：输出文件已存在时跳过处理
- 无时长限制（demucs 原生支持任意长度）
"""

import os
import sys
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import torch
import torchaudio

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("VocalSeparator")


class VocalSeparator:
    """Demucs 人声分离封装（Python API，无需 ffprobe）

    Usage:
        separator = VocalSeparator("path/to/video.mp4")
        vocal_path, inst_path = separator.separate()
    """

    DEFAULT_OUT_DIR = "separated"
    DEFAULT_MODEL = "htdemucs"

    def __init__(
        self,
        input_path: str,
        output_dir: Optional[str] = None,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
        verbose: bool = False,
    ):
        self.input_path = Path(input_path)
        if not self.input_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_path}")

        self.model_name = model_name
        self.device = device
        self.verbose = verbose

        # 输出目录
        if output_dir is None:
            output_dir = str(self.input_path.parent / self.DEFAULT_OUT_DIR)
        self.output_dir = Path(output_dir)

        self.track_name = self.input_path.stem

        # 缓存路径
        model_out = self.output_dir / self.model_name / self.track_name
        self._vocal_path = model_out / "vocals.wav"
        self._instrumental_path = model_out / "no_vocals.wav"

        # 确保 ffmpeg 可用（仅用于视频→音频提取）
        self._ensure_ffmpeg()

    # ── 公共接口 ──────────────────────────────────────

    def separate(self, force: bool = False) -> Tuple[str, str]:
        if not force and self.is_separated():
            logger.info(f"人声分离结果已存在，跳过处理: {self._vocal_path.parent}")
            return str(self._vocal_path), str(self._instrumental_path)

        audio_path = self._prepare_audio()
        logger.info(f"开始人声分离 (demucs {self.model_name})...")
        logger.info(f"  输入: {audio_path}")
        logger.info(f"  输出: {self.output_dir}")

        try:
            wav, sr = torchaudio.load(audio_path)
            logger.debug(f"  音频已加载: {list(wav.shape)}, {sr}Hz")
            self._run_demucs_api(wav, sr)
        finally:
            self._cleanup_temp(audio_path)

        if not self._vocal_path.exists():
            raise RuntimeError(f"人声分离失败，未生成输出文件: {self._vocal_path}")

        logger.info(f"人声分离完成:")
        logger.info(f"  人声: {self._vocal_path}")
        logger.info(f"  背景: {self._instrumental_path}")

        return str(self._vocal_path), str(self._instrumental_path)

    def get_vocal_path(self) -> str:
        return str(self._vocal_path)

    def get_instrumental_path(self) -> str:
        return str(self._instrumental_path)

    def is_separated(self) -> bool:
        return self._vocal_path.exists() and self._vocal_path.stat().st_size > 0

    # ── 内部方法 ──────────────────────────────────────

    def _ensure_ffmpeg(self):
        if self._find_on_path("ffmpeg"):
            return
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            ffmpeg_dir = os.path.dirname(ffmpeg_exe)
            ffmpeg_path = os.path.join(ffmpeg_dir, "ffmpeg.exe")
            if not os.path.exists(ffmpeg_path):
                for f in os.listdir(ffmpeg_dir):
                    if f.startswith("ffmpeg") and f.endswith(".exe"):
                        import shutil
                        shutil.copy2(os.path.join(ffmpeg_dir, f), ffmpeg_path)
                        break
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        except ImportError:
            logger.warning("imageio-ffmpeg 未安装，视频→音频提取将失败")

    @staticmethod
    def _find_on_path(name: str) -> bool:
        return any(
            os.path.exists(os.path.join(p, f"{name}.exe"))
            or os.path.exists(os.path.join(p, name))
            for p in os.environ.get("PATH", "").split(os.pathsep)
        )

    def _prepare_audio(self) -> str:
        """准备输入音频：视频→提取音轨，音频→直接使用

        通过 ensure_audio_duration() 自动检测并 aresample 修正
        音频时长偏差（AAC padding 导致的 CD > ADD 问题）。
        """
        ext = self.input_path.suffix.lower()
        audio_extensions = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma"}

        if ext in audio_extensions:
            return str(self.input_path)

        logger.info(f"从视频提取音频: {self.input_path.name}")

        # 使用共享工具 ensure_audio_duration 统一处理
        from MediaValidator import ensure_audio_duration

        temp_wav = os.path.join(
            tempfile.gettempdir(),
            f"vocal_sep_{self.track_name}_{os.urandom(4).hex()}.wav",
        )
        ensure_audio_duration(str(self.input_path), temp_wav, sr=44100, ch=2)

        self._temp_audio = temp_wav
        return temp_wav

    def _run_demucs_api(self, wav: torch.Tensor, sr: int):
        """使用 demucs Python API 执行分离（无 CLI 子进程）

        流程: load_model → convert_audio → normalize → apply_model → save
        """
        # 确保 Demucs 模型下载到项目本地
        _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.environ.setdefault("TORCH_HOME", os.path.join(_project_root, "models"))

        from demucs.apply import apply_model
        from demucs.audio import convert_audio, save_audio
        from demucs.pretrained import get_model_from_args
        from demucs import separate

        # 构造 CLI 参数（用于模型加载）
        parser = separate.get_parser()
        # 需要传入 dummy track 因为 parser 要求 positional arg
        cli_args = parser.parse_args([
            "/dev/null",  # dummy track，仅用于满足 parser
            "-n", self.model_name,
            "--two-stems", "vocals",
            "-o", str(self.output_dir),
            "--segment", "7",
            "--overlap", "0.25",
            "--float32",
            "--device", self.device,
        ])

        # 加载模型
        logger.info(f"  加载模型: {self.model_name}")
        model = get_model_from_args(cli_args)
        model.to(self.device)
        model.eval()

        # 检查 segment 上限 (htdemucs 最大 7.8s)
        from demucs.htdemucs import HTDemucs
        if isinstance(model, HTDemucs):
            max_segment = float(model.segment)
        elif hasattr(model, 'max_allowed_segment'):
            max_segment = model.max_allowed_segment
        else:
            max_segment = float("inf")
        segment = min(cli_args.segment, int(max_segment))

        # 重采样到模型期望格式
        wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)
        wav = wav.to(self.device)

        # 归一化
        ref = wav.mean(0)
        wav = wav - ref.mean()
        wav = wav / ref.std()

        # 推理
        audio_len_s = wav.shape[-1] / model.samplerate
        logger.info(f"  推理中... (segment={segment}s, 音频={audio_len_s:.1f}s)")
        try:
            with torch.no_grad():
                sources = apply_model(
                    model, wav[None], device=self.device,
                    shifts=cli_args.shifts, split=cli_args.split,
                    overlap=cli_args.overlap, progress=True,
                    segment=segment,
                )[0]
        except torch.cuda.OutOfMemoryError as e:
            logger.error(f"GPU 显存不足: {e}")
            # 降级策略：减小 segment 或切换到 CPU
            if self.device != "cpu" and segment > 3:
                new_segment = max(3, segment // 2)
                logger.warning(f"尝试减小 segment 至 {new_segment}s 重试...")
                with torch.no_grad():
                    sources = apply_model(
                        model, wav[None], device=self.device,
                        shifts=cli_args.shifts, split=cli_args.split,
                        overlap=cli_args.overlap, progress=True,
                        segment=new_segment,
                    )[0]
            else:
                logger.warning("切换到 CPU 执行...")
                model = model.to("cpu")
                wav = wav.to("cpu")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                with torch.no_grad():
                    sources = apply_model(
                        model, wav[None], device="cpu",
                        shifts=cli_args.shifts, split=cli_args.split,
                        overlap=cli_args.overlap, progress=True,
                        segment=segment,
                    )[0]

        # 反归一化
        sources = sources * ref.std()
        sources = sources + ref.mean()

        # 创建输出目录
        out = self.output_dir / self.model_name / self.track_name
        out.mkdir(parents=True, exist_ok=True)

        # 提取 vocals 和 no_vocals
        sources = list(sources)
        vocal = sources.pop(model.sources.index("vocals"))
        other = torch.zeros_like(sources[0])
        for s in sources:
            other += s

        # 保存
        save_audio(vocal, str(self._vocal_path),
                   samplerate=model.samplerate, clip="rescale",
                   as_float=True)
        save_audio(other, str(self._instrumental_path),
                   samplerate=model.samplerate, clip="rescale",
                   as_float=True)

    def _cleanup_temp(self, audio_path: str):
        if hasattr(self, "_temp_audio") and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass

    def __repr__(self) -> str:
        return (
            f"VocalSeparator(input={self.input_path.name}, "
            f"model={self.model_name})"
        )


# ── 便捷函数 ──────────────────────────────────────────

def separate_vocals(
    input_path: str,
    output_dir: Optional[str] = None,
    force: bool = False,
) -> Tuple[str, str]:
    separator = VocalSeparator(input_path, output_dir=output_dir)
    return separator.separate(force=force)


# ── 测试 / 示例 ──────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python VocalSeparator.py <input_audio_or_video> [output_dir]")
        sys.exit(1)

    input_file = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        sep = VocalSeparator(input_file, output_dir=out_dir, verbose=True)
        vocal, inst = sep.separate()
        print(f"\n结果:")
        print(f"  人声: {vocal}")
        print(f"  背景: {inst}")
    except Exception as e:
        logger.error(f"人声分离失败: {e}", exc_info=True)
        sys.exit(1)
