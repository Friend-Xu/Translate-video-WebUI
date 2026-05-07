"""Benchmark beam_size=1 vs beam_size=2 on Test_JP.mp4"""
import sys, os, time, gc
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))

from pipeline.transcriber import VADTranscriber
from pipeline.utils import get_ffmpeg_exe
from pipeline.audio import extract_audio_bare

VIDEO = "source_file/Test_JP.mp4"
WAV = "source_file/Test_JP_beam_test.wav"

print("=" * 60)
print("Beam Size Benchmark: beam_size=1 vs beam_size=2")
print("=" * 60)

# Step 1: Extract audio
print("\n[1/3] Extracting audio...")
ffmpeg_exe = get_ffmpeg_exe()
if not os.path.exists(WAV):
    extract_audio_bare(VIDEO, WAV, ffmpeg_exe)
    print(f"  Extracted: {WAV}")
else:
    print(f"  Using cached: {WAV}")

# Step 2: Run VAD once (reuse for both tests)
print("\n[2/3] Running VAD...")
t = VADTranscriber(WAV, model_name="turbo", device="cuda", compute_type="float16", num_workers=1)
segments, vad_time = t.run_vad(force=False)
print(f"  VAD: {len(segments)} segments, {vad_time:.1f}s")
audio_len = t._audio_len
print(f"  Audio duration: {audio_len:.1f}s")

# Step 3: Test beam_size=1 and beam_size=2
results = {}
for bs in [1, 2]:
    print(f"\n[3/3] Testing beam_size={bs}...")
    t2 = VADTranscriber(WAV, model_name="turbo", device="cuda", compute_type="float16", num_workers=1)
    t2._vad_segments = segments
    t2._audio_len = audio_len

    # Patch _transcribe_batch to use specific beam_size
    def make_transcribe(beam, transcriber):
        import soundfile as sf
        import numpy as np

        def patched_transcribe(seg_start, seg_end, audio_array=None, model=None):
            lang = getattr(transcriber, '_language', None) or 'ja'
            seg_dur = seg_end - seg_start
            start_sample = int(seg_start * transcriber.sample_rate)
            num_samples = int(seg_dur * transcriber.sample_rate)
            if audio_array is not None:
                audio_seg = audio_array[start_sample:start_sample + num_samples].copy()
                if audio_seg.dtype != np.float32:
                    audio_seg = audio_seg.astype(np.float32)
            else:
                audio_seg, _ = sf.read(transcriber.audio_path, start=start_sample, frames=num_samples)
                audio_seg = audio_seg.astype(np.float32)

            whisper_model = model if model is not None else transcriber._model_pool.get()
            seg_words = []
            segments_out, info = whisper_model.transcribe(
                audio_seg, language=lang, word_timestamps=True,
                beam_size=beam, vad_filter=False,
            )
            for seg in segments_out:
                if seg.words:
                    for w in seg.words:
                        seg_words.append({
                            "word": w.word.strip(),
                            "start": w.start + seg_start,
                            "end": w.end + seg_start,
                        })
            del audio_seg, segments_out
            return seg_words

        return patched_transcribe

    t2._transcribe_batch = make_transcribe(bs, t2)

    t0_bs = time.time()
    result = t2.transcribe_all(language="ja")
    elapsed = time.time() - t0_bs

    stats = result["stats"]
    word_count = len(result["words"])
    seg_count = len(result["segments"])
    results[bs] = {
        "time": elapsed, "words": word_count, "segments": seg_count,
        "sample": result["segments"][:3],
        "model_load": stats["model_load_time"],
        "transcribe": stats["transcribe_time"],
    }
    print(f"  beam_size={bs}: load={stats['model_load_time']:.1f}s, transcribe={stats['transcribe_time']:.1f}s, "
          f"total={elapsed:.1f}s, {word_count} words, {seg_count} segments")

    del t2
    gc.collect()
    import torch
    torch.cuda.empty_cache()

# Summary
print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
b1, b2 = results[1], results[2]
ratio = b2["transcribe"] / b1["transcribe"] if b1["transcribe"] > 0 else 0
print(f"  beam_size=1:  transcribe={b1['transcribe']:.1f}s, total={b1['time']:.1f}s, {b1['words']} words, {b1['segments']} segments")
print(f"  beam_size=2:  transcribe={b2['transcribe']:.1f}s, total={b2['time']:.1f}s, {b2['words']} words, {b2['segments']} segments")
print(f"  Speed ratio:  bs=1 is {ratio:.2f}x faster (transcribe time)")
print(f"  Word diff:    {b2['words'] - b1['words']} (bs=2 - bs=1)")
print(f"  Seg diff:     {b2['segments'] - b1['segments']}")

print("\n--- Sample output comparison (first 3 segments) ---")
for bs in [1, 2]:
    print(f"\n  beam_size={bs}:")
    for seg in results[bs]["sample"]:
        print(f"  [{seg['start']:.1f}s-{seg['end']:.1f}s] {seg['text'][:120]}")

# Cleanup
if os.path.exists(WAV):
    os.remove(WAV)
    print(f"\nCleaned up {WAV}")
