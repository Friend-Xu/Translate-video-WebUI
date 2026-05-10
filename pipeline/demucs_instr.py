"""
Demucs 人声分离模块 — 从视频提取纯背景乐。

长视频自动分段处理，避免 OOM：
  - 音频 > CHUNK_THRESHOLD 秒时，ffmpeg 切成带重叠的 N 段
  - 每段独立调用 apply_model(segment=7)，内存占用 ~100MB/段
  - 段间 10s 重叠 + 首尾 trim 消除边界杂音，ffmpeg concat 拼接

方案依据:
  - 官方 README: htdemucs 最大 segment=7.8s, "Demucs stores whole audio in memory"
  - Issue #498/#580: 官方建议 "split your file into shorter chunks before passing to demucs"
  - Torchaudio 教程: 标准做法为 chunk + overlap + fade 消除边界效应
"""
import os
import subprocess
import json
import tempfile
import numpy as np
import soundfile as sf
import torch

from pipeline.logger import get_logger
from pipeline.loudness import calculate_bgm_gain, apply_gain_to_wav

logger = get_logger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEMUCS_LOCAL_DIR = os.path.join(PROJECT_ROOT, "models", "Demucs")

# htdemucs 架构限制最大 ~7.8s，取 7s
_DEMUCS_SEGMENT = 7
# 音频超过此时长（秒）启用文件级预分段
_CHUNK_THRESHOLD = 300   # 5 min
_CHUNK_DURATION = 300     # 每段有效长度
_CHUNK_OVERLAP = 10       # 段间重叠秒数（首尾各 trim 一半）


def _ensure_torch_home():
    models_root = os.path.join(PROJECT_ROOT, "models")
    os.environ.setdefault("TORCH_HOME", models_root)
    os.makedirs(os.path.join(models_root, "hub", "checkpoints"), exist_ok=True)
    os.makedirs(_DEMUCS_LOCAL_DIR, exist_ok=True)


def _get_audio_duration(wav_path: str) -> float:
    import wave
    with wave.open(wav_path, 'rb') as f:
        return f.getnframes() / f.getframerate()


def _build_chunk_plan(total_duration: float) -> list[tuple[float, float, float]]:
    """生成带重叠的分段计划。

    Returns: [(extract_start, extract_end, keep_start, keep_end), ...]
      extract_*  — ffmpeg 提取范围（含重叠上下文）
      keep_*     — 拼接时保留的有效范围（相对于 extract_start）

    示例（300s chunk + 10s overlap，第一个 chunk 无重叠前缀）:
      Chunk 0: extract [0, 305),  keep [0, 300)
      Chunk 1: extract [295, 610), keep [5, 305)
      Chunk N: extract [N*300-5, N*300+305), keep [5, 305)
      Last:    keep 到末尾
    """
    half = _CHUNK_OVERLAP / 2
    plans = []
    pos = 0.0
    is_first = True

    while pos < total_duration:
        if is_first:
            ext_start = 0.0
            ext_end = min(_CHUNK_DURATION + half, total_duration)
            keep_start = 0.0
        else:
            ext_start = pos - half
            ext_end = min(pos + _CHUNK_DURATION + half, total_duration)
            keep_start = half

        keep_end = ext_end - ext_start
        # 最后一个 chunk 无重叠后缀
        if ext_end >= total_duration:
            keep_end = ext_end - ext_start

        plans.append((ext_start, ext_end, keep_start, keep_end))
        pos = ext_start + _CHUNK_DURATION
        is_first = False

        if ext_end >= total_duration:
            break

    return plans


def _extract_chunk(ffmpeg: str, wav_path: str, out_path: str,
                   start_s: float, duration_s: float) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-i", wav_path,
         "-ss", str(start_s), "-t", str(duration_s),
         "-c", "copy", out_path],
        capture_output=True, check=True,
    )
    # -c copy 可能在非关键帧处不准，重试用重编码
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        subprocess.run(
            [ffmpeg, "-y", "-i", wav_path,
             "-ss", str(start_s), "-t", str(duration_s),
             "-acodec", "pcm_s16le", out_path],
            capture_output=True, check=True,
        )


def _load_and_norm(wav_path: str):
    data, sr = sf.read(wav_path, dtype='float32')
    if data.ndim == 1:
        data = data[:, np.newaxis]
    tensor = torch.from_numpy(data.T).unsqueeze(0)
    ref = tensor.mean(dim=0)
    tensor = (tensor - ref.mean()) / ref.std()
    return tensor, sr, ref


def _concat_wavs_ffmpeg(ffmpeg: str, wav_paths: list[str], output_path: str) -> None:
    concat_list = os.path.join(os.path.dirname(output_path), "_concat_list.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in wav_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", output_path],
        capture_output=True, check=True,
    )
    os.remove(concat_list)


def _trim_wav(ffmpeg: str, src: str, dst: str,
              trim_start_s: float, trim_end_s: float) -> None:
    """从 WAV 中裁剪首尾指定时长。"""
    duration = _get_audio_duration(src)
    new_start = trim_start_s
    new_dur = duration - trim_start_s - trim_end_s
    if new_dur <= 0:
        import shutil
        shutil.copy2(src, dst)
        return
    subprocess.run(
        [ffmpeg, "-y", "-i", src,
         "-ss", str(new_start), "-t", str(new_dur),
         "-c", "copy", dst],
        capture_output=True, check=True,
    )
    # -c copy 可能因帧边界不准，重试重编码
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        subprocess.run(
            [ffmpeg, "-y", "-i", src,
             "-ss", str(new_start), "-t", str(new_dur),
             "-acodec", "pcm_s16le", dst],
            capture_output=True, check=True,
        )


def extract_instrumental(video_path: str, output_dir: str,
                         model_name: str = "htdemucs",
                         bgm_volume: float = 1.0) -> str:
    """从视频中提取纯背景乐（去除人声）。

    长视频自动分段处理，段间带重叠消除边界效应。

    Args:
        bgm_volume: 背景乐音量比例 (0.0~2.0, 1.0=自动补偿响度损失)
    """
    import shutil

    name = os.path.splitext(os.path.basename(video_path))[0]
    out_root = os.path.join(output_dir, model_name, name)
    instr_path = os.path.join(out_root, "no_vocals.wav")

    if os.path.isfile(instr_path):
        logger.info(f"已存在: {instr_path}")
        return instr_path

    os.makedirs(out_root, exist_ok=True)
    from pipeline.utils import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    # ── Step 1: ffmpeg 提取音频 ──────────────────────
    tmp_wav = os.path.join(output_dir, f"_demucs_tmp_{name}.wav")
    logger.info(f"提取音频: {os.path.basename(video_path)}")
    subprocess.run(
        [ffmpeg, "-y", "-i", video_path, "-vn",
         "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
         tmp_wav],
        capture_output=True, check=True,
    )

    # ── Step 2: 加载模型（只加载一次） ─────────────────
    logger.info(f"加载 {model_name} 模型...")
    _ensure_torch_home()
    from demucs import pretrained
    from demucs.apply import apply_model
    model = pretrained.get_model(model_name)

    hub_ckpt_dir = os.path.join(os.environ["TORCH_HOME"], "hub", "checkpoints")
    for src in __import__("glob").glob(os.path.join(hub_ckpt_dir, f"{model_name}*")):
        dst = os.path.join(_DEMUCS_LOCAL_DIR, os.path.basename(src))
        if not os.path.isfile(dst):
            shutil.copy2(src, dst)
            logger.info(f"checkpoint 已备份: {dst}")
    model.cpu()
    model.eval()

    source_names = model.sources
    sample_rate = model.samplerate

    # ── Step 3: 决定是否分段 ─────────────────────────
    duration = _get_audio_duration(tmp_wav)
    logger.info(f"音频时长: {duration/60:.1f} 分钟")

    if duration <= _CHUNK_THRESHOLD:
        # 短音频：直接全量处理
        logger.info(f"短音频，直接处理")
        tensor, sr, ref = _load_and_norm(tmp_wav)
        if sr != sample_rate:
            from demucs.audio import convert_audio
            tensor = convert_audio(tensor, sr, sample_rate, model.audio_channels)

        with torch.no_grad():
            sources = apply_model(
                model, tensor, device='cpu',
                shifts=1, split=True, overlap=0.25,
                segment=_DEMUCS_SEGMENT, progress=True,
            )[0]
        sources = sources * ref.std() + ref.mean()

        for idx, src_name in enumerate(source_names):
            sf.write(os.path.join(out_root, f"{src_name}.wav"),
                     sources[idx].cpu().numpy().T, sample_rate)
        del tensor, sources, ref
    else:
        # ── 长音频：重叠分段处理 ──────────────────────
        chunk_plan = _build_chunk_plan(duration)
        logger.info(f"长音频，切分为 {len(chunk_plan)} 段 "
              f"({_CHUNK_OVERLAP}s overlap)")

        # 临时目录存放提取的原始重叠片段
        extract_dir = tempfile.mkdtemp(prefix="demucs_extract_")
        per_source_segments = {s: [] for s in source_names}

        for i, (ext_start, ext_end, keep_start, keep_end) in enumerate(chunk_plan):
            ext_dur = ext_end - ext_start
            chunk_raw = os.path.join(extract_dir, f"raw_{i:03d}.wav")
            logger.info(f"提取段 {i+1}/{len(chunk_plan)}: "
                  f"[{ext_start:.0f}s, {ext_end:.0f}s)")
            _extract_chunk(ffmpeg, tmp_wav, chunk_raw, ext_start, ext_dur)

            tensor, sr, ref = _load_and_norm(chunk_raw)
            if sr != sample_rate:
                from demucs.audio import convert_audio
                tensor = convert_audio(tensor, sr, sample_rate, model.audio_channels)

            logger.info(f"分离段 {i+1}/{len(chunk_plan)}: "
                  f"{os.path.basename(chunk_raw)}")
            with torch.no_grad():
                sources = apply_model(
                    model, tensor, device='cpu',
                    shifts=1, split=True, overlap=0.25,
                    segment=_DEMUCS_SEGMENT, progress=True,
                )[0]
            sources = sources * ref.std() + ref.mean()

            # 保存完整段输出（含重叠部分）
            for idx, src_name in enumerate(source_names):
                seg_full = os.path.join(extract_dir, f"seg_{i:03d}_{src_name}.wav")
                sf.write(seg_full, sources[idx].cpu().numpy().T, sample_rate)

                # 裁剪掉重叠区，保留有效段
                trim_start = keep_start
                trim_end = max(0, (ext_end - ext_start) - keep_end)
                if trim_start > 0 or trim_end > 0:
                    seg_trimmed = os.path.join(extract_dir,
                                               f"trim_{i:03d}_{src_name}.wav")
                    _trim_wav(ffmpeg, seg_full, seg_trimmed, trim_start, trim_end)
                    per_source_segments[src_name].append(seg_trimmed)
                    os.remove(seg_full)
                else:
                    per_source_segments[src_name].append(seg_full)

            del tensor, sources, ref
            os.remove(chunk_raw)

        # ── 拼接各源 ──────────────────────────────
        logger.info(f"拼接 {len(chunk_plan)} 段...")
        for src_name in source_names:
            final_path = os.path.join(out_root, f"{src_name}.wav")
            seg_list = per_source_segments[src_name]
            if len(seg_list) == 1:
                shutil.move(seg_list[0], final_path)
            else:
                _concat_wavs_ffmpeg(ffmpeg, seg_list, final_path)
                for p in seg_list:
                    if os.path.isfile(p):
                        os.remove(p)

        shutil.rmtree(extract_dir)

    # ── Step 4: 合成 instrumental ────────────────────
    if 'vocals' in source_names:
        non_vocal_paths = [os.path.join(out_root, f"{s}.wav")
                           for s in source_names if s != 'vocals']
        if len(non_vocal_paths) > 1:
            inputs = []
            filter_parts = []
            for idx, p in enumerate(non_vocal_paths):
                inputs.extend(["-i", p])
                filter_parts.append(f"[{idx}:a]")
            amix = (f"{''.join(filter_parts)}"
                    f"amix=inputs={len(non_vocal_paths)}:duration=longest")
            subprocess.run(
                [ffmpeg, "-y"] + inputs +
                ["-filter_complex", amix,
                 "-acodec", "pcm_s16le", instr_path],
                capture_output=True, check=True,
            )
        else:
            shutil.copy2(non_vocal_paths[0], instr_path)
        logger.info(f"→ {instr_path}")

    # ── Step 5: BGM 响度补偿 ──────────────────────────
    if bgm_volume > 0:
        gain_db = calculate_bgm_gain(tmp_wav, instr_path, target_ratio=bgm_volume)
        if abs(gain_db) > 0.1:
            normalized = instr_path + ".normalized.wav"
            apply_gain_to_wav(instr_path, normalized, gain_db)
            os.replace(normalized, instr_path)
            logger.info(f"BGM 响度已补偿: {gain_db:+.1f} dB")

    del model
    torch.cuda.empty_cache()
    import gc
    gc.collect()
    os.remove(tmp_wav)
    return instr_path
