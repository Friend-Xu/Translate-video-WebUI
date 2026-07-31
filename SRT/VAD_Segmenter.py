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

import numpy as np
import torch
import torchaudio

try:
    import onnxruntime
    _ONNX_AVAILABLE = True
except ImportError:
    _ONNX_AVAILABLE = False

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
VAD_MODEL_ONNX = VAD_MODEL_DIR / "silero_vad.onnx"
VAD_UTILS_PATH = VAD_MODEL_DIR / "utils_vad.py"

# Silero 固定采样率
SILERO_SR = 16000

# 默认后处理参数
DEFAULT_VAD_THRESHOLD = 0.25       # Silero VAD 检测阈值（默认 0.5，ASMR 等弱人声需降低）
DEFAULT_MIN_SILENCE_GAP = 0.5      # 间隔 < 0.5s 的段合并（WhisperX 标准：~0.5s）
DEFAULT_MIN_SPEECH_DURATION = 0.5  # 丢弃 < 0.5s 的语音段
DEFAULT_MAX_SEGMENT_DURATION = 30.0  # 最大段长 30s（匹配 whisper 训练窗口）
DEFAULT_PAD_DURATION = 0.2         # 前后 padding 0.2s


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
        # Path("") == Path(".") 恒存在, 空路径必须显式拒绝 (禁止兜底: 不静默用当前目录)
        if not audio_path or not self.audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path!r}")

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
        self._onnx_session = None  # ONNX Runtime session (优先使用)

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

    def _vad_inference(self, audio_1d: torch.Tensor) -> list:
        """逐窗口 VAD 推理，返回语音概率列表。
        优先使用 ONNX Runtime，fallback 到 JIT。
        """
        onnx_session = self._load_onnx()
        if onnx_session is not None:
            return self._vad_inference_onnx(audio_1d, onnx_session)
        return self._vad_inference_jit(audio_1d)

    def _vad_inference_onnx(self, audio_1d: torch.Tensor, session) -> list:
        """ONNX Runtime 推理（~9x 快于 JIT）"""
        window_size = 512
        h = np.zeros((2, 1, 64), dtype=np.float32)
        c = np.zeros((2, 1, 64), dtype=np.float32)

        total = len(audio_1d)
        pad_total = (total + window_size - 1) // window_size * window_size
        if pad_total > total:
            audio_1d = torch.nn.functional.pad(audio_1d, (0, pad_total - total))

        probs = []
        for i in range(0, pad_total, window_size):
            chunk = audio_1d[i:i + window_size].unsqueeze(0).numpy().astype(np.float32)
            ort_in = {'input': chunk, 'h': h, 'c': c, 'sr': np.array(16000, dtype=np.int64)}
            out, h, c = session.run(None, ort_in)
            probs.append(float(out.squeeze()))
        return probs

    def _vad_inference_jit(self, audio_1d: torch.Tensor) -> list:
        """JIT 推理（fallback，与 utils_vad.py 逻辑一致）"""
        model = self._load_model()
        window_size = 512
        model.reset_states()
        probs = []
        total = len(audio_1d)
        for start in range(0, total, window_size):
            chunk = audio_1d[start:start + window_size]
            if len(chunk) < window_size:
                chunk = torch.nn.functional.pad(chunk, (0, window_size - len(chunk)))
            probs.append(model(chunk.unsqueeze(0), 16000).item())
        return probs

    def _probs_to_segments(self, probs: list, sampling_rate: int = 16000) -> list:
        """语音概率列表 → 时间段（与 utils_vad.py get_speech_timestamps 后处理一致）"""
        window_size = 512
        threshold = self.threshold
        min_speech_ms = int(self.min_speech_duration * 1000)
        min_silence_ms = 250
        speech_pad_ms = 30

        min_speech_samples = sampling_rate * min_speech_ms / 1000
        min_silence_samples = sampling_rate * min_silence_ms / 1000
        speech_pad_samples = sampling_rate * speech_pad_ms / 1000
        audio_length_samples = len(probs) * window_size

        triggered = False
        speeches = []
        current_speech = {}
        neg_threshold = threshold - 0.15
        temp_end = 0

        for i, sp in enumerate(probs):
            if sp >= threshold and temp_end:
                temp_end = 0
            if sp >= threshold and not triggered:
                triggered = True
                current_speech['start'] = window_size * i
                continue
            if sp < neg_threshold and triggered:
                if not temp_end:
                    temp_end = window_size * i
                if (window_size * i) - temp_end < min_silence_samples:
                    continue
                else:
                    current_speech['end'] = temp_end
                    if (current_speech['end'] - current_speech['start']) > min_speech_samples:
                        speeches.append(current_speech)
                    temp_end = 0
                    current_speech = {}
                    triggered = False
                    continue

        if current_speech and (audio_length_samples - current_speech['start']) > min_speech_samples:
            current_speech['end'] = audio_length_samples
            speeches.append(current_speech)

        for i, s in enumerate(speeches):
            if i == 0:
                s['start'] = int(max(0, s['start'] - speech_pad_samples))
            if i != len(speeches) - 1:
                silence_dur = speeches[i + 1]['start'] - s['end']
                if silence_dur < 2 * speech_pad_samples:
                    s['end'] += int(silence_dur // 2)
                    speeches[i + 1]['start'] = int(max(0, speeches[i + 1]['start'] - silence_dur // 2))
                else:
                    s['end'] = int(min(audio_length_samples, s['end'] + speech_pad_samples))
                    speeches[i + 1]['start'] = int(max(0, speeches[i + 1]['start'] - speech_pad_samples))
            else:
                s['end'] = int(min(audio_length_samples, s['end'] + speech_pad_samples))

        return [(s['start'] / sampling_rate, s['end'] / sampling_rate) for s in speeches]

    def _run_vad(self, wav_path: str) -> List[Tuple[float, float]]:
        """运行 Silero VAD，返回原始时间段

        优先使用 ONNX Runtime（~9x 加速），fallback 到 JIT。
        长音频 (>5min) 分块处理，避免内存溢出。
        """
        import gc
        import torchaudio

        onnx_available = self._load_onnx() is not None
        backend = "ONNX" if onnx_available else "JIT"
        if not onnx_available:
            self._load_model()

        import wave as _wav_mod
        with _wav_mod.open(str(wav_path), 'rb') as _wav_fp:
            sr = _wav_fp.getframerate()
            total_samples = _wav_fp.getnframes()
            duration_s = total_samples / sr

        def _load_to_1d(wav_np, sr_loaded):
            t = torch.from_numpy(wav_np).float()
            if t.ndim == 1:
                t = t.unsqueeze(0)
            else:
                t = t.T
            if sr_loaded != SILERO_SR:
                t = torchaudio.functional.resample(t, sr_loaded, SILERO_SR)
            if t.shape[0] > 1:
                t = t.mean(dim=0)
            else:
                t = t.squeeze(0)
            return t

        if duration_s <= 300:
            import soundfile as _sf
            _wav_np, sr_loaded = _sf.read(wav_path)
            audio = _load_to_1d(_wav_np, sr_loaded)
            probs = self._vad_inference(audio)
            return self._probs_to_segments(probs)

        logger.info(f"长音频 {duration_s:.0f}s，分块 VAD 处理 [{backend}]...")
        CHUNK_SAMPLES = SILERO_SR * 300
        OVERLAP_SAMPLES = SILERO_SR * 1

        all_segments = []
        offset = 0
        chunk_idx = 0

        while offset < total_samples:
            chunk_idx += 1
            end_sample = min(offset + CHUNK_SAMPLES, total_samples)
            num_frames = end_sample - offset

            import soundfile as _sf
            _wav_np, sr_loaded = _sf.read(wav_path, start=offset, frames=num_frames)
            audio = _load_to_1d(_wav_np, sr_loaded)

            probs = self._vad_inference(audio)
            segments = self._probs_to_segments(probs)

            time_offset = offset / sr
            for seg_start, seg_end in segments:
                all_segments.append((time_offset + seg_start, time_offset + seg_end))

            logger.info(f"  块 {chunk_idx}: {time_offset:.0f}s-{time_offset + num_frames/sr:.0f}s, "
                        f"检测到 {len(segments)} 段")

            del audio
            gc.collect()

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

        # 5. 限制最大段长（智能切割，避免切在单词中间）
        final = []
        for start, end in padded:
            duration = end - start
            if duration <= self.max_segment_duration:
                final.append((start, end))
            else:
                # 拆分为多个子段，段间留 0.05s 间隙避免切词
                chunk_size = self.max_segment_duration
                chunk_start = start
                while chunk_start < end:
                    chunk_end = min(end, chunk_start + chunk_size)
                    final.append((chunk_start, chunk_end))
                    chunk_start = chunk_end + 0.05  # 小间隙

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

    def _load_onnx(self):
        """加载 ONNX Runtime 会话（比 JIT 快 ~9x）"""
        if self._onnx_session is not None:
            return self._onnx_session
        if not _ONNX_AVAILABLE or not VAD_MODEL_ONNX.exists():
            return None
        logger.debug(f"从本地加载 ONNX VAD 模型: {VAD_MODEL_ONNX}")
        session = onnxruntime.InferenceSession(
            str(VAD_MODEL_ONNX),
            providers=['CPUExecutionProvider'],
        )
        session.intra_op_num_threads = 4
        session.inter_op_num_threads = 1
        self._onnx_session = session
        return session

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
