"""
VAD_Segmenter.py — Silero VAD 语音活动检测封装

依据「字幕提取优化方案 v1.0」Phase 2 规格实现。
- 使用 Silero VAD（whisperX 底层同款）
- 模型集成在项目 models/vad/ 目录，便于管理和移动
- 后处理：合并短间隔、过滤短语音、限制最大段长
- JSON 缓存：避免重复推理
"""

import os
import sys
import json
import logging
import tempfile
import warnings
from pathlib import Path
from typing import List, Tuple, Optional

import torch
import torchaudio

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("VAD_Segmenter")


# ── 模型路径常量 ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
VAD_MODEL_DIR = PROJECT_ROOT / "models" / "vad"
VAD_MODEL_JIT = VAD_MODEL_DIR / "silero_vad.jit"
VAD_UTILS_PATH = VAD_MODEL_DIR / "utils_vad.py"

# Silero 固定采样率
SILERO_SR = 16000

# 默认后处理参数
DEFAULT_VAD_THRESHOLD = 0.25       # Silero VAD 检测阈值（默认 0.5，ASMR 等弱人声需降低）
DEFAULT_MIN_SILENCE_GAP = 3.0      # 间隔 < 3s 的段合并
DEFAULT_MIN_SPEECH_DURATION = 0.5  # 丢弃 < 0.5s 的语音段
DEFAULT_MAX_SEGMENT_DURATION = 900.0  # 最大段长 15min (900s)
DEFAULT_PAD_DURATION = 0.3         # 前后 padding 0.3s


class VAD_Segmenter:
    """Silero VAD 语音活动检测封装

    Usage:
        seg = VAD_Segmenter("path/to/audio.wav")
        segments = seg.get_segments()  # [(start_s, end_s), ...]
    """

    def __init__(
        self,
        audio_path: str,
        min_silence_gap: float = DEFAULT_MIN_SILENCE_GAP,
        min_speech_duration: float = DEFAULT_MIN_SPEECH_DURATION,
        max_segment_duration: float = DEFAULT_MAX_SEGMENT_DURATION,
        pad_duration: float = DEFAULT_PAD_DURATION,
        threshold: float = DEFAULT_VAD_THRESHOLD,
        device: str = "cpu",
    ):
        """
        Args:
            audio_path: 音频文件路径（视频或音频）
            min_silence_gap: 间隔小于此值的段合并（秒）
            min_speech_duration: 丢弃小于此值的语音段（秒）
            max_segment_duration: 单段最大时长（秒）
            pad_duration: 段前后 padding（秒）
            device: 运行设备
        """
        self.audio_path = Path(audio_path)
        if not self.audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        self.min_silence_gap = min_silence_gap
        self.min_speech_duration = min_speech_duration
        self.max_segment_duration = max_segment_duration
        self.pad_duration = pad_duration
        self.threshold = threshold
        self.device = device

        # 缓存文件路径
        self._cache_path = self.audio_path.parent / f"{self.audio_path.stem}_vad_segments.json"

        # 加载模型
        self._model = None
        self._utils = None

    # ── 公共接口 ──────────────────────────────────────

    def get_segments(self, force: bool = False) -> List[Tuple[float, float]]:
        """获取 VAD 分段结果

        Args:
            force: 若 True，跳过缓存重新推理

        Returns:
            [(start_s, end_s), ...] 按时间排序
        """
        if not force:
            cached = self._load_cache()
            if cached is not None:
                logger.info(f"VAD 结果已从缓存加载: {self._cache_path}")
                return cached

        # 1. 准备音频（提取/转采样）
        wav_path = self._prepare_audio()

        # 2. 运行 VAD
        raw_segments = self._run_vad(wav_path)
        logger.info(f"VAD 原始结果: {len(raw_segments)} 段")

        # 3. 后处理
        segments = self._post_process(raw_segments)
        logger.info(f"后处理后: {len(segments)} 段")

        # 4. 保存缓存
        self._save_cache(segments)

        # 5. 清理临时文件
        self._cleanup_temp(wav_path)

        return segments

    def save_cache(self, segments: List[Tuple[float, float]]):
        """手动保存分段结果到缓存"""
        self._save_cache(segments)

    def clear_cache(self):
        """清除缓存文件"""
        if self._cache_path.exists():
            self._cache_path.unlink()
            logger.info(f"缓存已清除: {self._cache_path}")

    @property
    def cache_path(self) -> str:
        return str(self._cache_path)

    # ── 内部方法 ──────────────────────────────────────

    def _prepare_audio(self) -> str:
        """准备音频：视频→提取，非16kHz→重采样

        Returns:
            16kHz WAV 文件路径（可能是临时文件）
        """
        ext = self.audio_path.suffix.lower()
        is_video = ext not in {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma"}

        if is_video:
            # 提取音频
            temp_wav = os.path.join(
                tempfile.gettempdir(),
                f"vad_{self.audio_path.stem}_{os.urandom(4).hex()}.wav",
            )
            self._extract_audio(str(self.audio_path), temp_wav)
            src_path = temp_wav
            self._temp_wav = temp_wav
        else:
            src_path = str(self.audio_path)

        # 检查采样率 (兼容 torchaudio 2.x, 其已移除 info API)
        import wave as _wav_mod
        def _get_sr(p):
            with _wav_mod.open(str(p), 'rb') as _w:
                return _w.getframerate()
        sample_rate = _get_sr(src_path)
        if sample_rate != SILERO_SR:
            temp_wav16 = os.path.join(
                tempfile.gettempdir(),
                f"vad_16k_{self.audio_path.stem}_{os.urandom(4).hex()}.wav",
            )
            import soundfile as _sf
            _wav_np, sr = _sf.read(src_path)
            _wav_t = torch.from_numpy(_wav_np).float()
            if _wav_t.ndim == 1:
                _wav_t = _wav_t.unsqueeze(0)
            else:
                _wav_t = _wav_t.T
            wav = torchaudio.functional.resample(_wav_t, sr, SILERO_SR)
            torchaudio.save(temp_wav16, wav, SILERO_SR)
            self._temp_wav16 = temp_wav16

            # 清理原始临时文件
            if hasattr(self, "_temp_wav") and self._temp_wav != src_path:
                try:
                    os.remove(self._temp_wav)
                except OSError:
                    pass

            return temp_wav16

        return src_path

    def _extract_audio(self, video_path: str, output_wav: str):
        """用 ffmpeg 提取音轨为 16kHz mono WAV"""
        ffmpeg = self._get_ffmpeg_path()
        import subprocess
        subprocess.run(
            [ffmpeg, "-y", "-i", video_path,
             "-vn", "-acodec", "pcm_s16le",
             "-ar", str(SILERO_SR), "-ac", "1",
             output_wav],
            capture_output=True, check=True,
        )

    @staticmethod
    def _get_ffmpeg_path() -> str:
        for p in os.environ.get("PATH", "").split(os.pathsep):
            ff_path = os.path.join(p, "ffmpeg.exe")
            if os.path.exists(ff_path):
                return ff_path
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            raise RuntimeError("ffmpeg 未找到。请安装 imageio-ffmpeg")

    def _run_vad(self, wav_path: str) -> List[Tuple[float, float]]:
        """运行 Silero VAD，返回原始时间段
        
        长音频 (>5min) 分块处理，避免内存溢出
        """
        import gc
        import torchaudio

        model = self._load_model()
        get_speech_timestamps, _, *_ = self._load_utils()

        # 获取音频信息 (兼容 torchaudio 2.x)
        import wave as _wav_mod
        with _wav_mod.open(str(wav_path), 'rb') as _wav_fp:
            sr = _wav_fp.getframerate()
            total_samples = _wav_fp.getnframes()
            duration_s = total_samples / sr

        # 短音频直接处理
        if duration_s <= 300:  # 5分钟内直接处理
            import torch
            import soundfile as _sf
            _wav_np, sr_loaded = _sf.read(wav_path)
            _wav_t = torch.from_numpy(_wav_np).float()
            if _wav_t.ndim == 1:
                _wav_t = _wav_t.unsqueeze(0)
            else:
                _wav_t = _wav_t.T
            if sr_loaded != SILERO_SR:
                wav = torchaudio.functional.resample(_wav_t, sr_loaded, SILERO_SR)
            else:
                wav = _wav_t
            # 转单声道
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0)
            else:
                wav = wav.squeeze(0)
            timestamps = get_speech_timestamps(
                wav, model,
                sampling_rate=SILERO_SR,
                threshold=self.threshold,
                min_speech_duration_ms=int(self.min_speech_duration * 1000),
                min_silence_duration_ms=250,
            )
            segments = [(t["start"] / SILERO_SR, t["end"] / SILERO_SR) for t in timestamps]
            return segments

        # 长音频分块处理 (每块 5min，重叠 1s)
        logger.info(f"长音频 {duration_s:.0f}s，分块 VAD 处理...")
        CHUNK_SAMPLES = SILERO_SR * 300  # 5min @ 16kHz
        OVERLAP_SAMPLES = SILERO_SR * 1   # 1s overlap

        all_segments = []
        offset = 0
        chunk_idx = 0

        while offset < total_samples:
            chunk_idx += 1
            end_sample = min(offset + CHUNK_SAMPLES, total_samples)
            num_frames = end_sample - offset

            # 加载块
            import soundfile as _sf
            _wav_np, sr_loaded = _sf.read(wav_path, start=offset, frames=num_frames)
            _wav_t = torch.from_numpy(_wav_np).float()
            if _wav_t.ndim == 1:
                _wav_t = _wav_t.unsqueeze(0)
            else:
                _wav_t = _wav_t.T
            if sr_loaded != SILERO_SR:
                wav = torchaudio.functional.resample(_wav_t, sr_loaded, SILERO_SR)
            else:
                wav = _wav_t
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0)
            else:
                wav = wav.squeeze(0)

            # VAD
            timestamps = get_speech_timestamps(
                wav, model,
                sampling_rate=SILERO_SR,
                threshold=self.threshold,
                min_speech_duration_ms=int(self.min_speech_duration * 1000),
                min_silence_duration_ms=250,
            )

            # 偏移到全局时间
            time_offset = offset / sr
            for t in timestamps:
                seg_start = time_offset + t["start"] / SILERO_SR
                seg_end = time_offset + t["end"] / SILERO_SR
                all_segments.append((seg_start, seg_end))

            logger.info(f"  块 {chunk_idx}: {time_offset:.0f}s-{time_offset + num_frames/sr:.0f}s, "
                          f"检测到 {len(timestamps)} 段")

            # 清理内存
            del wav
            gc.collect()

            # 下一帧（减去重叠）
            if end_sample >= total_samples:
                break
            offset = end_sample - OVERLAP_SAMPLES

        return all_segments

    def _post_process(self, segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """VAD 后处理：合并、过滤、切割"""
        if not segments:
            return []

        # 1. 按时间排序
        segments = sorted(segments, key=lambda x: x[0])

        # 2. 合并间隔小的段
        merged = []
        current_start, current_end = segments[0]
        for start, end in segments[1:]:
            if start - current_end < self.min_silence_gap:
                # 合并
                current_end = end
            else:
                merged.append((current_start, current_end))
                current_start, current_end = start, end
        merged.append((current_start, current_end))

        # 3. 过滤过短的段
        merged = [(s, e) for s, e in merged if e - s >= self.min_speech_duration]

        # 4. 添加 padding
        padded = []
        for start, end in merged:
            padded.append((
                max(0.0, start - self.pad_duration),
                end + self.pad_duration,
            ))

        # 5. 限制最大段长（强制切割）
        final = []
        for start, end in padded:
            duration = end - start
            if duration <= self.max_segment_duration:
                final.append((start, end))
            else:
                # 强制切割为 max_segment_duration 的段
                num_chunks = int(duration / self.max_segment_duration) + 1
                chunk_size = duration / num_chunks
                for i in range(num_chunks):
                    chunk_start = start + i * chunk_size
                    chunk_end = min(end, start + (i + 1) * chunk_size)
                    final.append((chunk_start, chunk_end))

        return final

    def _load_model(self):
        """加载 Silero VAD 模型（优先本地缓存）"""
        if self._model is not None:
            return self._model

        if VAD_MODEL_JIT.exists():
            # 本地加载
            logger.debug(f"从本地加载 VAD 模型: {VAD_MODEL_JIT}")
            model = torch.jit.load(str(VAD_MODEL_JIT), map_location=self.device)
        else:
            # 从 torch.hub 下载
            logger.info("本地模型不存在，从 torch.hub 下载 Silero VAD...")
            model, _ = torch.hub.load(
                "snakers4/silero-vad:v4.0",
                "silero_vad",
                force_reload=False,
                trust_repo=True,
            )
            # 保存到项目目录
            VAD_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            model.save(str(VAD_MODEL_JIT))
            logger.info(f"模型已保存到: {VAD_MODEL_JIT}")

        model.eval()
        self._model = model
        return model

    def _load_utils(self):
        """加载 Silero VAD 工具函数（优先本地）"""
        if self._utils is not None:
            return self._utils

        if VAD_UTILS_PATH.exists():
            # 动态导入本地 utils
            import importlib.util
            spec = importlib.util.spec_from_file_location("vad_utils", str(VAD_UTILS_PATH))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._utils = (
                module.get_speech_timestamps,
                module.read_audio,
                module.save_audio,
                module.VADIterator,
                module.collect_chunks,
            )
        else:
            # 从 torch.hub 加载
            _, utils = torch.hub.load(
                "snakers4/silero-vad:v4.0",
                "silero_vad",
                force_reload=False,
                trust_repo=True,
            )
            self._utils = utils

        return self._utils

    def _save_cache(self, segments: List[Tuple[float, float]]):
        """保存 VAD 结果到 JSON"""
        data = {
            "audio_path": str(self.audio_path),
            "sample_rate": SILERO_SR,
            "parameters": {
                "threshold": self.threshold,
                "min_silence_gap": self.min_silence_gap,
                "min_speech_duration": self.min_speech_duration,
                "max_segment_duration": self.max_segment_duration,
                "pad_duration": self.pad_duration,
            },
            "segments": [{"start": s, "end": e} for s, e in segments],
        }
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"VAD 结果已缓存: {self._cache_path}")

    def _load_cache(self) -> Optional[List[Tuple[float, float]]]:
        """从 JSON 加载缓存（参数匹配时才使用）"""
        if not self._cache_path.exists():
            return None

        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 检查参数是否匹配
            params = data.get("parameters", {})
            if (
                params.get("threshold") == self.threshold
                and params.get("min_silence_gap") == self.min_silence_gap
                and params.get("min_speech_duration") == self.min_speech_duration
                and params.get("max_segment_duration") == self.max_segment_duration
                and params.get("pad_duration") == self.pad_duration
            ):
                return [(s["start"], s["end"]) for s in data["segments"]]

            logger.debug("缓存参数不匹配，重新推理")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"缓存文件损坏，重新推理: {e}")
            return None

    def _cleanup_temp(self, wav_path: str):
        """清理临时文件"""
        for attr in ("_temp_wav", "_temp_wav16"):
            if hasattr(self, attr):
                path = getattr(self, attr)
                if path and os.path.exists(path) and path != str(self.audio_path):
                    try:
                        os.remove(path)
                        logger.debug(f"已清理临时文件: {path}")
                    except OSError:
                        pass

    def __repr__(self) -> str:
        return (
            f"VAD_Segmenter(audio={self.audio_path.name}, "
            f"model={'local' if VAD_MODEL_JIT.exists() else 'hub'})"
        )


# ── 便捷函数 ──────────────────────────────────────────

def detect_speech_segments(
    audio_path: str,
    min_silence_gap: float = DEFAULT_MIN_SILENCE_GAP,
    min_speech_duration: float = DEFAULT_MIN_SPEECH_DURATION,
    max_segment_duration: float = DEFAULT_MAX_SEGMENT_DURATION,
) -> List[Tuple[float, float]]:
    """一键检测语音段

    Returns:
        [(start_s, end_s), ...]
    """
    seg = VAD_Segmenter(
        audio_path,
        min_silence_gap=min_silence_gap,
        min_speech_duration=min_speech_duration,
        max_segment_duration=max_segment_duration,
    )
    return seg.get_segments()


# ── 测试 / 示例 ──────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Silero VAD 语音段检测")
    parser.add_argument("audio", help="音频或视频文件路径")
    parser.add_argument("--min-gap", type=float, default=3.0, help="合并间隔阈值(秒)")
    parser.add_argument("--min-speech", type=float, default=0.5, help="最小语音段(秒)")
    parser.add_argument("--max-seg", type=float, default=900.0, help="最大段长(秒)")
    parser.add_argument("--force", action="store_true", help="强制重新推理")
    args = parser.parse_args()

    seg = VAD_Segmenter(
        args.audio,
        min_silence_gap=args.min_gap,
        min_speech_duration=args.min_speech,
        max_segment_duration=args.max_seg,
    )

    segments = seg.get_segments(force=args.force)
    print(f"\n检测到 {len(segments)} 个语音段:")
    total = 0.0
    for i, (start, end) in enumerate(segments, 1):
        duration = end - start
        total += duration
        print(f"  [{i:2d}] {start:8.2f}s - {end:8.2f}s  ({duration:6.2f}s)")
    print(f"\n总语音时长: {total:.1f}s")
    print(f"缓存路径: {seg.cache_path}")
