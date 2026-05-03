"""
Demucs 人声分离模块 — 从视频提取纯背景乐。

绕过 torchaudio/torchcodec 依赖，用 soundfile 加载音频。
"""
import os
import subprocess
import numpy as np
import soundfile as sf
import torch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEMUCS_LOCAL_DIR = os.path.join(PROJECT_ROOT, "models", "Demucs")


def _ensure_torch_home():
    """确保 TORCH_HOME 指向项目本地 models/ 目录。"""
    models_root = os.path.join(PROJECT_ROOT, "models")
    os.environ.setdefault("TORCH_HOME", models_root)
    os.makedirs(os.path.join(models_root, "hub", "checkpoints"), exist_ok=True)
    os.makedirs(_DEMUCS_LOCAL_DIR, exist_ok=True)


def extract_instrumental(video_path: str, output_dir: str, model_name: str = "htdemucs") -> str:
    """从视频中提取纯背景乐（去除人声）。

    Args:
        video_path: 输入视频路径
        output_dir: 输出目录（会在下面创建 htdemucs/<name>/）
        model_name: Demucs 模型名

    Returns:
        no_vocals.wav 的完整路径
    """
    name = os.path.splitext(os.path.basename(video_path))[0]
    out_root = os.path.join(output_dir, model_name, name)
    instr_path = os.path.join(out_root, "no_vocals.wav")

    if os.path.isfile(instr_path):
        print(f"  [Demucs] 已存在: {instr_path}")
        return instr_path

    os.makedirs(out_root, exist_ok=True)

    # ── Step 1: ffmpeg 提取音频 ──────────────────────
    from pipeline.utils import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    tmp_wav = os.path.join(output_dir, f"_demucs_tmp_{name}.wav")
    print(f"  [Demucs] 提取音频: {os.path.basename(video_path)}")
    subprocess.run(
        [ffmpeg, "-y", "-i", video_path, "-vn",
         "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
         tmp_wav],
        capture_output=True, check=True,
    )

    # ── Step 2: soundfile 加载 ──────────────────────
    print(f"  [Demucs] 加载音频...")
    data, sr = sf.read(tmp_wav, dtype='float32')
    if data.ndim == 1:
        data = data[:, np.newaxis]
    tensor = torch.from_numpy(data.T).unsqueeze(0)
    ref = tensor.mean(dim=0)
    tensor = (tensor - ref.mean()) / ref.std()

    # ── Step 3: 加载模型 ──────────────────────────────
    print(f"  [Demucs] 加载 {model_name} 模型...")
    _ensure_torch_home()
    from demucs import pretrained
    from demucs.apply import apply_model
    model = pretrained.get_model(model_name)

    # 将 checkpoint 备份到 models/Demucs/ 方便离线使用
    import shutil, glob as _glob
    hub_ckpt_dir = os.path.join(os.environ["TORCH_HOME"], "hub", "checkpoints")
    for src in _glob.glob(os.path.join(hub_ckpt_dir, f"{model_name}*")):
        dst = os.path.join(_DEMUCS_LOCAL_DIR, os.path.basename(src))
        if not os.path.isfile(dst):
            shutil.copy2(src, dst)
            print(f"  [Demucs] checkpoint 已备份: {dst}")
    model.cpu()
    model.eval()

    # ── Step 4: 分离 ──────────────────────────────
    print(f"  [Demucs] 分离人声/伴奏...")
    with torch.no_grad():
        sources = apply_model(
            model, tensor, device='cpu',
            shifts=1, split=True, overlap=0.25, progress=True,
        )[0]

    source_names = model.sources
    for idx, src_name in enumerate(source_names):
        src = sources[idx].cpu().numpy().T
        sf.write(os.path.join(out_root, f"{src_name}.wav"), src, model.samplerate)

    # 合成 instrumental（除 vocals 外的所有轨道之和）
    if 'vocals' in source_names:
        vocal_idx = source_names.index('vocals')
        instr_sources = [s for i, s in enumerate(sources.cpu().numpy()) if i != vocal_idx]
        instr = np.sum(instr_sources, axis=0).T
        sf.write(instr_path, instr, model.samplerate)
        print(f"  [Demucs] → {instr_path}")

    # 清理
    os.remove(tmp_wav)
    return instr_path
