"""
Generate TTS narration from tutorial-script.md using EdgeTTS.
v2: Outputs timing.json for downstream coordination.
Usage: .venv/Scripts/python generate_tts.py
"""
import asyncio, json, os, shutil, subprocess

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tutorial-script.md")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration")
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+10%"

if os.path.exists(OUT_DIR):
    shutil.rmtree(OUT_DIR)
os.makedirs(OUT_DIR, exist_ok=True)


async def tts(text: str, out_path: str) -> None:
    """Synthesize text to MP3 via EdgeTTS."""
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(out_path)


def extract_sections(md_path: str) -> list[tuple[str, str, str]]:
    """
    Extract (section_id, section_title, narration_text) from markdown.
    Groups consecutive > lines under each ## header.
    Section id is sec01, sec02, etc. in order of appearance.
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    sections = []
    current_texts = []
    current_title = ""
    counter = -1  # start at -1 so first section is sec00

    for line in content.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("## ") and not line_stripped.startswith("### "):
            if current_texts:
                counter += 1
                sections.append((f"sec{counter:02d}", current_title, " ".join(current_texts)))
                current_texts = []
            current_title = line_stripped[3:].strip()
        elif line_stripped.startswith("> "):
            current_texts.append(line_stripped[2:])

    if current_texts:
        counter += 1
        sections.append((f"sec{counter:02d}", current_title, " ".join(current_texts)))

    return sections


def get_mp3_duration(path: str) -> float:
    """Get duration of an MP3 file in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


async def main():
    print("=== TTS Narration Generator v2 ===\n")
    print(f"Voice: {VOICE}, Rate: {RATE}")

    sections = extract_sections(SCRIPT)
    print(f"Found {len(sections)} narration sections\n")

    timing = {}

    for i, (sid, title, text) in enumerate(sections, 1):
        out_mp3 = os.path.join(OUT_DIR, f"{sid}.mp3")
        print(f"[{i}/{len(sections)}] {sid}: {title}")
        print(f"  Text: {text[:80]}...")
        await tts(text, out_mp3)

        duration = get_mp3_duration(out_mp3)
        timing[sid] = {
            "title": title,
            "duration": round(duration, 3),
            "text": text,
            "chars": len(text),
        }
        print(f"  Duration: {duration:.2f}s ({len(text)} chars)")

    # Write timing.json
    timing_path = os.path.join(OUT_DIR, "timing.json")
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing, f, ensure_ascii=False, indent=2)

    total = sum(t["duration"] for t in timing.values())
    print(f"\n=== Done: {len(sections)} files, {total:.1f}s total ===")
    print(f"Timing: {timing_path}")


if __name__ == "__main__":
    asyncio.run(main())
