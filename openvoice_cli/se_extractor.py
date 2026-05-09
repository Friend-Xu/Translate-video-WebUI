import os
from glob import glob
import torch
import hashlib
import base64
import numpy as np
from pydub import AudioSegment
from faster_whisper import WhisperModel

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WHISPER_ROOT = os.path.join(_PROJECT_ROOT, "models", "whisper")
_VAD_ROOT = os.path.join(_PROJECT_ROOT, "models", "vad")
os.makedirs(_WHISPER_ROOT, exist_ok=True)

model_size = "medium"
# Run on GPU with FP16
model = None
def split_audio_whisper(audio_path, audio_name, target_dir='processed',
                        device="cuda", compute_type="float16"):
    print("whisper")
    global model
    if model is None:
        model = WhisperModel(model_size, device=device,
                             compute_type=compute_type,
                             download_root=_WHISPER_ROOT)
    audio = AudioSegment.from_file(audio_path)
    max_len = len(audio)

    target_folder = os.path.join(target_dir, audio_name)
    
    segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True)
    segments = list(segments)    

    # create directory
    os.makedirs(target_folder, exist_ok=True)
    wavs_folder = os.path.join(target_folder, 'wavs')
    os.makedirs(wavs_folder, exist_ok=True)

    # segments
    s_ind = 0
    start_time = None
    
    for k, w in enumerate(segments):
        # process with the time
        if k == 0:
            start_time = max(0, w.start)

        end_time = w.end

        # calculate confidence
        if len(w.words) > 0:
            confidence = sum([s.probability for s in w.words]) / len(w.words)
        else:
            confidence = 0.
        # clean text
        text = w.text.replace('...', '')

        # left 0.08s for each audios
        audio_seg = audio[int( start_time * 1000) : min(max_len, int(end_time * 1000) + 80)]

        # segment file name
        fname = f"{audio_name}_seg{s_ind}.wav"

        # filter out the segment shorter than 1.5s and longer than 20s
        save = audio_seg.duration_seconds > 1.5 and \
                audio_seg.duration_seconds < 20. and \
                len(text) >= 2 and len(text) < 200 

        if save:
            output_file = os.path.join(wavs_folder, fname)
            audio_seg.export(output_file, format='wav')

        if k < len(segments) - 1:
            start_time = max(0, segments[k+1].start - 0.08)

        s_ind = s_ind + 1
    return wavs_folder


def _load_vad_model():
    """Load Silero VAD model from project's models/vad/ directory.

    Prefers JIT model for simpler API compatibility, falls back to ONNX.
    """
    jit_path = os.path.join(_VAD_ROOT, "silero_vad.jit")
    if os.path.isfile(jit_path):
        return torch.jit.load(jit_path)
    onnx_path = os.path.join(_VAD_ROOT, "silero_vad.onnx")
    if os.path.isfile(onnx_path):
        import onnxruntime
        return onnxruntime.InferenceSession(onnx_path, providers=['CPUExecutionProvider'])
    model, _ = torch.hub.load(
        "snakers4/silero-vad:v4.0", "silero_vad",
        force_reload=False, trust_repo=True)
    return model


def _get_speech_timestamps(audio_1d: torch.Tensor, model, sr: int = 16000):
    """Get speech segments using project's Silero VAD.

    Returns list of {'start': float, 'end': float} in seconds.
    """
    import onnxruntime

    if isinstance(model, onnxruntime.InferenceSession):
        # ONNX path: use OnnxWrapper properly
        from models.vad.utils_vad import OnnxWrapper, get_speech_timestamps as gst
        onnx_path = os.path.join(_VAD_ROOT, "silero_vad.onnx")
        wrapper = OnnxWrapper(onnx_path, force_onnx_cpu=True)
        return gst(audio_1d, wrapper, sampling_rate=16000,
                   min_speech_duration_ms=100, min_silence_duration_ms=1000,
                   return_seconds=True)
    else:
        from models.vad.utils_vad import get_speech_timestamps as gst
        return gst(audio_1d, model, sampling_rate=sr,
                   min_speech_duration_ms=100, min_silence_duration_ms=1000,
                   return_seconds=True)


def split_audio_vad(audio_path, audio_name, target_dir, split_seconds=10.0):
    SAMPLE_RATE = 16000

    # Load audio with torchaudio (replaces whisper_timestamped's get_audio_tensor)
    import torchaudio
    audio_vad, sr = torchaudio.load(audio_path)
    if audio_vad.shape[0] > 1:
        audio_vad = audio_vad.mean(dim=0)
    if sr != SAMPLE_RATE:
        audio_vad = torchaudio.functional.resample(
            audio_vad.unsqueeze(0), sr, SAMPLE_RATE).squeeze(0)

    # Run Silero VAD (replaces whisper_timestamped's get_vad_segments)
    vad_model = _load_vad_model()
    segments = _get_speech_timestamps(audio_vad, vad_model, SAMPLE_RATE)
    # segments are already in seconds when return_seconds=True
    segments = [(s["start"], s["end"]) for s in segments]
    audio_active = AudioSegment.silent(duration=0)
    audio = AudioSegment.from_file(audio_path)

    for start_time, end_time in segments:
        audio_active += audio[int( start_time * 1000) : int(end_time * 1000)]

    audio_dur = audio_active.duration_seconds
    print(f'after vad: dur = {audio_dur}')
    target_folder = os.path.join(target_dir, audio_name)
    wavs_folder = os.path.join(target_folder, 'wavs')
    os.makedirs(wavs_folder, exist_ok=True)
    start_time = 0.
    count = 0
    if audio_dur<5:
        if audio_dur < 0.2:
            exit("音频文件时长太短！！")
        else:
            num_splits = 1
    else:
        num_splits = int(np.round(audio_dur / split_seconds))
    assert num_splits > 0, 'input audio is too short'
    interval = audio_dur / num_splits

    for i in range(num_splits):
        end_time = min(start_time + interval, audio_dur)
        if i == num_splits - 1:
            end_time = audio_dur
        output_file = f"{wavs_folder}/{audio_name}_seg{count}.wav"
        audio_seg = audio_active[int(start_time * 1000): int(end_time * 1000)]
        audio_seg.export(output_file, format='wav')
        start_time = end_time
        count += 1
    return wavs_folder

def hash_numpy_array(audio_path):
    import torchaudio
    array, sr = torchaudio.load(audio_path)
    if array.shape[0] > 1:
        array = array.mean(dim=0)
    array_np = array.numpy()
    # Convert the array to bytes
    array_bytes = array_np.tobytes()
    # Calculate the hash of the array bytes
    hash_object = hashlib.sha256(array_bytes)
    hash_value = hash_object.digest()
    # Convert the hash value to base64
    base64_value = base64.b64encode(hash_value)
    return base64_value.decode('utf-8')[:16].replace('/', '_^')

def get_se(audio_path, vc_model, target_dir='processed', vad=True,
          whisper_device="cuda", compute_type="float16"):
    vc_device = vc_model.device

    audio_name = f"{os.path.basename(audio_path).rsplit('.', 1)[0]}_{hash_numpy_array(audio_path)}"
    se_path = os.path.join(target_dir, audio_name, 'se.pth')

    if os.path.isfile(se_path):
        se = torch.load(se_path).to(vc_device)
        return se, audio_name
    if os.path.isdir(audio_path):
        wavs_folder = audio_path
    elif vad:
        wavs_folder = split_audio_vad(audio_path, target_dir=target_dir, audio_name=audio_name)
    else:
        wavs_folder = split_audio_whisper(audio_path, target_dir=target_dir, audio_name=audio_name,
                                            device=whisper_device, compute_type=compute_type)
    
    audio_segs = glob(f'{wavs_folder}/*.wav')
    if len(audio_segs) == 0:
        raise NotImplementedError('No audio segments found!')
    
    return vc_model.extract_se(audio_segs, se_save_path=se_path), audio_name

