"""Quick 20-segment TTS pipeline test."""
import os, sys, time, shutil
PROJ = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ)

workspace = os.path.join(PROJ, "source_file",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
    "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric_project")
srt_path = os.path.join(workspace, "02_translate", "machine.srt")

# Backup full SRT, write 20-entry version
with open(srt_path, "r", encoding="utf-8") as f:
    full_srt = f.read()
blocks = full_srt.strip().split("\n\n")
print(f"Total SRT blocks: {len(blocks)}, using 20")

with open(srt_path, "w", encoding="utf-8") as f:
    f.write("\n\n".join(blocks[:20]) + "\n\n")

try:
    # Clear old TTS outputs so resume manager doesn't skip everything
    import glob
    for pattern in ["TTS_*.mp4", "_*.mp4"]:
        for f in glob.glob(os.path.join(workspace, "03_tts", "video", pattern)):
            os.remove(f)
    clone_dir = os.path.join(workspace, "03_tts", "cloned")
    if os.path.isdir(clone_dir):
        shutil.rmtree(clone_dir)
    # Reset checkpoint
    ck_path = os.path.join(workspace, "checkpoint.json")
    if os.path.isfile(ck_path):
        import json as _json
        ck = _json.load(open(ck_path))
        if "steps" in ck and "tts" in ck["steps"]:
            ck["steps"]["tts"]["status"] = "pending"
            _json.dump(ck, open(ck_path, "w"), indent=2, ensure_ascii=False)
    # Delete old final output
    dubbed = os.path.join(workspace, "04_output", "dubbed.mp4")
    if os.path.isfile(dubbed):
        os.remove(dubbed)

    t0 = time.time()
    import subprocess
    result = subprocess.run([
        os.path.join(PROJ, ".venv", "Scripts", "python.exe"), "-u",
        os.path.join(PROJ, "main.py"),
        os.path.join(PROJ, "source_file",
            "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric",
            "TOP 30 Minecraft Mods OF The Month ｜ October 2025 (1.20.1 ⧸ 1.21+) - Forge & Fabric.mp4"),
        "--engine", "chattts",
        "--skip-extract", "--skip-translate",
        "--skip-demucs",
        "--config", os.path.join(PROJ, "config", "tts.yaml"),
    ])
    elapsed = time.time() - t0
    print(f"\n20 segments: {elapsed/60:.1f} min (exit={result.returncode})")
finally:
    # Restore full SRT
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(full_srt)
