"""
Generate SRT subtitles synced to narration timing, then burn into final video.
v2: Uses timing.json for accurate section boundaries, improved styling.
Usage: .venv/Scripts/python generate_subtitles.py
"""
import json, os, re, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
NARR_DIR = os.path.join(ROOT, "narration")
TIMING_PATH = os.path.join(NARR_DIR, "timing.json")
SRT_OUT = os.path.join(ROOT, "tutorial_subtitles.srt")
VIDEO_IN = os.path.join(ROOT, "tutorial_final.mp4")
VIDEO_OUT = os.path.join(ROOT, "tutorial_final_subbed.mp4")


def fmt_time(sec: float) -> str:
    """Format seconds to SRT timestamp: HH:MM:SS,mmm"""
    ms = int((sec % 1) * 1000)
    s = int(sec) % 60
    m = int(sec) // 60 % 60
    h = int(sec) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_sentences(text: str) -> list[str]:
    """Split Chinese text into sentence-like chunks."""
    parts = re.split(r'([。！？，；\n]|[.]\s+)', text)
    sentences = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        buffer += part
        if re.search(r'[。！？]$', part.strip()):
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
        elif re.search(r'[.]\\s*$', part.strip()):
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        sentences.append(buffer.strip())
    if not sentences:
        sentences = [text]
    return sentences


def build() -> None:
    print("=== Generating Subtitles v2 ===\n")

    with open(TIMING_PATH, "r", encoding="utf-8") as f:
        timing = json.load(f)

    entries = []
    current_time = 0.0

    for sec_id in sorted(timing.keys()):
        info = timing[sec_id]
        duration = info["duration"]
        text = info["text"]

        sentences = split_sentences(text)
        if not sentences:
            continue

        char_counts = [len(s) for s in sentences]
        total_chars = sum(char_counts)
        if total_chars == 0:
            total_chars = 1

        for i, sentence in enumerate(sentences):
            sent_dur = duration * (char_counts[i] / total_chars)
            sent_dur = max(sent_dur, 1.5)

            start = current_time
            end = start + sent_dur

            if sentence.strip():
                entries.append({
                    "start": start,
                    "end": end,
                    "text": sentence.strip(),
                })
            current_time = end

        # Snap to section boundary
        cum = 0.0
        for sid in sorted(timing.keys()):
            cum += timing[sid]["duration"]
            if sid == sec_id:
                current_time = cum
                break

    # Write SRT
    with open(SRT_OUT, "w", encoding="utf-8") as f:
        for idx, entry in enumerate(entries, 1):
            f.write(f"{idx}\n")
            f.write(f"{fmt_time(entry['start'])} --> {fmt_time(entry['end'])}\n")
            f.write(f"{entry['text']}\n\n")

    print(f"Wrote {len(entries)} subtitle entries to {SRT_OUT}")

    # Burn subtitles
    print("\n--- Burning subtitles ---")
    if not os.path.isfile(VIDEO_IN):
        print(f"[WARN] Input video not found: {VIDEO_IN}")
        print(f"SRT file created: {SRT_OUT}")
        return

    srt_path = SRT_OUT.replace("\\", "/").replace(":", "\\:")
    style = (
        "FontSize=28,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,Outline=2.5,Shadow=1.5,"
        "BorderStyle=1,Alignment=2,MarginV=72"
    )

    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", VIDEO_IN,
        "-vf", f"subtitles='{srt_path}':force_style='{style}'",
        "-c:v", "libx264", "-preset", "slower", "-crf", "18",
        "-profile:v", "high", "-g", "60",
        "-c:a", "copy",
        "-movflags", "+faststart",
        VIDEO_OUT,
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"FFmpeg error:\n{result.stderr[-600:]}")
        raise subprocess.CalledProcessError(result.returncode, [], result.stdout, result.stderr)

    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", VIDEO_OUT]).decode().strip())
    size_mb = os.path.getsize(VIDEO_OUT) / 1024 / 1024
    print(f"\n=== Done: {VIDEO_OUT} ===")
    print(f"  Duration: {dur:.1f}s, Size: {size_mb:.1f}MB")


if __name__ == "__main__":
    build()
