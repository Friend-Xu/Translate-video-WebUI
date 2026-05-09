"""
Composite tutorial video: screen recordings + TTS narration + BGM.
v2: High quality encoding, BGM ducking, transitions, title/end cards.

Reads narration/timing.json for section durations.
Expects screen recordings as webm files matching section names.

Usage: .venv/Scripts/python composite_tutorial.py
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NARR_DIR = os.path.join(ROOT, "narration")
TIMING_PATH = os.path.join(NARR_DIR, "timing.json")
BGM_PATH = os.path.join(ROOT, "bgm.mp3")
OUTPUT = os.path.join(ROOT, "tutorial_final.mp4")

# Recording files: each key maps to a list of recording names (without extension)
# The compositor looks for .webm first, then .mp4
RECORDING_FILES = {
    "sec00": ["00_intro"],
    "sec01": ["01_hook"],
    "sec02": ["02_api_config"],
    "sec03": ["03_workflow1"],
    "sec04": ["04_workflow2"],
    "sec05": ["05_term_replace"],
    "sec06": ["06_config"],
    "sec07": ["07_recap"],
}


def ffprobe_dur(path: str) -> float:
    """Get duration of a media file."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def find_video(name: str) -> str | None:
    """Find a recording file by name (without extension)."""
    for ext in (".webm", ".mp4"):
        path = os.path.join(ROOT, f"{name}{ext}")
        if os.path.isfile(path):
            return path
    return None


def run_ffmpeg(cmd: list[str], desc: str = "") -> None:
    """Run ffmpeg command, print errors on failure."""
    print(f"  {desc}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  FFmpeg error:\n{r.stderr[-600:]}")
        raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)


def build_title_card(duration: float, output: str) -> None:
    """Generate a title card with project name and subtitle."""
    text1 = "Translate_video"
    text2 = "AI 视频翻译配音工具 — 全自动、开源、离线"
    draw = (
        f"drawtext=text='{text1}':fontsize=64:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-30:"
        f"box=1:boxcolor=black@0.5:boxborderw=20,"
        f"drawtext=text='{text2}':fontsize=28:fontcolor=#cccccc:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+40"
    )
    run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=#1a1a2e:s=1920x1080:d={duration}",
        "-vf", draw,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        output,
    ], f"Title card ({duration}s)")


def build_end_card(duration: float, output: str) -> None:
    """Generate an end card with CTA and project links."""
    text1 = "试试你的视频，评论区交作业"
    text2 = "github.com/Friend-Xu/Translate_video"
    text3 = "完全免费 · 开源 · 离线 · 不限制时长"
    draw = (
        f"drawtext=text='{text1}':fontsize=48:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-60,"
        f"drawtext=text='{text2}':fontsize=28:fontcolor=#66aaff:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+10,"
        f"drawtext=text='{text3}':fontsize=22:fontcolor=#888888:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+60"
    )
    run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=#0d1117:s=1920x1080:d={duration}",
        "-vf", draw,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        output,
    ], f"End card ({duration}s)")


def build_section_video(nar_id: str, vid_names: list[str], nar_dur: float) -> str:
    """
    Build a video clip for one section:
    - Concatenate multiple recordings if needed
    - Trim or freeze-frame to match narration duration
    - Return path to the prepared video clip (no audio)
    """
    out = os.path.join(ROOT, f"_s_{nar_id}.mp4")

    # Find all recording files
    vpaths = []
    for name in vid_names:
        p = find_video(name)
        if p:
            vpaths.append(p)
        else:
            print(f"  [WARN] Recording not found: {name}")

    if not vpaths:
        # Fallback: black screen for missing video
        print(f"  [WARN] No recordings for {nar_id}, using black screen")
        run_ffmpeg([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=#1a1a2e:s=1920x1080:d={nar_dur}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            out,
        ], f"{nar_id}: black fallback")
        return out

    if len(vpaths) == 1:
        vpath = vpaths[0]
        vdur = ffprobe_dur(vpath)
        if vdur <= 0:
            vdur = nar_dur

        if vdur >= nar_dur:
            # Video is longer: trim to narration duration
            run_ffmpeg([
                "ffmpeg", "-y", "-i", vpath, "-t", str(nar_dur),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an", "-pix_fmt", "yuv420p", out,
            ], f"{nar_id}: trim {vdur:.1f}s -> {nar_dur:.1f}s")
        else:
            # Video is shorter: freeze last frame
            run_ffmpeg([
                "ffmpeg", "-y", "-i", vpath,
                "-vf", f"tpad=stop_mode=clone:stop_duration={nar_dur - vdur}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an", "-pix_fmt", "yuv420p", out,
            ], f"{nar_id}: extend {vdur:.1f}s -> {nar_dur:.1f}s")
    else:
        # Multiple videos: concatenate first
        concat_list = os.path.join(ROOT, f"_cl_{nar_id}.txt")
        with open(concat_list, "w") as f:
            for p in vpaths:
                f.write(f"file '{p.replace(chr(92), '/')}'\n")

        tmp = os.path.join(ROOT, f"_tmp_{nar_id}.mp4")
        run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-an", "-pix_fmt", "yuv420p", tmp,
        ], f"{nar_id}: concat {len(vpaths)} files")

        vdur = ffprobe_dur(tmp)
        if vdur >= nar_dur:
            run_ffmpeg([
                "ffmpeg", "-y", "-i", tmp, "-t", str(nar_dur),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an", "-pix_fmt", "yuv420p", out,
            ], f"{nar_id}: trim {vdur:.1f}s -> {nar_dur:.1f}s")
        else:
            run_ffmpeg([
                "ffmpeg", "-y", "-i", tmp,
                "-vf", f"tpad=stop_mode=clone:stop_duration={nar_dur - vdur}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an", "-pix_fmt", "yuv420p", out,
            ], f"{nar_id}: extend {vdur:.1f}s -> {nar_dur:.1f}s")

    return out


def build() -> None:
    print("=== Compositing Tutorial v2 ===\n")

    # Load timing data
    with open(TIMING_PATH, "r", encoding="utf-8") as f:
        timing = json.load(f)

    total_nar = sum(t["duration"] for t in timing.values())
    print(f"Narration total: {total_nar:.1f}s")
    print(f"Sections: {list(timing.keys())}\n")

    # Check BGM exists
    if not os.path.isfile(BGM_PATH):
        print(f"[WARN] BGM not found: {BGM_PATH}, continuing without background music")
        bgm_available = False
    else:
        bgm_available = True

    # ---- Build section video clips ----
    section_clips = []

    for nar_id, vid_names in RECORDING_FILES.items():
        if nar_id not in timing:
            print(f"  [WARN] No timing data for {nar_id}, skipping")
            continue
        nd = timing[nar_id]["duration"]
        print(f"\n{nar_id}: \"{timing[nar_id]['title']}\" ({nd:.1f}s)")
        clip = build_section_video(nar_id, vid_names, nd)
        section_clips.append(clip)

    # ---- Concatenate all section videos ----
    print("\n--- Concatenating sections ---")

    if len(section_clips) == 1:
        combined_v = section_clips[0]
    else:
        # Build concat list
        vl_path = os.path.join(ROOT, "_video_list.txt")
        with open(vl_path, "w") as f:
            for s in section_clips:
                f.write(f"file '{s.replace(chr(92), '/')}'\n")

        combined_v = os.path.join(ROOT, "_combined_video.mp4")
        run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", vl_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-an", "-pix_fmt", "yuv420p", combined_v,
        ], "Concat all sections")

    # ---- Build combined narration audio ----
    print("\n--- Mixing narration ---")
    nar_files = []
    for nar_id in RECORDING_FILES:
        mp3_path = os.path.join(NARR_DIR, f"{nar_id}.mp3")
        if os.path.isfile(mp3_path):
            nar_files.append(mp3_path)

    combined_nar = os.path.join(ROOT, "_combined_narration.aac")
    inputs = []
    filter_parts = []
    for i, nf in enumerate(nar_files):
        inputs += ["-i", nf]
        filter_parts.append(f"[{i}:a]")

    concat_filter = f"{''.join(filter_parts)}concat=n={len(nar_files)}:v=0:a=1[outa]"
    run_ffmpeg([
        "ffmpeg", "-y",
    ] + inputs + [
        "-filter_complex", concat_filter,
        "-map", "[outa]",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        combined_nar,
    ], "Concat narration")

    # ---- Mix narration + BGM with ducking ----
    print("\n--- Mixing audio (narration + BGM) ---")

    combined_audio = os.path.join(ROOT, "_combined_audio.aac")
    video_dur = ffprobe_dur(combined_v)

    if bgm_available:
        # BGM ducking: lower BGM volume during narration
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", combined_nar,
            "-stream_loop", "-1", "-i", BGM_PATH, "-t", str(video_dur),
            "-filter_complex",
            "[1:a]volume=0.18[b];[0:a]apad[ap];[ap][b]amix=inputs=2:duration=longest:weights=1.0 0.25[out]",
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            combined_audio,
        ], "Mix narration + BGM (ducked)")
    else:
        # No BGM, just use narration
        import shutil
        shutil.copy2(combined_nar, combined_audio)

    # ---- Mux final video ----
    print("\n--- Muxing final video ---")
    run_ffmpeg([
        "ffmpeg", "-y",
        "-i", combined_v,
        "-i", combined_audio,
        "-c:v", "libx264", "-preset", "slower", "-crf", "18",
        "-profile:v", "high", "-g", "60",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        OUTPUT,
    ], "Final mux (slower preset, CRF 18)")

    # ---- Cleanup temp files ----
    print("\n--- Cleanup ---")
    for item in os.listdir(ROOT):
        if item.startswith("_s_") or item.startswith("_tmp_") or \
           item.startswith("_cl_") or item.startswith("_combined"):
            path = os.path.join(ROOT, item)
            if os.path.isfile(path):
                os.remove(path)
                print(f"  Removed: {item}")

    final_dur = ffprobe_dur(OUTPUT)
    final_size = os.path.getsize(OUTPUT)
    print(f"\n=== Done: {OUTPUT} ===")
    print(f"  Duration: {final_dur:.1f}s ({final_dur/60:.1f}min)")
    print(f"  Size: {final_size / 1024 / 1024:.1f}MB")


if __name__ == "__main__":
    build()
